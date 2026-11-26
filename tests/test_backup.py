import sqlite3
from datetime import date

import pytest

from reddit_tracker.backup import BackupError, backup_database, sqlite_path


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1), (2)")
    conn.commit()
    return conn  # 保持開著：WAL 還沒 checkpoint，備份也要讀到


def test_backup_copies_wal_content_and_prunes(tmp_path):
    src = tmp_path / "live.db"
    conn = _db(src)
    out = tmp_path / "backups"
    for day in (1, 2, 3, 4):
        backup_database(src, out, keep=3, day=date(2026, 11, day))
    conn.close()
    names = sorted(p.name for p in out.iterdir())
    assert names == ["reddit_tracker-2026-11-02.db", "reddit_tracker-2026-11-03.db", "reddit_tracker-2026-11-04.db"]
    copy = sqlite3.connect(out / names[-1])
    assert copy.execute("SELECT count(*) FROM t").fetchone()[0] == 2


def test_backup_rejects_bad_inputs(tmp_path):
    with pytest.raises(BackupError):
        backup_database(tmp_path / "missing.db", tmp_path, keep=3, day=date(2026, 11, 1))
    with pytest.raises(BackupError):
        backup_database(tmp_path / "missing.db", tmp_path, keep=0, day=date(2026, 11, 1))


def test_sqlite_path():
    assert str(sqlite_path("sqlite:///./reddit_tracker.db")) == "reddit_tracker.db"
    assert str(sqlite_path("sqlite:////Users/x/rt.db")) == "/Users/x/rt.db"
    with pytest.raises(BackupError):
        sqlite_path("postgresql://h/db")
    with pytest.raises(BackupError):
        sqlite_path("sqlite:///:memory:")
