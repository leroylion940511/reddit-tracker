"""Safety checks for the v5 deployment backup step."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from reddit_tracker.newsroom.deploy import (
    NewsroomDeploymentError,
    backup_sqlite_database,
    sqlite_database_path,
)


def test_backup_sqlite_database_creates_an_integrity_checked_copy(tmp_path):
    source = tmp_path / "newsroom.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE editions (id INTEGER PRIMARY KEY, headline TEXT)")
        connection.execute("INSERT INTO editions (headline) VALUES ('來源透明的短報')")

    backup = backup_sqlite_database(source, now=datetime(2026, 9, 18, 12, 34, 56))

    assert backup == tmp_path / "newsroom.backup-20260918-123456.db"
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT headline FROM editions").fetchone() == ("來源透明的短報",)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_backup_refuses_missing_source_and_existing_target(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(NewsroomDeploymentError, match="找不到"):
        backup_sqlite_database(missing)

    source = tmp_path / "newsroom.db"
    source.touch()
    target = tmp_path / "newsroom.backup-20260918-123456.db"
    target.touch()
    with pytest.raises(NewsroomDeploymentError, match="拒絕覆寫"):
        backup_sqlite_database(source, now=datetime(2026, 9, 18, 12, 34, 56))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:////tmp/newsroom.db", "/tmp/newsroom.db"),
        ("sqlite:///:memory:", None),
        ("postgresql://localhost/newsroom", None),
    ],
)
def test_sqlite_database_path_only_accepts_file_backed_sqlite(url, expected):
    if expected is None:
        with pytest.raises(NewsroomDeploymentError):
            sqlite_database_path(url)
    else:
        assert sqlite_database_path(url) == Path(expected).resolve()
