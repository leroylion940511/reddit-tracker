"""Plan C 階段補上的三個指令：/feed /digest /settings。"""

from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from reddit_tracker.bot import handlers
from reddit_tracker.config import get_settings
from reddit_tracker.models import (
    CandidatePost,
    DailyPush,
    RelatedPost,
    ScoringRecord,
    TrackedPost,
)


NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


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
    # 重置 settings cache，避免測試間互相污染
    get_settings.cache_clear()
    return session


def _make_candidate(session, *, rid: str, sub="Taiwan", title="test post",
                    hours_ago=2.0) -> CandidatePost:
    c = CandidatePost(
        reddit_post_id=rid, subreddit=sub, title=title, selftext="x",
        permalink=f"/r/{sub}/comments/{rid}/x/",
        author_username="alice",
        posted_at=NOW - timedelta(hours=hours_ago),
        initial_score=50, initial_num_comments=5,
    )
    session.add(c)
    session.flush()
    c.discovered_at = NOW - timedelta(hours=hours_ago)
    session.flush()
    return c


def _make_tracked(session, c: CandidatePost, *, user_id=42, status="active",
                  tier="hot") -> TrackedPost:
    tp = TrackedPost(
        candidate_post_id=c.id, user_id=user_id, polling_tier=tier,
        status=status, promoted_at=NOW - timedelta(hours=1),
    )
    session.add(tp)
    session.flush()
    return tp


def _make_push(session, c: CandidatePost, *, ptype="already_hot", rank=1,
               push_date: date | None = None) -> DailyPush:
    dp = DailyPush(
        push_date=push_date or TODAY,
        candidate_post_id=c.id,
        push_type=ptype,
        rank=rank,
    )
    session.add(dp)
    session.flush()
    return dp


def _make_scoring(session, c: CandidatePost, *, stage="final", passed=True,
                  score=0.85, hours_ago=1.0) -> ScoringRecord:
    sr = ScoringRecord(
        candidate_post_id=c.id, stage=stage, passed=passed, score=score,
        cost_usd=Decimal("0.0002"),
    )
    session.add(sr)
    session.flush()
    sr.scored_at = NOW - timedelta(hours=hours_ago)
    session.flush()
    return sr


def _make_milestone(session, tp: TrackedPost, *, rid="m1",
                    relation_type="hot_reply", score=200.0,
                    hours_ago=12.0) -> RelatedPost:
    r = RelatedPost(
        tracked_post_id=tp.id, reddit_post_id=rid,
        relation_type=relation_type, is_milestone=True,
        relevance_score=score,
        content=f"milestone content for {rid}",
        posted_at=NOW - timedelta(hours=hours_ago),
    )
    session.add(r)
    session.flush()
    r.discovered_at = NOW - timedelta(hours=hours_ago)
    session.flush()
    return r


# ---------------------------------------------------------------------------
# /feed
# ---------------------------------------------------------------------------


def test_feed_empty_no_pushes_no_finals(patched_scope):
    text = handlers._feed_today_sync(user_id=42)
    assert "尚未推送" in text
    assert "沒有通過評分" in text


def test_feed_today_groups_by_push_type(patched_scope):
    session = patched_scope
    c1 = _make_candidate(session, rid="h1", title="hot post zh", sub="Taiwan")
    c2 = _make_candidate(session, rid="h2", title="hot post en", sub="tifu")
    c3 = _make_candidate(session, rid="e1", title="early bet", sub="Taiwan")
    c4 = _make_candidate(session, rid="b1", title="breaking news!", sub="HongKong")
    _make_push(session, c1, ptype="already_hot", rank=1)
    _make_push(session, c2, ptype="already_hot", rank=2)
    _make_push(session, c3, ptype="early_bet", rank=1)
    _make_push(session, c4, ptype="breaking", rank=1)

    text = handlers._feed_today_sync(user_id=42)
    assert "今日推送" in text
    assert "已爆貼（2）" in text
    assert "早期下注（1）" in text
    assert "即時破例（1）" in text
    assert "hot post zh" in text
    assert "early bet" in text
    assert "breaking news!" in text
    assert "r/Taiwan" in text


