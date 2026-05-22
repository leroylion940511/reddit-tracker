"""SCHEDULE.md M4.5 — feedback callback + record_feedback DB 邏輯測試。

- 直接用 in-memory session 驗 `services/feedback.record_feedback` 行為
- async `feedback_callback` 用 AsyncMock 模擬 Telegram 物件、patch sync wrapper
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from reddit_tracker.bot import handlers
from reddit_tracker.bot.formatter import (
    ACTION_COLLECT,
    ACTION_DISLIKE,
    ACTION_MUTE,
    encode_callback,
)
from reddit_tracker.models import CandidatePost, Feedback
from reddit_tracker.services.feedback import FeedbackOutcome, record_feedback


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


def _persist_candidate(session, *, rid: str = "abc1") -> CandidatePost:
    c = CandidatePost(
        reddit_post_id=rid,
        subreddit="Taiwan",
        title="t",
        selftext="x" * 100,
        permalink=f"/r/Taiwan/comments/{rid}/x/",
        author_username="alice",
        author_karma=500,
        author_created_utc=NOW - timedelta(days=180),
        posted_at=NOW - timedelta(hours=8),
        initial_score=100,
        initial_num_comments=10,
        upvote_ratio=0.9,
        lang="zh",
        meta_json={},
    )
    session.add(c)
    session.flush()
    return c


# ---------------------------------------------------------------------------
# record_feedback (sync, DB-backed)
# ---------------------------------------------------------------------------


def test_record_feedback_writes_new(session):
    c = _persist_candidate(session)
    out = record_feedback(session, user_id=999, candidate_post_id=c.id, action="collect")
    assert out.feedback_id is not None
    assert not out.duplicate
    assert not out.candidate_missing
    assert not out.invalid_action
    rows = session.scalars(select(Feedback)).all()
    assert len(rows) == 1
    assert rows[0].action == "collect"
    assert rows[0].user_id == 999


def test_record_feedback_dedups_same_triple(session):
    c = _persist_candidate(session)
    first = record_feedback(session, user_id=1, candidate_post_id=c.id, action="dislike")
    second = record_feedback(session, user_id=1, candidate_post_id=c.id, action="dislike")
    assert second.duplicate
    assert second.feedback_id == first.feedback_id
    assert len(session.scalars(select(Feedback)).all()) == 1


def test_record_feedback_distinct_actions_for_same_post(session):
    """同使用者對同一篇的不同 action 各算一筆，譬如先 dislike 再 mute_author。"""
    c = _persist_candidate(session)
    record_feedback(session, user_id=1, candidate_post_id=c.id, action="dislike")
    record_feedback(session, user_id=1, candidate_post_id=c.id, action="mute_author")
    rows = session.scalars(select(Feedback)).all()
    assert {r.action for r in rows} == {"dislike", "mute_author"}


def test_record_feedback_unknown_candidate(session):
    out = record_feedback(session, user_id=1, candidate_post_id=99999, action="collect")
    assert out.candidate_missing
    assert out.feedback_id is None
    assert session.scalars(select(Feedback)).all() == []


def test_record_feedback_invalid_action(session):
    c = _persist_candidate(session)
    out = record_feedback(session, user_id=1, candidate_post_id=c.id, action="hug")
    assert out.invalid_action
    assert out.feedback_id is None
    assert session.scalars(select(Feedback)).all() == []


# ---------------------------------------------------------------------------
# async feedback_callback
# ---------------------------------------------------------------------------


def _make_update(callback_data: str | None, user_id: int = 123, message_text: str | None = "原訊息"):
    """造一個最小 Telegram Update mock。所有 IO method 都是 AsyncMock。"""
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    if message_text is None:
        update.callback_query.message = None
    else:
        update.callback_query.message = MagicMock()
        update.callback_query.message.text = message_text
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    return update


@pytest.mark.asyncio
async def test_feedback_callback_writes_collect():
    update = _make_update(encode_callback(ACTION_COLLECT, 42))
    fake_outcome = FeedbackOutcome(feedback_id=1)
    with patch.object(handlers, "_record_feedback_sync", return_value=fake_outcome) as wr:
        await handlers.feedback_callback(update, None)
    wr.assert_called_once_with(123, 42, "collect")
    update.callback_query.answer.assert_awaited_once()
    args, _ = update.callback_query.answer.call_args
    assert "已收藏" in args[0]
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_feedback_callback_dislike_and_mute():
    update_d = _make_update(encode_callback(ACTION_DISLIKE, 42))
    update_m = _make_update(encode_callback(ACTION_MUTE, 42))
    out = FeedbackOutcome(feedback_id=1)
    with patch.object(handlers, "_record_feedback_sync", return_value=out) as wr:
        await handlers.feedback_callback(update_d, None)
        await handlers.feedback_callback(update_m, None)
    calls = [c.args for c in wr.call_args_list]
    assert calls == [(123, 42, "dislike"), (123, 42, "mute_author")]


@pytest.mark.asyncio
async def test_feedback_callback_unparseable_data():
    update = _make_update("garbage")
    with patch.object(handlers, "_record_feedback_sync") as wr:
        await handlers.feedback_callback(update, None)
    wr.assert_not_called()
    update.callback_query.answer.assert_awaited_once_with(handlers.INVALID_REPLY)


@pytest.mark.asyncio
async def test_feedback_callback_unknown_short_action():
    update = _make_update("fb:z:42")     # prefix ok, action 'z' 不在白名單
    with patch.object(handlers, "_record_feedback_sync") as wr:
        await handlers.feedback_callback(update, None)
    wr.assert_not_called()
    update.callback_query.answer.assert_awaited_once_with(handlers.INVALID_REPLY)


@pytest.mark.asyncio
async def test_feedback_callback_missing_candidate():
    update = _make_update(encode_callback(ACTION_COLLECT, 99999))
    out = FeedbackOutcome(feedback_id=None, candidate_missing=True)
    with patch.object(handlers, "_record_feedback_sync", return_value=out):
        await handlers.feedback_callback(update, None)
    update.callback_query.answer.assert_awaited_once_with(handlers.MISSING_REPLY)
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_callback_duplicate_appends_suffix():
    update = _make_update(encode_callback(ACTION_COLLECT, 42))
    out = FeedbackOutcome(feedback_id=1, duplicate=True)
    with patch.object(handlers, "_record_feedback_sync", return_value=out):
        await handlers.feedback_callback(update, None)
    args, _ = update.callback_query.answer.call_args
    assert "已收藏" in args[0]
    assert handlers.DUPLICATE_REPLY in args[0]


@pytest.mark.asyncio
async def test_feedback_callback_no_callback_query():
    """update.callback_query is None — early return，不應 raise / 不打 DB。"""
    update = MagicMock()
    update.callback_query = None
    with patch.object(handlers, "_record_feedback_sync") as wr:
        await handlers.feedback_callback(update, None)
    wr.assert_not_called()
