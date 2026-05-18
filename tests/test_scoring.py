from pathlib import Path
import sqlite3

from nl_sql_agent.scoring import canonicalize_rows, score_sql
from nl_sql_agent.sqlite_tools import SQLiteToolkit


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE orders(id INTEGER PRIMARY KEY, amount REAL);
        INSERT INTO orders VALUES (1, 1.0), (2, 2.0);
        """
    )
    conn.close()


def test_result_match_when_sql_text_differs(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.sqlite"
    make_db(db_path)
    toolkit = SQLiteToolkit(db_path)
    score = score_sql(
        toolkit,
        "select sum(amount) as total from orders",
        "select SUM(orders.amount) total from orders",
    )
    assert score.validation_success
    assert score.execution_success
    assert score.result_match


def test_result_match_ignores_alias_names(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.sqlite"
    make_db(db_path)
    toolkit = SQLiteToolkit(db_path)
    score = score_sql(
        toolkit,
        "select count(*) as number_of_orders from orders",
        "select count(*) from orders",
    )
    assert score.result_match


def test_canonicalize_sorts_unordered_rows() -> None:
    rows = [{"name": "b", "value": 2.0}, {"value": 1.0, "name": "a"}]
    assert canonicalize_rows(rows) == [{"name": "a", "value": 1.0}, {"name": "b", "value": 2.0}]
