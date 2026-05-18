from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError


PreferredSQL = Literal["gold", "generated", "tie"]


class JudgeResponse(BaseModel):
    equivalent: bool
    score: int = Field(ge=0, le=5)
    reason: str
    issues: list[str] = Field(default_factory=list)
    preferred_sql: PreferredSQL


@dataclass(frozen=True)
class JudgeInput:
    question: str
    schema: str
    gold_sql: str
    generated_sql: str
    gold_result_summary: str
    generated_result_summary: str


def build_judge_prompt(payload: JudgeInput) -> list[dict[str, str]]:
    system = (
        "You are an expert SQL evaluator. Compare generated SQL against gold SQL for the "
        "same SQLite database and natural-language question. Judge semantic equivalence, "
        "not formatting. Return strict JSON with equivalent, score, reason, issues, and preferred_sql. "
        "preferred_sql must be exactly one of: gold, generated, tie."
    )
    user = {
        "question": payload.question,
        "schema": payload.schema,
        "gold_sql": payload.gold_sql,
        "generated_sql": payload.generated_sql,
        "gold_result_summary": payload.gold_result_summary,
        "generated_result_summary": payload.generated_result_summary,
        "scoring": "0 means wrong, 5 means fully equivalent.",
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, indent=2, sort_keys=True)},
    ]


def judge_sql(payload: JudgeInput, model: str) -> JudgeResponse:
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=build_judge_prompt(payload),
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    try:
        return JudgeResponse.model_validate_json(content)
    except ValidationError:
        return JudgeResponse.model_validate(_coerce_judge_json(content, payload))


def _coerce_judge_json(content: str, payload: JudgeInput) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {
            "equivalent": False,
            "score": 0,
            "reason": f"Judge returned non-JSON content: {content[:200]}",
            "issues": ["invalid_json"],
            "preferred_sql": "gold",
        }
    preferred = str(data.get("preferred_sql", "tie")).strip()
    if preferred == payload.gold_sql:
        data["preferred_sql"] = "gold"
    elif preferred == payload.generated_sql:
        data["preferred_sql"] = "generated"
    elif "gold" in preferred.lower():
        data["preferred_sql"] = "gold"
    elif "generated" in preferred.lower():
        data["preferred_sql"] = "generated"
    else:
        data["preferred_sql"] = "tie"
    data.setdefault("equivalent", False)
    data.setdefault("score", 0)
    data.setdefault("reason", "Judge response required coercion.")
    data.setdefault("issues", ["coerced_response"])
    return data
