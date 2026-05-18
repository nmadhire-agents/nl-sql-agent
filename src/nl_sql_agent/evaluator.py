from __future__ import annotations

from dataclasses import asdict, dataclass
import asyncio
import json
from pathlib import Path
import time

from nl_sql_agent.agent import ask_agent
from nl_sql_agent.config import Settings
from nl_sql_agent.judge import JudgeInput, JudgeResponse, judge_sql
from nl_sql_agent.scoring import SQLScore, score_sql
from nl_sql_agent.spider import SpiderDataset, SpiderExample
from nl_sql_agent.sqlite_tools import SQLiteToolkit
from nl_sql_agent.tracing import span


@dataclass
class EvalRecord:
    example_id: str
    db_id: str
    question: str
    generated_sql: str | None
    gold_sql: str
    deterministic_score: SQLScore
    judge: JudgeResponse | None
    latency_seconds: float
    final_answer: str
    trace_id: str | None = None


async def run_spider_eval(
    data_dir: Path,
    split: str,
    limit: int,
    settings: Settings,
    output: Path,
    use_judge: bool = True,
) -> list[EvalRecord]:
    dataset = SpiderDataset(data_dir)
    examples = dataset.examples(split=split, limit=limit)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with output.open("w", encoding="utf-8") as handle:
        for example in examples:
            record = await evaluate_example(example, settings, use_judge=use_judge)
            records.append(record)
            handle.write(json.dumps(_record_to_json(record), default=str) + "\n")
    return records


async def evaluate_example(example: SpiderExample, settings: Settings, use_judge: bool) -> EvalRecord:
    start = time.perf_counter()
    with span("eval.example", {"example_id": example.example_id, "db_id": example.db_id}):
        answer = await ask_agent(example.question, example.db_path, settings)
        generated_sql = answer.generated_sql or ""
        toolkit = SQLiteToolkit(example.db_path, settings.max_rows, settings.query_timeout_seconds)
        score = score_sql(toolkit, generated_sql, example.gold_sql)
        judge = None
        if use_judge and generated_sql:
            judge = await asyncio.to_thread(_judge_example, example, generated_sql, toolkit, settings)
    return EvalRecord(
        example_id=example.example_id,
        db_id=example.db_id,
        question=example.question,
        generated_sql=generated_sql or None,
        gold_sql=example.gold_sql,
        deterministic_score=score,
        judge=judge,
        latency_seconds=time.perf_counter() - start,
        final_answer=answer.answer,
        trace_id=answer.trace_id,
    )


def _judge_example(
    example: SpiderExample, generated_sql: str, toolkit: SQLiteToolkit, settings: Settings
) -> JudgeResponse:
    gold_result = toolkit.execute_query(example.gold_sql, max_rows=20)
    generated_result = toolkit.execute_query(generated_sql, max_rows=20)
    schema_text = json.dumps(example.schema, sort_keys=True)[:8000]
    payload = JudgeInput(
        question=example.question,
        schema=schema_text,
        gold_sql=example.gold_sql,
        generated_sql=generated_sql,
        gold_result_summary=json.dumps(gold_result.__dict__, default=str)[:4000],
        generated_result_summary=json.dumps(generated_result.__dict__, default=str)[:4000],
    )
    with span("eval.llm_judge", {"db_id": example.db_id}):
        return judge_sql(payload, settings.judge_model)


def _record_to_json(record: EvalRecord) -> dict:
    payload = asdict(record)
    if record.judge is not None:
        payload["judge"] = record.judge.model_dump()
    return payload

