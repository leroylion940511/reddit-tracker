"""SCHEDULE.md M5.1 — collect → promote 升格邏輯。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from reddit_tracker.bot import handlers
from reddit_tracker.models import (
    CandidatePost,
    SubredditSource,
    TrackedPost,
)
from reddit_tracker.services.promotion import (
    ACTIVE_STATUS,
    INITIAL_TIER,
    promote_to_tracked,
)


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


def _persist_candidate(session, *, rid: str = "cand1", sub: str = "Taiwan") -> CandidatePost:
    c = CandidatePost(
        reddit_post_id=rid,
        subreddit=sub,
        title="t",
        selftext="x" * 100,
        permalink=f"/r/{sub}/comments/{rid}/x/",
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


def _persist_subreddit_source(session, *, name: str = "Taiwan") -> SubredditSource:
    s = SubredditSource(name=name, lang_hint="zh", enabled=True)
    session.add(s)
    session.flush()
    return s


# ---------------------------------------------------------------------------
# promote_to_tracked
# ---------------------------------------------------------------------------


def test_promote_creates_tracked_row(session):
    c = _persist_candidate(session)
    out = promote_to_tracked(session, user_id=42, candidate_post_id=c.id)
    assert out.created
    assert out.tracked_post_id is not None
    assert not out.already_tracked

    tracked = session.get(TrackedPost, out.tracked_post_id)
    assert tracked is not None
    assert tracked.candidate_post_id == c.id
    assert tracked.user_id == 42
    assert tracked.polling_tier == INITIAL_TIER == "hot"
    assert tracked.status == ACTIVE_STATUS == "active"
    assert tracked.last_polled_at is None


def test_promote_is_idempotent_on_candidate(session):
    """同 candidate 第二次 promote — 不再寫新 row、回現有 id、already_tracked=True。"""
    c = _persist_candidate(session)
    first = promote_to_tracked(session, user_id=1, candidate_post_id=c.id)
    second = promote_to_tracked(session, user_id=2, candidate_post_id=c.id)
    assert first.created
    assert second.already_tracked
    assert second.tracked_post_id == first.tracked_post_id
    rows = session.scalars(select(TrackedPost)).all()
    assert len(rows) == 1
    assert rows[0].user_id == 1                # 首位收藏者保留


def test_promote_unknown_candidate(session):
    out = promote_to_tracked(session, user_id=1, candidate_post_id=99999)
    assert out.candidate_missing
    assert out.tracked_post_id is None
    assert session.scalars(select(TrackedPost)).all() == []


def test_promote_bumps_subreddit_total_collected(session):
    src = _persist_subreddit_source(session, name="Taiwan")
    c = _persist_candidate(session, sub="Taiwan")
    assert src.total_collected == 0
    promote_to_tracked(session, user_id=1, candidate_post_id=c.id)
    assert src.total_collected == 1


def test_promote_subreddit_source_missing_is_noop(session):
    """sub 在 subreddit_sources 沒登錄（從 keyword 流入的）— promote 仍成立。"""
    c = _persist_candidate(session, sub="UnregisteredSub")
    out = promote_to_tracked(session, user_id=1, candidate_post_id=c.id)
    assert out.created
    # 沒對應 SubredditSource，但不報錯
    assert session.scalars(
        select(SubredditSource).where(SubredditSource.name == "UnregisteredSub")
    ).all() == []


def test_promote_second_collect_does_not_double_bump(session):
    """同篇被第二位使用者收藏 — promote idempotent，total_collected 也不應再加。"""
    src = _persist_subreddit_source(session, name="Taiwan")
    c = _persist_candidate(session, sub="Taiwan")
    promote_to_tracked(session, user_id=1, candidate_post_id=c.id)
    promote_to_tracked(session, user_id=2, candidate_post_id=c.id)
    assert src.total_collected == 1


# ---------------------------------------------------------------------------
# handlers._record_feedback_sync — collect 觸發 promotion
# ---------------------------------------------------------------------------


def test_record_feedback_sync_collect_promotes(session, monkeypatch):
    """integration: feedback 寫入 + tracked 升格 在同一 session_scope 完成。"""
    from reddit_tracker import db as db_mod

    # 把 session_scope 換成 yield 這個 in-memory session、commit 走測試控制
    import contextlib

    @contextlib.contextmanager
    def _fake_scope():
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise

    c = _persist_candidate(session)
    monkeypatch.setattr(handlers, "session_scope", _fake_scope)
    monkeypatch.setattr(db_mod, "session_scope", _fake_scope)

    out = handlers._record_feedback_sync(user_id=7, candidate_id=c.id, action="collect")
    assert out.feedback_id is not None

    tracked = session.scalar(
        select(TrackedPost).where(TrackedPost.candidate_post_id == c.id)
    )
    assert tracked is not None
    assert tracked.user_id == 7


def test_record_feedback_sync_dislike_does_not_promote(session, monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def _fake_scope():
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise

    c = _persist_candidate(session)
    monkeypatch.setattr(handlers, "session_scope", _fake_scope)
    handlers._record_feedback_sync(user_id=7, candidate_id=c.id, action="dislike")
    assert session.scalars(select(TrackedPost)).all() == []


def test_record_feedback_sync_collect_missing_candidate_no_promotion(session, monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def _fake_scope():
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr(handlers, "session_scope", _fake_scope)
    out = handlers._record_feedback_sync(user_id=7, candidate_id=99999, action="collect")
    assert out.candidate_missing
    assert session.scalars(select(TrackedPost)).all() == []
