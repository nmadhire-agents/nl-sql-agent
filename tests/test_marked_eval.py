from pathlib import Path
import asyncio
import os

import pytest


@pytest.mark.spider_eval
def test_spider_data_scores_gold_sql() -> None:
    if not Path("data/spider").exists():
        pytest.skip("Download Spider with `uv run nl-sql data download-spider --output data/spider`.")
    from nl_sql_agent.spider import SpiderDataset
    from nl_sql_agent.sqlite_tools import SQLiteToolkit
    from nl_sql_agent.scoring import score_sql

    example = SpiderDataset(Path("data/spider")).examples("dev", limit=1)[0]
    score = score_sql(SQLiteToolkit(example.db_path), example.gold_sql, example.gold_sql)
    assert score.result_match


@pytest.mark.llm_eval
def test_llm_eval_runs_agent_and_judge_on_one_spider_example(tmp_path: Path) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for LLM judge evals.")
    if not Path("data/spider").exists():
        pytest.skip("Download Spider with `uv run nl-sql data download-spider --output data/spider`.")
    from nl_sql_agent.config import load_settings
    from nl_sql_agent.evaluator import run_spider_eval

    records = asyncio.run(
        run_spider_eval(
            Path("data/spider"),
            split="dev",
            limit=1,
            settings=load_settings(),
            output=tmp_path / "llm_eval.jsonl",
            use_judge=True,
        )
    )
    assert len(records) == 1
    assert records[0].generated_sql
    assert records[0].judge is not None
