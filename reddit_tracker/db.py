"""DB engine + Session factory。沿用 v3 的最小封裝。

統一從這支拿 `Session`，避免散落各處重複建 engine。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args: dict = {}
        if url.startswith("sqlite"):
            # SQLite + multi-thread (APScheduler 會在背景 thread 用 session)
            connect_args["check_same_thread"] = False
            # 等鎖 5 秒再 fail。SQLite 預設 busy_timeout=0 撞鎖立即 raise，
            # bot + scheduler 兩 process 並發時必撞（曾 6/9–6/11 連 3 天 9 AM
            # daily_top5_push 死在 database is locked）。
            connect_args["timeout"] = 5.0
        _engine = create_engine(url, future=True, connect_args=connect_args)

        if url.startswith("sqlite"):
            # 每個 connection 起來時 PRAGMA：WAL + NORMAL + busy_timeout
            # - WAL：reader 與 writer 不互相 block；只有 writer 之間 mutex
            # - synchronous=NORMAL：WAL 下安全且比 FULL 略快
            # - busy_timeout=5000ms：與 connect_args["timeout"] 對齊，雙保險
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _conn_record):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """上下文管理：commit on success / rollback on exception。"""
    Session = get_session_factory()
    s = Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
