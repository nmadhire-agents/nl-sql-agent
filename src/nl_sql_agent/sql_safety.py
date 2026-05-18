from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str | None = None
    normalized_sql: str | None = None


UNSAFE_EXPRESSIONS = (
    exp.Alter,
    exp.Command,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.Update,
)


def normalize_sql(sql: str) -> str:
    parsed = sqlglot.parse_one(sql, read="sqlite")
    return parsed.sql(dialect="sqlite", pretty=False).strip()


def format_sql(sql: str) -> str:
    parsed = sqlglot.parse_one(sql, read="sqlite")
    return parsed.sql(dialect="sqlite", pretty=True).strip()


def validate_readonly_sql(sql: str) -> ValidationResult:
    text = sql.strip()
    if not text:
        return ValidationResult(False, "SQL is empty.")

    try:
        statements = sqlglot.parse(text, read="sqlite")
    except Exception as exc:
        return ValidationResult(False, f"SQL parse failed: {exc}")

    if len(statements) != 1:
        return ValidationResult(False, "Only a single SQL statement is allowed.")

    statement = statements[0]
    if statement is None:
        return ValidationResult(False, "SQL parse produced no statement.")

    if any(isinstance(node, UNSAFE_EXPRESSIONS) for node in statement.walk()):
        return ValidationResult(False, "Only read-only SELECT/WITH queries are allowed.")

    if not _is_readonly_query(statement):
        return ValidationResult(False, "Only SELECT, WITH, UNION, INTERSECT, or EXCEPT queries are allowed.")

    try:
        normalized = statement.sql(dialect="sqlite", pretty=False).strip()
    except Exception:
        normalized = text.rstrip(";")

    return ValidationResult(True, normalized_sql=normalized)


def _is_readonly_query(statement: exp.Expression) -> bool:
    return isinstance(
        statement,
        (
            exp.Select,
            exp.Union,
            exp.Except,
            exp.Intersect,
        ),
    )
