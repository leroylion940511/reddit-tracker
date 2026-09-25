"""Safety helpers for a v5 newsroom schema deployment.

The shell deploy command invokes this module before Alembic.  SQLite's online
backup API gives us a consistent, recoverable copy even while the newsroom
service still has the database open.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from sqlalchemy.engine import make_url

from ..config import get_settings


class NewsroomDeploymentError(ValueError):
    """Raised when a database cannot be backed up safely before migration."""


def sqlite_database_path(database_url: str) -> Path:
    """Resolve a file-backed SQLite SQLAlchemy URL without accepting other DBs."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise NewsroomDeploymentError("newsroom deploy 目前只支援檔案型 SQLite database")
    return Path(unquote(url.database)).expanduser().resolve()


def backup_sqlite_database(database_path: Path, *, now: datetime | None = None) -> Path:
    """Create a timestamped, integrity-checked SQLite backup beside its source."""
    source = database_path.expanduser().resolve()
    if not source.is_file():
        raise NewsroomDeploymentError(f"找不到 SQLite database：{source}")
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = source.with_name(f"{source.stem}.backup-{timestamp}{source.suffix}")
    if backup.exists():
        raise NewsroomDeploymentError(f"backup 已存在，拒絕覆寫：{backup}")
    try:
        with sqlite3.connect(str(source)) as source_connection, sqlite3.connect(str(backup)) as backup_connection:
            source_connection.backup(backup_connection)
        with sqlite3.connect(str(backup)) as verification_connection:
            integrity = verification_connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise NewsroomDeploymentError(f"SQLite backup 失敗：{exc}") from exc
    if integrity != ("ok",):
        raise NewsroomDeploymentError(f"backup integrity_check 失敗：{integrity}")
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the configured SQLite DB before newsroom migration")
    parser.parse_args()
    source = sqlite_database_path(get_settings().database_url)
    backup = backup_sqlite_database(source)
    print(f"SQLite backup ready: {backup}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["NewsroomDeploymentError", "backup_sqlite_database", "sqlite_database_path"]
