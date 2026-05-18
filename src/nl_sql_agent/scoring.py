from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any

from nl_sql_agent.sql_safety import normalize_sql, validate_readonly_sql
from nl_sql_agent.sqlite_tools import SQLiteToolkit


@dataclass
class SQLScore:
    validation_success: bool
    execution_success: bool
    exact_sql_match: bool
    result_match: bool
    generated_result_hash: str | None
    gold_result_hash: str | None
    error: str | None = None


def score_sql(toolkit: SQLiteToolkit, generated_sql: str, gold_sql: str) -> SQLScore:
    generated_validation = validate_readonly_sql(generated_sql)
    if not generated_validation.ok:
        return SQLScore(False, False, False, False, None, None, generated_validation.error)

    gold_validation = validate_readonly_sql(gold_sql)
    if not gold_validation.ok:
        return SQLScore(True, False, False, False, None, None, f"Gold SQL invalid: {gold_validation.error}")

    exact = _safe_normalize(generated_sql) == _safe_normalize(gold_sql)
    generated = toolkit.execute_query(generated_sql, max_rows=10_000)
    gold = toolkit.execute_query(gold_sql, max_rows=10_000)
    if not generated.ok:
        return SQLScore(True, False, exact, False, None, None, generated.error)
    if not gold.ok:
        return SQLScore(True, False, exact, False, None, None, f"Gold execution failed: {gold.error}")

    if len(generated.columns) != len(gold.columns):
        return SQLScore(True, True, exact, False, None, None, "Result column counts differ.")

    generated_rows = canonicalize_result(generated.rows, generated.columns)
    gold_rows = canonicalize_result(gold.rows, gold.columns)
    generated_hash = hash_rows(generated_rows)
    gold_hash = hash_rows(gold_rows)
    return SQLScore(True, True, exact, generated_hash == gold_hash, generated_hash, gold_hash)


def canonicalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        normalized.append({key: normalize_value(value) for key, value in sorted(row.items())})
    return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def canonicalize_result(rows: list[dict[str, Any]], columns: list[str]) -> list[list[Any]]:
    normalized = []
    for row in rows:
        normalized.append([normalize_value(row.get(column)) for column in columns])
    return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))


def normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return round(value, 8)
    if isinstance(value, bytes):
        return value.hex()
    return value


def hash_rows(rows: list[dict[str, Any]] | list[list[Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _safe_normalize(sql: str) -> str:
    try:
        return normalize_sql(sql).lower()
    except Exception:
        return " ".join(sql.lower().split())