def test_feed_only_shows_today(patched_scope):
    session = patched_scope
    c_today = _make_candidate(session, rid="today", title="today push")
    c_old = _make_candidate(session, rid="old", title="yesterday push")
    _make_push(session, c_today, ptype="already_hot", rank=1)
    _make_push(session, c_old, ptype="already_hot", rank=1,
               push_date=TODAY - timedelta(days=1))

    text = handlers._feed_today_sync(user_id=42)
    assert "today push" in text
    assert "yesterday push" not in text


def test_feed_fallback_to_recent_finals(patched_scope):
    session = patched_scope
    # 沒有 daily_pushes，但有 24h 內通過 final 的 candidate
    for i in range(3):
        c = _make_candidate(session, rid=f"f{i}", title=f"final {i}")
        _make_scoring(session, c, stage="final", passed=True,
                      score=0.9 - i * 0.05)
    # 一筆 final 但 passed=False，不該入選
    c_fail = _make_candidate(session, rid="fail", title="rejected")
    _make_scoring(session, c_fail, stage="final", passed=False, score=0.3)

    text = handlers._feed_today_sync(user_id=42)
    assert "尚未推送" in text
    assert "近 24h" in text
    assert "final 0" in text
    assert "final 1" in text
    assert "final 2" in text
    assert "rejected" not in text


def test_feed_fallback_ignores_stale_finals(patched_scope):
    session = patched_scope
    c = _make_candidate(session, rid="old_final", title="too old")
    _make_scoring(session, c, stage="final", passed=True, score=0.9,
                  hours_ago=48)

    text = handlers._feed_today_sync(user_id=42)
    assert "沒有通過評分" in text
    assert "too old" not in text


# ---------------------------------------------------------------------------
# /digest
# ---------------------------------------------------------------------------


def test_digest_no_collections_at_all(patched_scope):
    text = handlers._digest_sync(user_id=42)
    assert "還沒收藏" in text


def test_digest_has_collections_but_no_milestone(patched_scope):
    session = patched_scope
    c = _make_candidate(session, rid="c1")
    _make_tracked(session, c, user_id=42)
    text = handlers._digest_sync(user_id=42)
    assert "沒有任何 milestone" in text
    assert "active 收藏 1 篇" in text


def test_digest_groups_milestones_by_tracked(patched_scope):
    session = patched_scope
    c1 = _make_candidate(session, rid="t1", title="貼 A")
    c2 = _make_candidate(session, rid="t2", title="貼 B")
    tp1 = _make_tracked(session, c1, user_id=42)
    tp2 = _make_tracked(session, c2, user_id=42)
    _make_milestone(session, tp1, rid="a1", relation_type="hot_reply", score=300)
    _make_milestone(session, tp1, rid="a2", relation_type="author_reply", score=50)
    _make_milestone(session, tp2, rid="b1", relation_type="crosspost", score=120)

    text = handlers._digest_sync(user_id=42)
    assert "本週摘要" in text
    assert "3 個 milestone" in text
    assert "2 篇收藏" in text
    assert "貼 A" in text
    assert "貼 B" in text
    assert f"/timeline {tp1.id}" in text
    assert f"/timeline {tp2.id}" in text


def test_digest_excludes_other_users_and_stale(patched_scope):
    session = patched_scope
    c_mine = _make_candidate(session, rid="m1", title="我的")
    c_other = _make_candidate(session, rid="o1", title="他的")
    tp_mine = _make_tracked(session, c_mine, user_id=42)
    tp_other = _make_tracked(session, c_other, user_id=99)
    _make_milestone(session, tp_mine, rid="recent", hours_ago=12)
    _make_milestone(session, tp_other, rid="other_user", hours_ago=12)
    _make_milestone(session, tp_mine, rid="too_old", hours_ago=24 * 8)

    text = handlers._digest_sync(user_id=42)
    assert "我的" in text
    assert "他的" not in text
    assert "1 個 milestone" in text  # too_old 不計、other_user 不計


