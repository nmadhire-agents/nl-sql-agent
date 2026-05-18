from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class SpiderExample:
    example_id: str
    question: str
    db_id: str
    gold_sql: str
    db_path: Path
    schema: dict


class SpiderDataset:
    def __init__(self, root: Path) -> None:
        self.root = resolve_spider_root(root)
        self.tables = _load_json(self.root / "tables.json")
        self.tables_by_db = {table["db_id"]: table for table in self.tables}

    def examples(self, split: str = "dev", limit: int | None = None) -> list[SpiderExample]:
        if split != "dev":
            raise ValueError("This repo persists the Spider dev subset only; use split='dev'.")
        rows = _load_json(self.root / "dev.json")
        examples = []
        for index, row in enumerate(rows[:limit]):
            db_id = row["db_id"]
            examples.append(
                SpiderExample(
                    example_id=f"{split}-{index}",
                    question=row["question"],
                    db_id=db_id,
                    gold_sql=row["query"],
                    db_path=self.database_path(db_id),
                    schema=self.tables_by_db[db_id],
                )
            )
        return examples

    def database_path(self, db_id: str) -> Path:
        db_path = self.root / "database" / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            raise FileNotFoundError(f"Spider SQLite database not found: {db_path}")
        return db_path


def resolve_spider_root(path: Path) -> Path:
    path = Path(path)
    if _has_spider_files(path):
        return path
    for child in path.rglob("tables.json"):
        candidate = child.parent
        if _has_spider_files(candidate):
            return candidate
    raise FileNotFoundError(
        f"Could not find Spider files under {path}. Expected dev.json, tables.json, and database/."
    )


def verify_spider_dir(path: Path) -> Path:
    root = resolve_spider_root(path)
    missing = [
        name
        for name in ("dev.json", "tables.json", "database")
        if not (root / name).exists()
    ]
    if missing:
        raise FileNotFoundError(f"Spider dataset is missing: {', '.join(missing)}")
    sqlite_files = list((root / "database").glob("*/*.sqlite"))
    if not sqlite_files:
        raise FileNotFoundError("Spider dataset has no database/*/*.sqlite files.")
    return root


def _has_spider_files(path: Path) -> bool:
    return (path / "tables.json").exists() and (path / "database").exists()


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
