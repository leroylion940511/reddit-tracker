"""SCHEDULE.md M5.9 — /saved + /timeline bot commands。"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from reddit_tracker.bot import handlers
from reddit_tracker.models import (
    CandidatePost,
    PostSnapshot,
    RelatedPost,
    TrackedPost,
)


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def patched_scope(session, monkeypatch):
    @contextlib.contextmanager
    def _scope():
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr(handlers, "session_scope", _scope)
    return session


def _make_tracked(session, *, rid="p1", sub="Taiwan", title="原貼",
                  user_id: int = 1, status="active", tier="hot",
                  hours_ago=8.0) -> TrackedPost:
    c = CandidatePost(
        reddit_post_id=rid, subreddit=sub, title=title, selftext="x",
        permalink=f"/r/{sub}/comments/{rid}/x/",
        author_username="alice",
        posted_at=NOW - timedelta(hours=hours_ago),
        initial_score=50, initial_num_comments=5,
    )
    session.add(c)
    session.flush()
    tp = TrackedPost(
        candidate_post_id=c.id, user_id=user_id, polling_tier=tier,
        status=status, promoted_at=NOW - timedelta(hours=hours_ago - 2),
    )
    session.add(tp)
    session.flush()
    return tp


def _make_snapshot(session, tp, *, score, num_comments, minutes_ago=10):
    s = PostSnapshot(
        tracked_post_id=tp.id, score=score, num_comments=num_comments,
        upvote_ratio=0.92,
    )
    session.add(s)
    session.flush()
    s.captured_at = NOW - timedelta(minutes=minutes_ago)
    session.flush()
    return s


def _make_related(session, tp, *, rid, relation_type="author_reply",
                  is_milestone=False, score=10.0, minutes_ago=30):
    r = RelatedPost(
        tracked_post_id=tp.id, reddit_post_id=rid,
        relation_type=relation_type, is_milestone=is_milestone,
        relevance_score=score,
        content=f"[fixture] {rid}",
        posted_at=NOW - timedelta(minutes=minutes_ago),
    )
    session.add(r)
    session.flush()
    r.discovered_at = NOW - timedelta(minutes=minutes_ago)
    session.flush()
    return r


# ---------------------------------------------------------------------------
# /saved
# ---------------------------------------------------------------------------


def test_saved_list_empty(patched_scope):
    text = handlers._saved_list_sync(user_id=999)
    assert "還沒收藏" in text


def test_saved_list_lists_user_only(patched_scope):
    session = patched_scope
    tp_mine = _make_tracked(session, rid="mine", title="我的", user_id=42)
    _make_tracked(session, rid="other", title="他的", user_id=99)
    text = handlers._saved_list_sync(user_id=42)
    assert "我的" in text
    assert "他的" not in text
    assert f"/timeline {tp_mine.id}" in text


def test_saved_list_shows_counts_and_tier(patched_scope):
    session = patched_scope
    tp = _make_tracked(session, user_id=42, tier="cooling")
    _make_snapshot(session, tp, score=100, num_comments=10, minutes_ago=10)
    _make_snapshot(session, tp, score=120, num_comments=12, minutes_ago=5)
    _make_related(session, tp, rid="r1")
    _make_related(session, tp, rid="r2", is_milestone=True, score=300, relation_type="hot_reply")

    text = handlers._saved_list_sync(user_id=42)
    assert "tier=cooling" in text
    assert "snapshots=2" in text
    assert "related=2" in text
    assert "★ 1" in text


def test_saved_list_marks_archived(patched_scope):
    session = patched_scope
    _make_tracked(session, user_id=42, status="archived", tier="archive")
    text = handlers._saved_list_sync(user_id=42)
    assert "[archived]" in text


# ---------------------------------------------------------------------------
# /timeline
# ---------------------------------------------------------------------------


def test_timeline_not_found(patched_scope):
    text = handlers._timeline_sync(user_id=42, tracked_id=99999)
    assert "找不到" in text


def test_timeline_wrong_user(patched_scope):
    session = patched_scope
    tp = _make_tracked(session, user_id=99)
    text = handlers._timeline_sync(user_id=42, tracked_id=tp.id)
    assert "不是你的收藏" in text


def test_timeline_shows_snapshots_and_related(patched_scope):
    session = patched_scope
    tp = _make_tracked(session, user_id=42, title="颱風天買到的便當")
    _make_snapshot(session, tp, score=85, num_comments=10, minutes_ago=240)
    _make_snapshot(session, tp, score=200, num_comments=42, minutes_ago=60)
    _make_related(session, tp, rid="c1", relation_type="author_reply",
                  is_milestone=True, minutes_ago=120)
    _make_related(session, tp, rid="xp1", relation_type="crosspost",
                  is_milestone=False, minutes_ago=30)

    text = handlers._timeline_sync(user_id=42, tracked_id=tp.id)
    assert "颱風天買到的便當" in text
    assert "快照變化" in text
    assert "score=200" in text
    assert "相關事件" in text
    assert "💬 原作回覆" in text
    assert "🔁 被轉貼" in text
    assert "★" in text                # milestone star prefix


def test_timeline_no_data_message(patched_scope):
    session = patched_scope
    tp = _make_tracked(session, user_id=42)
    text = handlers._timeline_sync(user_id=42, tracked_id=tp.id)
    assert "尚無任何快照" in text


# ---------------------------------------------------------------------------
# async wrappers
# ---------------------------------------------------------------------------


def _make_update(*, user_id=42, args=None):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.args = args or []
    return update, ctx


@pytest.mark.asyncio
async def test_saved_cmd_replies(patched_scope, monkeypatch):
    monkeypatch.setattr(handlers, "_saved_list_sync", lambda user_id: f"saved-for-{user_id}")
    update, ctx = _make_update(user_id=42)
    await handlers.saved_cmd(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    args, kwargs = update.effective_message.reply_text.call_args
    assert args[0] == "saved-for-42"
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_timeline_cmd_requires_id(patched_scope):
    update, ctx = _make_update(args=[])
    await handlers.timeline_cmd(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    args, _ = update.effective_message.reply_text.call_args
    assert "用法" in args[0]


@pytest.mark.asyncio
async def test_timeline_cmd_rejects_non_int(patched_scope):
    update, ctx = _make_update(args=["abc"])
    await handlers.timeline_cmd(update, ctx)
    args, _ = update.effective_message.reply_text.call_args
    assert "整數" in args[0]


@pytest.mark.asyncio
async def test_timeline_cmd_dispatches_to_sync(patched_scope, monkeypatch):
    captured = {}

    def fake(user_id, tracked_id):
        captured["user_id"] = user_id
        captured["tracked_id"] = tracked_id
        return "ok"

    monkeypatch.setattr(handlers, "_timeline_sync", fake)
    update, ctx = _make_update(user_id=42, args=["7"])
    await handlers.timeline_cmd(update, ctx)
    assert captured == {"user_id": 42, "tracked_id": 7}
