from __future__ import annotations

from pathlib import Path
import re
import shutil
import urllib.request
import zipfile

from nl_sql_agent.spider import verify_spider_dir


SPIDER_WEBSITE = "https://yale-lily.github.io/spider"


def download_spider(output: Path, force: bool = False) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if not force:
        try:
            return verify_spider_dir(output)
        except FileNotFoundError:
            pass

    archive_path = output / "spider.zip"
    url = find_spider_download_url()

    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError("gdown is required to download Spider. Run `uv sync` first.") from exc

    result = gdown.download(id=google_drive_file_id(url), output=str(archive_path), quiet=False)
    if result is None:
        raise RuntimeError(f"Spider download failed from {url}")

    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(output)

    root = verify_spider_dir(output)
    prune_spider_dir(root)
    return verify_spider_dir(root)


def find_spider_download_url() -> str:
    with urllib.request.urlopen(SPIDER_WEBSITE, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    match = re.search(r"https://drive\.google\.com/[^\"']+", html)
    if not match:
        raise RuntimeError(f"No Google Drive Spider dataset link found on {SPIDER_WEBSITE}")
    return match.group(0)


def google_drive_file_id(url: str) -> str:
    match = re.search(r"/file/d/([^/]+)/", url)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([^&]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not parse Google Drive file id from {url}")


def prune_spider_dir(root: Path) -> None:
    """Keep only files needed by this SQLite dev-set harness."""
    root = Path(root)
    keep_root_files = {"README.txt", "dev.json", "tables.json"}
    for child in root.iterdir():
        if child.name == "database":
            continue
        if child.is_file() and child.name in keep_root_files:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    database = root / "database"
    for file_path in database.rglob("*"):
        if file_path.is_file() and file_path.suffix != ".sqlite":
            file_path.unlink()

    for directory in sorted(database.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
