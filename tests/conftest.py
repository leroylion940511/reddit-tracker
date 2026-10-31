"""共用 fixtures — in-memory SQLite session。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from reddit_tracker.models import Base
from tests import llm_guard


def pytest_configure(config):
    """收集測試前就裝好防護：連 session fixture 的 setup 也不能呼叫真 LLM。"""
    llm_guard.install()


@pytest.fixture(autouse=True)
def _no_real_llm():
    """攔截可能被程式內的 `except` 吞掉；測試結束再檢查一次，有嘗試就判失敗。"""
    llm_guard.attempts.clear()
    yield
    if llm_guard.attempts:
        found = list(llm_guard.attempts)
        llm_guard.attempts.clear()
        pytest.fail(f"測試嘗試呼叫真 LLM：{found}")


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


@pytest.fixture(autouse=True)
def _no_codex_version_probe(monkeypatch):
    """`codex --version` 也會被 llm_guard 擋；預設當成讀不到版本。要測實測版本的測試自己再 patch。"""
    from reddit_tracker.llm import codex_version

    monkeypatch.setattr(codex_version, "probe_cli_version", lambda binary, **kw: None)
