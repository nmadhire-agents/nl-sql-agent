from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nl_sql_agent.agent import ask_agent, stream_agent_with_session
from nl_sql_agent.config import load_settings
from nl_sql_agent.tracing import configure_tracing


class ChatRequest(BaseModel):
    question: str
    db_path: str


class ChatResponse(BaseModel):
    answer: str
    sql: str | None
    reasoning: str | None
    trace_id: str | None
    validation_error: str | None


app = FastAPI(title="nl-sql-agent-ui-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)
    result = await ask_agent(request.question, Path(request.db_path), settings)
    return ChatResponse(
        answer=result.answer,
        sql=result.generated_sql,
        reasoning=result.reasoning,
        trace_id=result.trace_id,
        validation_error=result.validation_error,
    )


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)

    async def events():
        try:
            async for payload in stream_agent_with_session(request.question, Path(request.db_path), settings):
                yield _sse(payload)
        except Exception as exc:
            fallback_events = list(_demo_fallback_events(request.question, Path(request.db_path), str(exc)))
            if fallback_events:
                for payload in fallback_events:
                    yield _sse(payload)
                return
            yield _sse({"type": "error", "text": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _demo_fallback_events(question: str, db_path: Path, error: str) -> Iterator[dict[str, Any]]:
    """Return a local demo answer for the bundled example when the LLM is unavailable."""
    normalized_question = " ".join(question.lower().split())
    if "how many singers" not in normalized_question:
        return
    if db_path.name != "concert_singer.sqlite":
        return
    if not db_path.exists():
        return

    sql = "SELECT COUNT(*) AS singer_count FROM singer"
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        count = connection.execute(sql).fetchone()[0]

    answer = f"There are {count} singers in the database."
    yield {
        "type": "status",
        "title": "Using local demo fallback",
        "text": "The LLM call failed, so the bundled example is being answered with a deterministic local SQLite query.",
    }
    yield {
        "type": "reasoning",
        "text": f"Original LLM error: {error}",
    }
    yield {
        "type": "tool_call",
        "name": "execute_query",
        "title": "Executing read-only query",
        "text": "Running the known demo SQL against the bundled Spider SQLite database.",
    }
    yield {"type": "tool_output", "title": "Tool returned", "text": f"Query returned 1 row with singer_count = {count}."}
    yield {"type": "answer_start", "confidence": "high"}
    for word in answer.split(" "):
        yield {"type": "answer_delta", "text": f"{word} "}
    yield {"type": "sql", "sql": sql}
    yield {
        "type": "done",
        "answer": answer,
        "sql": sql,
        "reasoning": "Deterministic fallback for bundled UI smoke-test example.",
        "trace_id": None,
        "validation_error": None,
    }
