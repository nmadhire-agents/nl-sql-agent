from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nl_sql_agent.config import Settings
from nl_sql_agent.sqlite_tools import SQLiteToolkit
from nl_sql_agent.tracing import safe_attr, set_span_attribute, span, trace_payload


INSTRUCTIONS = """You are a careful SQLite data analyst.
You must:
1. Identify likely tables with search_tables.
2. Fetch schema with get_schema_info before writing SQL.
3. Generate SQLite SQL only.
4. Validate SQL with validate_sql before executing it.
5. Execute only validated read-only SQL with execute_query.
6. If validation or execution fails, correct the SQL once using the error and schema.
7. Summarize the final data and include the SQL you used.
Never use DDL, DML, PRAGMA, ATTACH, DETACH, VACUUM, or multiple statements."""


@dataclass
class AgentAnswer:
    answer: str
    generated_sql: str | None
    validation_error: str | None
    trace_id: str | None = None
    raw: Any | None = None


async def ask_agent(question: str, db_path: Path, settings: Settings) -> AgentAnswer:
    try:
        from agents import Agent, RunConfig, Runner, function_tool, set_tracing_disabled
    except ImportError as exc:
        raise RuntimeError("openai-agents is required. Run `uv sync` first.") from exc

    set_tracing_disabled(True)
    toolkit = SQLiteToolkit(db_path, settings.max_rows, settings.query_timeout_seconds)

    @function_tool
    def search_tables(query: str) -> dict[str, Any]:
        """Search SQLite tables and columns relevant to a natural-language query."""
        with span("tool.search_tables", {"input.query": safe_attr(query, settings.trace_mode)}) as current:
            result = toolkit.search_tables(query)
            set_span_attribute(current, "output", trace_payload(result, settings.trace_mode))
            return result

    @function_tool
    def get_schema_info(table_names: list[str]) -> dict[str, Any]:
        """Return SQLite DDL, columns, keys, indexes, and foreign keys for tables."""
        with span("tool.get_schema_info", {"input.tables": ",".join(table_names)}) as current:
            result = toolkit.get_schema_info(table_names)
            set_span_attribute(current, "output", trace_payload(result, settings.trace_mode))
            return result

    @function_tool
    def validate_sql(query: str) -> dict[str, Any]:
        """Validate read-only SQLite SQL without executing it."""
        with span("tool.validate_sql", {"input.sql": safe_attr(query, settings.trace_mode)}) as current:
            result = toolkit.validate_sql(query)
            set_span_attribute(current, "output", trace_payload(result, settings.trace_mode))
            if result.get("normalized_sql"):
                set_span_attribute(current, "generated_sql", safe_attr(result["normalized_sql"], settings.trace_mode))
            return result

    @function_tool
    def execute_query(query: str) -> dict[str, Any]:
        """Execute read-only SQLite SQL and return capped JSON rows."""
        with span("tool.execute_query", {"input.sql": safe_attr(query, settings.trace_mode)}) as current:
            result = toolkit.execute_query(query)
            set_span_attribute(current, "output", trace_payload(result.__dict__, settings.trace_mode))
            set_span_attribute(current, "row_count", result.row_count)
            set_span_attribute(current, "truncated", result.truncated)
            return result.__dict__

    agent = Agent(
        name="DataAnalystAgent",
        instructions=INSTRUCTIONS,
        model=settings.agent_model,
        tools=[search_tables, get_schema_info, validate_sql, execute_query],
    )
    with span(
        "agent.run",
        {
            "question": safe_attr(question, settings.trace_mode),
            "db_path": str(db_path),
            "system_prompt": safe_attr(INSTRUCTIONS, settings.trace_mode),
            "model": settings.agent_model,
        },
    ) as current:
        result = await Runner.run(
            agent,
            input=question,
            run_config=RunConfig(workflow_name="nl-sql-agent", trace_include_sensitive_data=False),
        )
        final_answer = str(result.final_output)
        generated_sql = toolkit.last_executed_sql or toolkit.last_validated_sql
        set_span_attribute(current, "final_answer", safe_attr(final_answer, settings.trace_mode))
        if generated_sql:
            set_span_attribute(current, "generated_sql", safe_attr(generated_sql, settings.trace_mode))
    return AgentAnswer(
        answer=final_answer,
        generated_sql=generated_sql,
        validation_error=toolkit.last_error,
        raw=result,
    )
