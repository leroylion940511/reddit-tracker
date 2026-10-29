"""共用 fixtures — in-memory SQLite session。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from reddit_tracker.models import Base


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


@pytest.fixture(autouse=True)
def _isolated_llm_quota(tmp_path, monkeypatch):
    """額度 state 檔一律放 tmp_path，絕不寫到 production 也會用的 /tmp 計數檔。"""
    from reddit_tracker.config import get_settings

    monkeypatch.setenv("LLM_QUOTA_STATE_PATH", str(tmp_path / "llm-quota.json"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
