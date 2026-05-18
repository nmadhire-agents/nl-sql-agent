from pathlib import Path
import sqlite3

from nl_sql_agent.sqlite_tools import SQLiteToolkit


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL,
          FOREIGN KEY(customer_id) REFERENCES customers(id));
        INSERT INTO customers VALUES (1, 'Ada'), (2, 'Grace');
        INSERT INTO orders VALUES (1, 1, 10.5), (2, 1, 4.5), (3, 2, 7.0);
        """
    )
    conn.close()


def test_schema_discovery_and_execution(tmp_path: Path) -> None:
    db_path = tmp_path / "sales.sqlite"
    make_db(db_path)
    toolkit = SQLiteToolkit(db_path, max_rows=2)

    found = toolkit.search_tables("customer amount")
    assert found["ok"]
    assert {table["table"] for table in found["tables"]} == {"customers", "orders"}

    schema = toolkit.get_schema_info(["orders"])
    assert schema["schemas"][0]["columns"][2]["name"] == "amount"

    result = toolkit.execute_query("select * from orders order by id")
    assert result.ok
    assert result.row_count == 2
    assert result.truncated


def test_search_handles_simple_pluralization(tmp_path: Path) -> None:
    db_path = tmp_path / "sales.sqlite"
    make_db(db_path)
    toolkit = SQLiteToolkit(db_path)

    found = toolkit.search_tables("How many customers?")

    assert any(table["table"] == "customers" for table in found["tables"])
