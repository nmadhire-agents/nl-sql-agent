from pathlib import Path

from nl_sql_agent.downloader import prune_spider_dir


def test_prune_spider_dir_keeps_only_harness_files(tmp_path: Path) -> None:
    root = tmp_path / "spider_data"
    db_dir = root / "database" / "tiny"
    test_db_dir = root / "test_database" / "tiny"
    db_dir.mkdir(parents=True)
    test_db_dir.mkdir(parents=True)
    (root / "README.txt").write_text("source", encoding="utf-8")
    (root / "dev.json").write_text("[]", encoding="utf-8")
    (root / "tables.json").write_text("[]", encoding="utf-8")
    (root / "train_spider.json").write_text("[]", encoding="utf-8")
    (root / "test.json").write_text("[]", encoding="utf-8")
    (db_dir / "tiny.sqlite").write_bytes(b"sqlite")
    (db_dir / "schema.sql").write_text("create table tiny(id int)", encoding="utf-8")
    (db_dir / "annotation.json").write_text("{}", encoding="utf-8")
    (test_db_dir / "tiny.sqlite").write_bytes(b"sqlite")

    prune_spider_dir(root)

    assert (root / "README.txt").exists()
    assert (root / "dev.json").exists()
    assert (root / "tables.json").exists()
    assert (db_dir / "tiny.sqlite").exists()
    assert not (root / "train_spider.json").exists()
    assert not (root / "test.json").exists()
    assert not (root / "test_database").exists()
    assert not (db_dir / "schema.sql").exists()
    assert not (db_dir / "annotation.json").exists()
