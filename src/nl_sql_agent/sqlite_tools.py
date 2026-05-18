from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

from nl_sql_agent.sql_safety import ValidationResult, validate_readonly_sql


@dataclass
class QueryResult:
    ok: bool
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    truncated: bool
    error: str | None = None


class SQLiteToolkit:
    def __init__(self, db_path: Path, max_rows: int = 100, timeout_seconds: float = 10) -> None:
        self.db_path = Path(db_path)
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds
        self.last_validated_sql: str | None = None
        self.last_executed_sql: str | None = None
        self.last_error: str | None = None

    @contextmanager
    def connect(self, readonly: bool = True) -> Iterator[sqlite3.Connection]:
        if readonly:
            uri = f"file:{self.db_path.resolve()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds)
        else:
            conn = sqlite3.connect(self.db_path, timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        deadline = time.monotonic() + self.timeout_seconds

        def check_timeout() -> int:
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(check_timeout, 1000)
        try:
            yield conn
        finally:
            conn.close()

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def search_tables(self, query: str) -> dict[str, Any]:
        terms = expanded_terms(query)
        matches: list[dict[str, Any]] = []
        for table in self.list_tables():
            schema = self.table_schema(table)
            haystack = " ".join([table, *[col["name"] for col in schema["columns"]]]).lower()
            if not terms or any(term in haystack for term in terms):
                matches.append(schema)
        if not matches:
            matches = [self.table_schema(table) for table in self.list_tables()[:20]]
        return {"ok": True, "tables": matches[:20]}

    def get_schema_info(self, table_names: list[str]) -> dict[str, Any]:
        available = set(self.list_tables())
        schemas = []
        for table in table_names:
            if table in available:
                schemas.append(self.table_schema(table))
        return {"ok": True, "schemas": schemas, "missing": [t for t in table_names if t not in available]}

    def table_schema(self, table_name: str) -> dict[str, Any]:
        with self.connect() as conn:
            ddl_row = conn.execute(
                "SELECT sql, type FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
                (table_name,),
            ).fetchone()
            columns = conn.execute(f"PRAGMA table_info({quote_ident(table_name)})").fetchall()
            foreign_keys = conn.execute(f"PRAGMA foreign_key_list({quote_ident(table_name)})").fetchall()
            indexes = conn.execute(f"PRAGMA index_list({quote_ident(table_name)})").fetchall()
        return {
            "table": table_name,
            "type": ddl_row["type"] if ddl_row else None,
            "ddl": ddl_row["sql"] if ddl_row else None,
            "columns": [
                {
                    "name": row["name"],
                    "type": row["type"],
                    "notnull": bool(row["notnull"]),
                    "default": row["dflt_value"],
                    "primary_key": bool(row["pk"]),
                }
                for row in columns
            ],
            "foreign_keys": [dict(row) for row in foreign_keys],
            "indexes": [dict(row) for row in indexes],
        }

    def validate_sql(self, sql: str) -> dict[str, Any]:
        validation = validate_readonly_sql(sql)
        if not validation.ok:
            self.last_error = validation.error
            return validation.__dict__
        try:
            with self.connect() as conn:
                conn.execute(f"EXPLAIN QUERY PLAN {validation.normalized_sql}").fetchall()
        except Exception as exc:
            self.last_error = str(exc)
            return ValidationResult(False, f"SQLite validation failed: {exc}").__dict__
        self.last_validated_sql = validation.normalized_sql
        self.last_error = None
        return validation.__dict__

    def execute_query(self, sql: str, max_rows: int | None = None) -> QueryResult:
        validation_payload = self.validate_sql(sql)
        if not validation_payload["ok"]:
            return QueryResult(False, [], [], 0, False, validation_payload["error"])

        normalized = validation_payload["normalized_sql"]
        limit = max_rows or self.max_rows
        try:
            with self.connect() as conn:
                cursor = conn.execute(normalized)
                rows = cursor.fetchmany(limit + 1)
                columns = [description[0] for description in cursor.description or []]
        except Exception as exc:
            self.last_error = str(exc)
            return QueryResult(False, [], [], 0, False, str(exc))

        truncated = len(rows) > limit
        visible_rows = rows[:limit]
        payload_rows = [{column: row[column] for column in columns} for row in visible_rows]
        self.last_executed_sql = normalized
        self.last_error = None
        return QueryResult(True, payload_rows, columns, len(payload_rows), truncated)


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def expanded_terms(query: str) -> list[str]:
    raw_terms = [part.strip(".,?!:;()[]{}'\"").lower() for part in query.replace("_", " ").split()]
    terms: set[str] = set()
    for term in raw_terms:
        if not term:
            continue
        terms.add(term)
        if term.endswith("ies") and len(term) > 3:
            terms.add(term[:-3] + "y")
        if term.endswith("s") and len(term) > 3:
            terms.add(term[:-1])
    return sorted(terms)
