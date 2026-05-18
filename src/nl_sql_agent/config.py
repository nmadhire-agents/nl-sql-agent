from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    default_db_path: Path | None
    max_rows: int
    query_timeout_seconds: float
    trace_backend: str
    trace_mode: str
    phoenix_collector_endpoint: str
    judge_model: str
    agent_model: str


def load_settings() -> Settings:
    load_dotenv()
    default_db = os.getenv("NL_SQL_DEFAULT_DB_PATH")
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        default_db_path=Path(default_db) if default_db else None,
        max_rows=int(os.getenv("NL_SQL_MAX_ROWS", "100")),
        query_timeout_seconds=float(os.getenv("NL_SQL_QUERY_TIMEOUT_SECONDS", "10")),
        trace_backend=os.getenv("NL_SQL_TRACE_BACKEND", "phoenix"),
        trace_mode=os.getenv("NL_SQL_TRACE_MODE", "redacted"),
        phoenix_collector_endpoint=os.getenv(
            "PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces"
        ),
        judge_model=os.getenv("NL_SQL_JUDGE_MODEL", "gpt-4.1-mini"),
        agent_model=os.getenv("NL_SQL_AGENT_MODEL", "gpt-4.1-mini"),
    )

