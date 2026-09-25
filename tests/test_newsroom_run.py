"""Publishing must stop safely if a multi-message Telegram delivery breaks."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reddit_tracker.newsroom.publisher import TELEGRAM_SAFE_LENGTH
from reddit_tracker.newsroom.rendering import EditionView, ItemView, SourceView
from reddit_tracker.newsroom.repository import create_reader_profile, get_or_create_edition
from reddit_tracker.models import AgentRun, NewsroomEdition
from reddit_tracker.newsroom.planning import EditorialPlanningError
from reddit_tracker.newsroom.run import PreparedEdition, prepare_edition, publish_edition


def _view() -> EditionView:
    return EditionView(
        edition_date="2026-09-17",
        reader_summary="多看人際與日常。",
        artifacts=[],
        items=[
            ItemView(
                position=1,
                kind="brief",
                headline_zh="可分段測試稿",
                body_zh="內容" * TELEGRAM_SAFE_LENGTH,
                why_it_matters="驗證中斷後不會自動重送。",
                confidence="low",
                warnings=[],
                sources=[SourceView("Original Reddit title", "askreddit", "https://reddit.example/1")],
            )
        ],
    )


def test_partial_delivery_failure_is_not_reset_for_automatic_retry(session, monkeypatch):
    reader = create_reader_profile(
        session,
        telegram_chat_id=100,
        preference_prompt="多看人際與日常。",
    )
    edition = get_or_create_edition(
        session,
        reader=reader,
        edition_date=date(2026, 9, 17),
        window_start=date(2026, 9, 16),
        window_end=date(2026, 9, 17),
    ).edition
    edition.status = "drafted"
    session.commit()

    @contextmanager
    def session_scope():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    async def partial_failure(**_kwargs):
        raise RuntimeError("second Telegram message timed out")

    import reddit_tracker.newsroom.run as run_module

    monkeypatch.setattr(run_module, "get_settings", lambda: SimpleNamespace(telegram_bot_token="test-token"))
    monkeypatch.setattr(run_module, "session_scope", session_scope)
    monkeypatch.setattr(
        run_module,
        "prepare_edition",
        lambda **_kwargs: PreparedEdition(edition.id, 100, _view(), "template"),
    )
    monkeypatch.setattr(run_module, "send_telegram_messages", partial_failure)

    with pytest.raises(RuntimeError, match="second Telegram message timed out"):
        publish_edition(edition_date=date(2026, 9, 17))

    assert session.get(type(edition), edition.id).status == "delivery_failed"


def test_planning_failure_keeps_edition_and_assignment_artifact(session, monkeypatch):
    """A missed edition must remain explainable after its transaction commits."""

    @contextmanager
    def session_scope():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    import reddit_tracker.newsroom.run as run_module

    monkeypatch.setattr(
        run_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_chat_id="100",
            newsroom_delivery_timezone="Asia/Taipei",
            newsroom_delivery_hour=8,
            newsroom_delivery_minute=30,
            newsroom_writer="template",
            newsroom_template_fallback=True,
        ),
    )
    monkeypatch.setattr(run_module, "session_scope", session_scope)

    with pytest.raises(EditorialPlanningError, match="insufficient"):
        prepare_edition(edition_date=date(2026, 9, 18), writer_mode="template")

    edition = session.scalar(select(NewsroomEdition).where(NewsroomEdition.edition_date == date(2026, 9, 18)))
    assert edition is not None
    assert edition.status == "planning_failed"
    assert edition.editor_summary is not None
    assert "insufficient" in edition.editor_summary
    assignment_run = session.scalar(
        select(AgentRun).where(
            AgentRun.edition_id == edition.id,
            AgentRun.stage == "assignment",
        )
    )
    assert assignment_run is not None
    assert assignment_run.status == "failed"
