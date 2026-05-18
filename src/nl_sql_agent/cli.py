from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import typer

from nl_sql_agent.agent import ask_agent_with_session
from nl_sql_agent.config import load_settings
from nl_sql_agent.downloader import download_spider
from nl_sql_agent.evaluator import run_spider_eval
from nl_sql_agent.sql_safety import format_sql
from nl_sql_agent.tracing import configure_tracing


app = typer.Typer(help="SQLite NL-to-SQL command-line agent.")
data_app = typer.Typer(help="Dataset download and verification commands.")
app.add_typer(data_app, name="data")


@app.command()
def ask(
    question: str,
    db: Path = typer.Option(None, "--db", help="SQLite database path."),
    formatted_sql: bool = typer.Option(True, "--format-sql/--raw-sql", help="Pretty-print generated SQL in the response."),
    session_id: str | None = typer.Option(None, "--session-id", help="Persist conversation context across CLI invocations."),
    session_store: Path = typer.Option(Path(".cache/nl_sql_agent_sessions.sqlite"), "--session-store", help="SQLite file for persisted CLI sessions."),
) -> None:
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)
    db_path = db or settings.default_db_path
    if db_path is None:
        raise typer.BadParameter("Provide --db or set NL_SQL_DEFAULT_DB_PATH.")
    session = _build_session(session_id, session_store) if session_id else None
    result = asyncio.run(ask_agent_with_session(question, db_path, settings, session=session))
    typer.echo(result.answer)
    if result.generated_sql:
        typer.echo("\nSQL:")
        typer.echo(_display_sql(result.generated_sql, formatted_sql))


@app.command("sql")
def sql_cmd(
    question: str,
    db: Path = typer.Option(None, "--db", help="SQLite database path."),
    formatted: bool = typer.Option(True, "--format/--raw", help="Pretty-print the generated SQL."),
    session_id: str | None = typer.Option(None, "--session-id", help="Persist conversation context across CLI invocations."),
    session_store: Path = typer.Option(Path(".cache/nl_sql_agent_sessions.sqlite"), "--session-store", help="SQLite file for persisted CLI sessions."),
) -> None:
    """Generate and print only the SQLite SQL for a natural-language question."""
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)
    db_path = db or settings.default_db_path
    if db_path is None:
        raise typer.BadParameter("Provide --db or set NL_SQL_DEFAULT_DB_PATH.")
    session = _build_session(session_id, session_store) if session_id else None
    result = asyncio.run(ask_agent_with_session(question, db_path, settings, session=session))
    if not result.generated_sql:
        raise typer.Exit(code=1)
    typer.echo(_display_sql(result.generated_sql, formatted))


@app.command("chat")
def chat_cmd(
    db: Path = typer.Option(None, "--db", help="SQLite database path."),
    session_id: str | None = typer.Option(None, "--session-id", help="Session identifier. Generated when omitted."),
    session_store: Path | None = typer.Option(None, "--session-store", help="Persist session history to this SQLite file."),
    sql_only: bool = typer.Option(False, "--sql-only", help="Print only generated SQL for each question."),
    formatted: bool = typer.Option(True, "--format/--raw", help="Pretty-print generated SQL."),
) -> None:
    """Start an interactive NL-to-SQL session for multiple questions."""
    settings = load_settings()
    configure_tracing(settings.phoenix_collector_endpoint, settings.trace_mode)
    db_path = db or settings.default_db_path
    if db_path is None:
        raise typer.BadParameter("Provide --db or set NL_SQL_DEFAULT_DB_PATH.")

    active_session_id = session_id or f"cli-{uuid4().hex[:12]}"
    session = _build_session(active_session_id, session_store)
    typer.echo(f"NL-to-SQL session: {active_session_id}")
    typer.echo("Type a question, or use :exit, :quit, or Ctrl-D to stop.")

    while True:
        try:
            question = typer.prompt("nl-sql")
        except (EOFError, KeyboardInterrupt):
            typer.echo()
            break
        if question.strip() in {":exit", ":quit", "exit", "quit"}:
            break
        if not question.strip():
            continue

        result = asyncio.run(ask_agent_with_session(question, db_path, settings, session=session))
        if sql_only:
            if result.generated_sql:
                typer.echo(_display_sql(result.generated_sql, formatted))
            else:
                typer.echo("No SQL generated.", err=True)
            continue

        typer.echo(result.answer)
        if result.generated_sql:
            typer.echo("\nSQL:")
            typer.echo(_display_sql(result.generated_sql, formatted))


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


def _display_sql(sql: str, formatted: bool) -> str:
    if not formatted:
        return sql
    try:
        return format_sql(sql)
    except Exception:
        return sql


def _build_session(session_id: str, session_store: Path | None):
    try:
        from agents.memory.sqlite_session import SQLiteSession
    except ImportError as exc:
        raise RuntimeError("openai-agents SQLiteSession is required. Run `uv sync` first.") from exc

    if session_store is None:
        return SQLiteSession(session_id=session_id, db_path=":memory:")
    session_store.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteSession(session_id=session_id, db_path=session_store)
