from typer.testing import CliRunner

from nl_sql_agent.cli import _display_sql, app


def test_display_sql_formats_query() -> None:
    formatted = _display_sql("select count(*) as total from singer", formatted=True)
    assert "SELECT" in formatted
    assert "\n" in formatted


def test_display_sql_can_return_raw_query() -> None:
    sql = "select count(*) as total from singer"
    assert _display_sql(sql, formatted=False) == sql


def test_sql_command_is_registered() -> None:
    result = CliRunner().invoke(app, ["sql", "--help"])
    assert result.exit_code == 0
    assert "Generate and print only" in result.output
