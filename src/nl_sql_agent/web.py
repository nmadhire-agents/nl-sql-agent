from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from nl_sql_agent.agent import ask_agent
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