def test_digest_excludes_non_milestone(patched_scope):
    session = patched_scope
    c = _make_candidate(session, rid="c1", title="貼 X")
    tp = _make_tracked(session, c, user_id=42)
    # 一筆 milestone, 一筆非 milestone
    _make_milestone(session, tp, rid="ms")
    r = RelatedPost(
        tracked_post_id=tp.id, reddit_post_id="not_ms",
        relation_type="author_reply", is_milestone=False, relevance_score=5.0,
        content="not a milestone", posted_at=NOW - timedelta(hours=1),
    )
    session.add(r)
    session.flush()
    r.discovered_at = NOW - timedelta(hours=1)
    session.flush()

    text = handlers._digest_sync(user_id=42)
    assert "1 個 milestone" in text


# ---------------------------------------------------------------------------
# /settings
# ---------------------------------------------------------------------------


def test_settings_shows_scraper_mode(patched_scope, monkeypatch):
    monkeypatch.setenv("REDDIT_SCRAPER", "rss")
    get_settings.cache_clear()
    text = handlers._settings_sync(user_id=42)
    assert "RSS fallback (Plan C)" in text
    assert "Plan C" in text  # warning banner


def test_settings_no_plan_c_warning_for_public_json(patched_scope, monkeypatch):
    monkeypatch.setenv("REDDIT_SCRAPER", "public_json")
    get_settings.cache_clear()
    text = handlers._settings_sync(user_id=42)
    assert "public JSON" in text
    assert "Plan C：" not in text


def test_settings_shows_counts(patched_scope):
    session = patched_scope
    # 過去 24h 內：3 candidate / 2 rules pass / 1 final pass / 1 push
    cs = [_make_candidate(session, rid=f"c{i}") for i in range(3)]
    _make_scoring(session, cs[0], stage="rules", passed=True, score=None)
    _make_scoring(session, cs[1], stage="rules", passed=True, score=None)
    _make_scoring(session, cs[2], stage="rules", passed=False, score=None)
    _make_scoring(session, cs[0], stage="final", passed=True, score=0.85)
    _make_push(session, cs[0])
    # user=42 收藏 1 篇，archived 1 篇
    _make_tracked(session, cs[0], user_id=42, status="active")
    _make_tracked(session, cs[1], user_id=42, status="archived")
    # user=99 的收藏不該被算
    _make_tracked(session, cs[2], user_id=99, status="active")

    text = handlers._settings_sync(user_id=42)
    assert "新候選：3" in text
    assert "rules 通過：2/3" in text
    assert "67%" in text
    assert "final 通過：1" in text
    assert "今日已推送：1" in text
    assert "active 收藏：1" in text
    assert "archived：1" in text
    assert "user_id" in text


def test_settings_handles_no_data(patched_scope):
    text = handlers._settings_sync(user_id=42)
    assert "新候選：0" in text
    assert "rules 通過：0/0" in text
    assert "0%" in text
    assert "active 收藏：0" in text


# ---------------------------------------------------------------------------
# async cmd dispatchers
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
async def test_feed_cmd_dispatches(patched_scope, monkeypatch):
    monkeypatch.setattr(handlers, "_feed_today_sync",
                        lambda user_id: f"feed-{user_id}")
    update, ctx = _make_update(user_id=42)
    await handlers.feed_cmd(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()
    args, kwargs = update.effective_message.reply_text.call_args
    assert args[0] == "feed-42"
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_digest_cmd_dispatches(patched_scope, monkeypatch):
    monkeypatch.setattr(handlers, "_digest_sync",
                        lambda user_id: f"digest-{user_id}")
    update, ctx = _make_update(user_id=7)
    await handlers.digest_cmd(update, ctx)
    args, kwargs = update.effective_message.reply_text.call_args
    assert args[0] == "digest-7"
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_settings_cmd_dispatches(patched_scope, monkeypatch):
    monkeypatch.setattr(handlers, "_settings_sync",
                        lambda user_id: f"settings-{user_id}")
    update, ctx = _make_update(user_id=99)
    await handlers.settings_cmd(update, ctx)
    args, kwargs = update.effective_message.reply_text.call_args
    assert args[0] == "settings-99"
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_feed_cmd_requires_user(patched_scope):
    update, ctx = _make_update()
    update.effective_user = None
    await handlers.feed_cmd(update, ctx)
    update.effective_message.reply_text.assert_not_called()
