from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nl_sql_agent.config import Settings
from nl_sql_agent.sqlite_tools import SQLiteToolkit
from nl_sql_agent.tracing import safe_attr, set_span_attribute, span, trace_payload


INSTRUCTIONS = """You are a careful SQLite data analyst building SQL for a benchmark harness.

Goal:
- Convert the user's natural-language question into correct SQLite SQL.
- Use tools to bridge from user intent to physical schema.
- Return a concise, structured final answer.

Required workflow:
1. Use search_tables first to identify candidate tables and columns.
2. Use get_schema_info for the relevant tables before writing SQL.
3. Generate SQLite SQL only. Prefer explicit joins, clear aliases, and aggregate names.
4. Use validate_sql before execution.
5. Use execute_query only after validation succeeds.
6. If validation or execution fails, inspect the error, fetch schema again if useful, and retry once.
7. Base the final answer only on executed query results. If no SQL was executed, say why.

Safety rules:
- Never use DDL, DML, PRAGMA, ATTACH, DETACH, VACUUM, or multiple statements.
- Never invent tables or columns. If schema is ambiguous, use the available schema and state uncertainty.
- Do not expose hidden tool internals; summarize the result plainly.

Structured final output:
- answer: natural-language answer or explanation.
- sql: the final validated/executed SQL, or null if no SQL could be produced.
- tables_used: table names used by the query.
- row_count: number of rows returned by execute_query, if known.
- truncated: whether execute_query reported truncated rows.
- validation_error: final validation/execution error, if unresolved.
- confidence: high when SQL executed and directly answers the question; medium for partial/ambiguous answers; low when no SQL executed."""


class SQLAgentOutput(BaseModel):
    answer: str = Field(description="Concise natural-language answer for the user.")
    sql: str | None = Field(default=None, description="Final validated or executed SQLite SQL.")
    tables_used: list[str] = Field(default_factory=list, description="SQLite tables referenced by the final SQL.")
    row_count: int | None = Field(default=None, description="Number of rows returned by the final query, if known.")
    truncated: bool = Field(default=False, description="Whether query rows were truncated by the execution tool.")
    validation_error: str | None = Field(default=None, description="Final validation or execution error, if unresolved.")
    confidence: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Confidence that the final SQL and answer satisfy the question.",
    )


@dataclass
class AgentAnswer:
    answer: str
    generated_sql: str | None
    validation_error: str | None
    structured_output: SQLAgentOutput | None = None
    trace_id: str | None = None
    reasoning: str | None = None
    raw: Any | None = None


AgentStreamPayload = dict[str, Any]


async def ask_agent(question: str, db_path: Path, settings: Settings) -> AgentAnswer:
    return await ask_agent_with_session(question, db_path, settings, session=None)


async def ask_agent_with_session(
    question: str,
    db_path: Path,
    settings: Settings,
    session: Any | None = None,
) -> AgentAnswer:
    try:
        from agents import RunConfig, Runner
    except ImportError as exc:
        raise RuntimeError("openai-agents is required. Run `uv sync` first.") from exc

    agent, toolkit = _build_agent(db_path, settings)
    with span(
        "agent.run",
        {
            "question": safe_attr(question, settings.trace_mode),
            "db_path": str(db_path),
            "system_prompt": safe_attr(INSTRUCTIONS, settings.trace_mode),
            "model": settings.agent_model,
        },
    ) as current:
        trace_id: str | None = None
        result = await Runner.run(
            agent,
            input=question,
            session=session,
            run_config=RunConfig(workflow_name="nl-sql-agent", trace_include_sensitive_data=False),
        )
        trace_id = _extract_trace_id(result)
        return _answer_from_result(result, toolkit, settings, current, trace_id)


