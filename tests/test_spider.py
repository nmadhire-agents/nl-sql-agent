from pathlib import Path
import json
import sqlite3

from nl_sql_agent.spider import SpiderDataset, verify_spider_dir


def write_tiny_spider(root: Path) -> None:
    db_dir = root / "database" / "tiny_sales"
    db_dir.mkdir(parents=True)
    conn = sqlite3.connect(db_dir / "tiny_sales.sqlite")
    conn.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, amount REAL)")
    conn.execute("INSERT INTO orders VALUES (1, 3.0)")
    conn.commit()
    conn.close()
    (root / "dev.json").write_text(
        json.dumps([{"db_id": "tiny_sales", "question": "total?", "query": "select sum(amount) from orders"}]),
        encoding="utf-8",
    )
    (root / "train_spider.json").write_text("[]", encoding="utf-8")
    (root / "tables.json").write_text(
        json.dumps([{"db_id": "tiny_sales", "table_names_original": ["orders"], "column_names_original": []}]),
        encoding="utf-8",
    )


def test_spider_loader_tiny_fixture(tmp_path: Path) -> None:
    write_tiny_spider(tmp_path)
    assert verify_spider_dir(tmp_path) == tmp_path
    dataset = SpiderDataset(tmp_path)
    example = dataset.examples("dev", limit=1)[0]
    assert example.db_id == "tiny_sales"
    assert example.db_path.exists()

