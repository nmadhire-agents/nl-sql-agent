from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from nl_sql_agent.agent import ask_agent
from nl_sql_agent.config import load_settings
from nl_sql_agent.downloader import download_spider
from nl_sql_agent.evaluator import run_spider_eval
from nl_sql_agent.tracing import configure_tracing


app = typer.Typer(help="SQLite NL-to-SQL command-line agent.")
data_app = typer.Typer(help="Dataset download and verification commands.")
app.add_typer(data_app, name="data")


@app.command()
def ask(
    question: str,
    db: Path = typer.Option(None, "--db", help="SQLite database path."),
) -> None:
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)
    db_path = db or settings.default_db_path
    if db_path is None:
        raise typer.BadParameter("Provide --db or set NL_SQL_DEFAULT_DB_PATH.")
    result = asyncio.run(ask_agent(question, db_path, settings))
    typer.echo(result.answer)
    if result.generated_sql:
        typer.echo("\nSQL:")
        typer.echo(result.generated_sql)


@app.command("eval")
def eval_cmd(
    dataset: str = typer.Option("spider", "--dataset"),
    data_dir: Path = typer.Option(Path("data/spider"), "--data-dir"),
    split: str = typer.Option("dev", "--split"),
    limit: int = typer.Option(25, "--limit"),
    output: Path = typer.Option(Path("eval_runs/spider_eval.jsonl"), "--output"),
    judge: bool = typer.Option(True, "--judge/--no-judge"),
) -> None:
    if dataset != "spider":
        raise typer.BadParameter("Only --dataset spider is supported.")
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)
    records = asyncio.run(run_spider_eval(data_dir, split, limit, settings, output, use_judge=judge))
    total = len(records)
    result_matches = sum(1 for record in records if record.deterministic_score.result_match)
    judge_matches = sum(1 for record in records if record.judge and record.judge.equivalent)
    typer.echo(f"Examples: {total}")
    typer.echo(f"Execution accuracy: {result_matches}/{total}")
    if judge:
        typer.echo(f"LLM judge equivalent: {judge_matches}/{total}")
    typer.echo(f"Artifacts: {output}")


@data_app.command("download-spider")
def download_spider_cmd(
    output: Path = typer.Option(Path("data/spider"), "--output"),
    force: bool = typer.Option(False, "--force", help="Redownload and re-extract even if Spider data is already present."),
) -> None:
    root = download_spider(output, force=force)
    typer.echo(f"Spider dataset ready at {root}")
    typer.echo("Source: https://yale-lily.github.io/spider")
    typer.echo("License: CC BY-SA 4.0")


@app.command("trace-server")
def trace_server(host: str = "127.0.0.1", port: int = 6006) -> None:
    try:
        import phoenix as px
    except ImportError as exc:
        raise RuntimeError("arize-phoenix is required. Run `uv sync` first.") from exc
    session = px.launch_app(host=host, port=port)
    typer.echo(f"Phoenix running at {session.url}")
    typer.echo("Press Ctrl+C to stop.")
    try:
        import time

        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        typer.echo("Stopping Phoenix.")


def main() -> None:
    app()