async def stream_agent_with_session(
    question: str,
    db_path: Path,
    settings: Settings,
    session: Any | None = None,
) -> AsyncIterator[AgentStreamPayload]:
    """Stream UI-friendly status/tool/final-answer events for one agent run."""
    try:
        from agents import RunConfig, Runner
    except ImportError as exc:
        raise RuntimeError("openai-agents is required. Run `uv sync` first.") from exc

    agent, toolkit = _build_agent(db_path, settings)
    with span(
        "agent.run",
        {
            "question": safe_attr(question, settings.trace_mode),
            "db_path": str(db_path),
            "system_prompt": safe_attr(INSTRUCTIONS, settings.trace_mode),
            "model": settings.agent_model,
            "streaming": True,
        },
    ) as current:
        yield {
            "type": "status",
            "title": "Starting analyst run",
            "text": "Preparing schema discovery and SQLite validation tools.",
        }
        result = Runner.run_streamed(
            agent,
            input=question,
            session=session,
            run_config=RunConfig(workflow_name="nl-sql-agent-ui", trace_include_sensitive_data=False),
        )
        async for event in result.stream_events():
            for payload in _stream_payloads(event, settings.trace_mode):
                yield payload

        trace_id = _extract_trace_id(result)
        answer = _answer_from_result(result, toolkit, settings, current, trace_id)
        yield {
            "type": "answer_start",
            "trace_id": answer.trace_id,
            "confidence": answer.structured_output.confidence if answer.structured_output else "medium",
        }
        for chunk in _text_chunks(answer.answer):
            yield {"type": "answer_delta", "text": chunk}
            await asyncio.sleep(0)
        if answer.generated_sql:
            yield {"type": "sql", "sql": answer.generated_sql}
        if answer.validation_error:
            yield {"type": "validation_error", "text": answer.validation_error}
        if answer.structured_output:
            yield {"type": "structured_output", "output": answer.structured_output.model_dump()}
        yield {
            "type": "done",
            "answer": answer.answer,
            "sql": answer.generated_sql,
            "reasoning": answer.reasoning,
            "trace_id": answer.trace_id,
            "validation_error": answer.validation_error,
        }


def _build_agent(db_path: Path, settings: Settings) -> tuple[Any, SQLiteToolkit]:
    try:
        from agents import Agent, function_tool, set_tracing_disabled
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
        output_type=SQLAgentOutput,
    )
    return agent, toolkit


def _answer_from_result(
    result: Any,
    toolkit: SQLiteToolkit,
    settings: Settings,
    current_span: Any,
    trace_id: str | None,
) -> AgentAnswer:
    structured_output = _coerce_structured_output(result.final_output)
    final_answer = structured_output.answer if structured_output else str(result.final_output)
    generated_sql = toolkit.last_executed_sql or toolkit.last_validated_sql
    if generated_sql is None and structured_output:
        generated_sql = structured_output.sql
    set_span_attribute(current_span, "final_answer", safe_attr(final_answer, settings.trace_mode))
    if generated_sql:
        set_span_attribute(current_span, "generated_sql", safe_attr(generated_sql, settings.trace_mode))
    reasoning = _extract_reasoning(result)
    if reasoning:
        set_span_attribute(current_span, "reasoning", safe_attr(reasoning, settings.trace_mode))
    tool_events = _extract_tool_events(result)
    if tool_events:
        set_span_attribute(current_span, "tool_events", trace_payload(tool_events, settings.trace_mode))
    if trace_id:
        set_span_attribute(current_span, "trace_id", trace_id)
    return AgentAnswer(
        answer=final_answer,
        generated_sql=generated_sql,
        validation_error=toolkit.last_error or (structured_output.validation_error if structured_output else None),
        structured_output=structured_output,
        trace_id=trace_id,
        reasoning=reasoning,
        raw=result,
    )


def _coerce_structured_output(value: Any) -> SQLAgentOutput | None:
    if isinstance(value, SQLAgentOutput):
        return value
    if isinstance(value, dict):
        return SQLAgentOutput.model_validate(value)
    return None


