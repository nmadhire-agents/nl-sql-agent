from pathlib import Path
import json
import sqlite3

from nl_sql_agent.downloader import download_spider, google_drive_file_id


def write_tiny_spider(root: Path) -> None:
    db_dir = root / "database" / "tiny_sales"
    db_dir.mkdir(parents=True)
    conn = sqlite3.connect(db_dir / "tiny_sales.sqlite")
    conn.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, amount REAL)")
    conn.commit()
    conn.close()
    (root / "dev.json").write_text("[]", encoding="utf-8")
    (root / "train_spider.json").write_text("[]", encoding="utf-8")
    (root / "tables.json").write_text(json.dumps([]), encoding="utf-8")


def test_download_spider_reuses_existing_verified_data(tmp_path: Path, monkeypatch) -> None:
    write_tiny_spider(tmp_path)

    def fail_if_network_called() -> str:
        raise AssertionError("download path should not fetch when Spider data exists")

    monkeypatch.setattr("nl_sql_agent.downloader.find_spider_download_url", fail_if_network_called)

    assert download_spider(tmp_path) == tmp_path


def test_google_drive_file_id_from_share_url() -> None:
    assert (
        google_drive_file_id("https://drive.google.com/file/d/1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J/view?usp=sharing")
        == "1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J"
    )
