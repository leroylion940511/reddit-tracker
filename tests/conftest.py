"""共用 fixtures — in-memory SQLite + seeded session。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from reddit_tracker.models import Base
from reddit_tracker.seeds.loader import load_all


@pytest.fixture()
def engine():
    """每個測試一個獨立 in-memory SQLite。"""
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    s = Session()
    try:
        yield s
        s.rollback()
    finally:
        s.close()


@pytest.fixture()
def seeded_session(session) -> Session:
    """已 load 完 subreddit + keyword seeds 的 session。"""
    load_all(session)
    session.commit()
    return session
