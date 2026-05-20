from __future__ import annotations

import json
from pathlib import Path

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
            yield _sse({"type": "error", "text": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"
