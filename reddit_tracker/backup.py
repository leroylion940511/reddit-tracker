"""每日 SQLite 備份：online backup API（WAL 下安全，不阻擋寫入），保留最近 N 份。

`python -m reddit_tracker.backup [--dir DIR] [--keep N]` 手動跑；排程由 `DB_BACKUP_DIR` 開啟。
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import get_settings

logger = logging.getLogger(__name__)

PREFIX = "reddit_tracker-"
SUFFIX = ".db"


class BackupError(RuntimeError):
    pass


def sqlite_path(database_url: str) -> Path:
    """`sqlite:///./x.db`、`sqlite:////abs/x.db` → 檔案路徑；其他資料庫不支援。"""
    if not database_url.startswith("sqlite:///"):
        raise BackupError(f"只支援 sqlite:/// 檔案資料庫：{database_url.split(':', 1)[0]}")
    path = database_url[len("sqlite:///"):]
    if not path or path == ":memory:":
        raise BackupError("in-memory 資料庫不能備份")
    return Path(path)


def backup_database(source: Path, backup_dir: Path, *, keep: int, day: date) -> Path:
    """把 source 備份成 backup_dir/reddit_tracker-YYYY-MM-DD.db，quick_check 通過才換名，再刪多的舊檔。"""
    if keep < 1:
        raise BackupError("DB_BACKUP_KEEP 至少 1")
    if not source.exists():
        raise BackupError(f"找不到資料庫：{source}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    final = backup_dir / f"{PREFIX}{day.isoformat()}{SUFFIX}"
    tmp = final.with_suffix(".db.partial")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if result != "ok":
        tmp.unlink(missing_ok=True)
        raise BackupError(f"備份 quick_check 失敗：{result}")
    tmp.replace(final)
    for old in sorted(backup_dir.glob(f"{PREFIX}*{SUFFIX}"))[:-keep]:
        old.unlink()
        logger.info("db backup pruned: %s", old.name)
    return final


def run_scheduled_backup() -> Path | None:
    settings = get_settings()
    if not settings.db_backup_dir:
        return None
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    path = backup_database(
        sqlite_path(settings.database_url), Path(settings.db_backup_dir).expanduser(),
        keep=settings.db_backup_keep, day=today,
    )
    logger.info("db backup done: %s (%.0f MB)", path, path.stat().st_size / 1e6)
    return path


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=settings.db_backup_dir, help="備份目錄（預設 DB_BACKUP_DIR）")
    parser.add_argument("--keep", type=int, default=settings.db_backup_keep)
    args = parser.parse_args(argv)
    if not args.dir:
        parser.error("沒有備份目錄：設定 DB_BACKUP_DIR 或帶 --dir")
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    path = backup_database(sqlite_path(settings.database_url), Path(args.dir).expanduser(), keep=args.keep, day=today)
    print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
