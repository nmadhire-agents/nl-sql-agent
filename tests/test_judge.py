import json

from nl_sql_agent.judge import JudgeInput, JudgeResponse, _coerce_judge_json, build_judge_prompt


def test_judge_prompt_contains_required_fields() -> None:
    payload = JudgeInput(
        question="What is total revenue?",
        schema="orders(id, amount)",
        gold_sql="select sum(amount) from orders",
        generated_sql="select total(amount) from orders",
        gold_result_summary="[{'sum': 3}]",
        generated_result_summary="error",
    )
    messages = build_judge_prompt(payload)
    body = json.loads(messages[1]["content"])
    assert body["question"] == payload.question
    assert body["gold_sql"] == payload.gold_sql
    assert body["generated_sql"] == payload.generated_sql


def test_judge_response_schema() -> None:
    response = JudgeResponse.model_validate(
        {"equivalent": False, "score": 1, "reason": "wrong aggregate", "issues": ["bad function"], "preferred_sql": "gold"}
    )
    assert response.preferred_sql == "gold"


def test_coerces_preferred_sql_text_to_enum() -> None:
    payload = JudgeInput(
        question="How many?",
        schema="singer(id)",
        gold_sql="select count(*) from singer",
        generated_sql="select count(*) as number_of_singers from singer",
        gold_result_summary="[[6]]",
        generated_result_summary="[[6]]",
    )
    coerced = _coerce_judge_json(
        json.dumps({"equivalent": True, "score": 5, "reason": "same", "issues": [], "preferred_sql": payload.generated_sql}),
        payload,
    )
    assert coerced["preferred_sql"] == "generated"
