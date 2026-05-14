"""DB engine + Session factory。沿用 v3 的最小封裝。

統一從這支拿 `Session`，避免散落各處重複建 engine。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
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
        _engine = create_engine(url, future=True, connect_args=connect_args)
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