def _extract_trace_id(result: Any) -> str | None:
    for attr in ("trace_id", "id", "run_id"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_reasoning(result: Any) -> str | None:
    for attr in ("reasoning", "reasoning_summary", "summary"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_tool_events(result: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    raw_items = getattr(result, "new_items", None) or getattr(result, "items", None)
    if not raw_items:
        return events
    for item in raw_items:
        item_type = getattr(item, "type", None) or item.__class__.__name__
        payload = _item_payload(item)
        events.append({"type": str(item_type), "payload": payload})
    return events


def _item_payload(item: Any) -> str:
    for attr in ("model_dump_json", "to_json"):
        method = getattr(item, attr, None)
        if callable(method):
            try:
                value = method()
                if isinstance(value, str):
                    return value
            except Exception:
                continue
    if hasattr(item, "model_dump"):
        try:
            return json.dumps(item.model_dump(), default=str, sort_keys=True)
        except Exception:
            pass
    return str(item)


def _stream_payloads(event: Any, trace_mode: str) -> list[AgentStreamPayload]:
    event_type = getattr(event, "type", "")
    if event_type == "agent_updated_stream_event":
        agent_name = getattr(getattr(event, "new_agent", None), "name", "agent")
        return [{"type": "status", "title": "Agent selected", "text": f"{agent_name} is handling the request."}]

    if event_type == "raw_response_event":
        return _raw_response_payloads(getattr(event, "data", None))

    if event_type != "run_item_stream_event":
        return []

    name = getattr(event, "name", "")
    item = getattr(event, "item", None)
    if name == "tool_called":
        tool_name = getattr(item, "tool_name", None) or _raw_field(getattr(item, "raw_item", None), "name") or "tool"
        return [
            {
                "type": "tool_call",
                "name": tool_name,
                "title": _tool_title(tool_name),
                "text": _tool_call_text(tool_name),
            }
        ]
    if name == "tool_output":
        output = getattr(item, "output", None)
        return [
            {
                "type": "tool_output",
                "title": "Tool returned",
                "text": _summarize_tool_output(output, trace_mode),
            }
        ]
    if name == "reasoning_item_created":
        return [{"type": "reasoning", "text": "The model recorded a reasoning summary for this step."}]
    if name == "message_output_created":
        return [{"type": "status", "title": "Composing answer", "text": "Formatting the answer, SQL, and metadata."}]
    return []


def _raw_response_payloads(data: Any) -> list[AgentStreamPayload]:
    raw_type = getattr(data, "type", "")
    delta = getattr(data, "delta", None)
    if isinstance(delta, str) and "reasoning" in raw_type:
        return [{"type": "reasoning_delta", "text": delta}]
    return []


def _raw_field(raw_item: Any, field_name: str) -> Any:
    if isinstance(raw_item, dict):
        return raw_item.get(field_name)
    return getattr(raw_item, field_name, None)


def _tool_title(tool_name: str) -> str:
    titles = {
        "search_tables": "Searching schema",
        "get_schema_info": "Reading table definitions",
        "validate_sql": "Validating SQL",
        "execute_query": "Executing read-only query",
    }
    return titles.get(tool_name, f"Calling {tool_name}")


def _tool_call_text(tool_name: str) -> str:
    descriptions = {
        "search_tables": "Looking for tables and columns that match the question.",
        "get_schema_info": "Loading DDL, columns, keys, indexes, and relationships.",
        "validate_sql": "Checking that the generated statement is safe SQLite SQL.",
        "execute_query": "Running the validated query with row caps and read-only protections.",
    }
    return descriptions.get(tool_name, "Running an agent tool.")


def _summarize_tool_output(output: Any, trace_mode: str) -> str:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return "Tool output captured."
    if not isinstance(output, dict):
        return "Tool output captured."
    if "candidates" in output:
        candidates = output.get("candidates") or []
        names = [str(candidate.get("table")) for candidate in candidates if isinstance(candidate, dict) and candidate.get("table")]
        if names:
            return f"Found candidate tables: {', '.join(names[:5])}."
        return "No strong table candidates found."
    if "tables" in output:
        tables = output.get("tables") or {}
        if isinstance(tables, dict) and tables:
            return f"Loaded schema for: {', '.join(list(tables)[:5])}."
        return "Schema lookup completed."
    if "is_valid" in output:
        if output.get("is_valid"):
            sql = output.get("normalized_sql")
            if trace_mode == "full" and sql:
                return f"SQL validated: {sql}"
            return "SQL passed parser, safety, and SQLite query-plan checks."
        return f"SQL validation failed: {output.get('error') or 'unknown error'}"
    if "row_count" in output:
        row_count = output.get("row_count")
        truncated = " Results were truncated." if output.get("truncated") else ""
        return f"Query returned {row_count} row(s).{truncated}"
    return "Tool output captured."


def _text_chunks(text: str, chunk_size: int = 18) -> list[str]:
    words = text.split(" ")
    if len(words) <= 1:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_len + extra > chunk_size:
            chunks.append(" ".join(current) + " ")
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        chunks.append(" ".join(current))
    return chunks
