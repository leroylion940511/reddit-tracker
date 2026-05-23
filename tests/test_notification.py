"""SCHEDULE.md M5.8 — milestone push + daily digest selection。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from reddit_tracker.bot.formatter import (
    format_digest_message,
    format_milestone_message,
)
from reddit_tracker.models import (
    CandidatePost,
    RelatedPost,
    TrackedPost,
)
from reddit_tracker.services.notification import (
    build_daily_digest,
    fetch_pending_milestones,
    mark_notified,
)


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


def _make_tracked(session, *, rid="p1", sub="Taiwan", title="原貼", status="active") -> TrackedPost:
    c = CandidatePost(
        reddit_post_id=rid, subreddit=sub, title=title, selftext="x",
        permalink=f"/r/{sub}/comments/{rid}/x/",
        author_username="alice",
        posted_at=NOW - timedelta(hours=10),
        initial_score=50, initial_num_comments=5,
    )
    session.add(c)
    session.flush()
    tp = TrackedPost(
        candidate_post_id=c.id, user_id=1, polling_tier="hot", status=status,
    )
    session.add(tp)
    session.flush()
    return tp


def _make_related(
    session, tp, *, rid="x1", relation_type="hot_reply", score=200.0,
    is_milestone=True, content="x", discovered_minutes_ago=10, notified=False,
) -> RelatedPost:
    rp = RelatedPost(
        tracked_post_id=tp.id,
        reddit_post_id=rid,
        relation_type=relation_type,
        relevance_score=score,
        is_milestone=is_milestone,
        content=content,
        posted_at=NOW - timedelta(minutes=discovered_minutes_ago),
        notified_at=NOW if notified else None,
    )
    session.add(rp)
    session.flush()
    # 把 discovered_at 改成相對 NOW，避免 server_default 把它寫成測試時間
    rp.discovered_at = NOW - timedelta(minutes=discovered_minutes_ago)
    session.flush()
    return rp


# ---------------------------------------------------------------------------
# fetch_pending_milestones
# ---------------------------------------------------------------------------


def test_fetch_pending_milestones_filters_notified_and_non_milestone(session):
    tp = _make_tracked(session)
    pending = _make_related(session, tp, rid="m1", is_milestone=True, notified=False)
    _make_related(session, tp, rid="m2", is_milestone=True, notified=True)       # 已通知
    _make_related(session, tp, rid="m3", is_milestone=False, notified=False)     # 非 milestone
    found = fetch_pending_milestones(session)
    assert [p.related.id for p in found] == [pending.id]


def test_fetch_pending_milestones_skips_archived_tracked(session):
    tp = _make_tracked(session, status="archived")
    _make_related(session, tp, is_milestone=True, notified=False)
    assert fetch_pending_milestones(session) == []


def test_fetch_pending_milestones_join_returns_tracked_and_candidate(session):
    tp = _make_tracked(session)
    _make_related(session, tp, rid="m1", is_milestone=True, notified=False)
    [p] = fetch_pending_milestones(session)
    assert p.tracked.id == tp.id
    assert p.candidate.id == tp.candidate_post_id


# ---------------------------------------------------------------------------
# mark_notified
# ---------------------------------------------------------------------------


def test_mark_notified_writes_timestamp(session):
    tp = _make_tracked(session)
    r1 = _make_related(session, tp, rid="m1", is_milestone=True, notified=False)
    r2 = _make_related(session, tp, rid="m2", is_milestone=True, notified=False)
    n = mark_notified(session, [r1.id, r2.id], now=NOW)
    assert n == 2
    assert session.get(RelatedPost, r1.id).notified_at == NOW
    assert session.get(RelatedPost, r2.id).notified_at == NOW


def test_mark_notified_idempotent(session):
    tp = _make_tracked(session)
    r1 = _make_related(session, tp, rid="m1", is_milestone=True, notified=False)
    mark_notified(session, [r1.id], now=NOW)
    n2 = mark_notified(session, [r1.id], now=NOW + timedelta(hours=1))
    assert n2 == 0
    assert session.get(RelatedPost, r1.id).notified_at == NOW    # 第一次的時間，不被覆寫


# ---------------------------------------------------------------------------
# build_daily_digest
# ---------------------------------------------------------------------------


def test_digest_groups_by_tracked_and_excludes_milestone_and_notified(session):
    tp1 = _make_tracked(session, rid="p1", title="A")
    tp2 = _make_tracked(session, rid="p2", title="B")
    # tp1: 2 non-milestone (digest 候選) + 1 milestone（不應入 digest）
    _make_related(session, tp1, rid="a1", relation_type="author_reply",
                  is_milestone=False, score=10, discovered_minutes_ago=120)
    _make_related(session, tp1, rid="a2", relation_type="hot_reply",
                  is_milestone=False, score=30, discovered_minutes_ago=60)
    _make_related(session, tp1, rid="ms", is_milestone=True, score=300,
                  discovered_minutes_ago=30)
    # tp2: 1 non-milestone notified（排除）+ 1 unnotified
    _make_related(session, tp2, rid="b1", is_milestone=False, score=5,
                  discovered_minutes_ago=10, notified=True)
    _make_related(session, tp2, rid="b2", relation_type="crosspost",
                  is_milestone=False, score=15, discovered_minutes_ago=5)

    entries = build_daily_digest(session, now=NOW, lookback_hours=24)
    by_tp = {e.tracked.id: e for e in entries}
    assert set(by_tp.keys()) == {tp1.id, tp2.id}
    assert {r.reddit_post_id for r in by_tp[tp1.id].related} == {"a1", "a2"}
    assert [r.reddit_post_id for r in by_tp[tp2.id].related] == ["b2"]


def test_digest_respects_lookback_cutoff(session):
    tp = _make_tracked(session)
    _make_related(session, tp, rid="recent", is_milestone=False,
                  discovered_minutes_ago=120)
    _make_related(session, tp, rid="old", is_milestone=False,
                  discovered_minutes_ago=2000)  # > 24h
    entries = build_daily_digest(session, now=NOW, lookback_hours=24)
    assert len(entries) == 1
    assert [r.reddit_post_id for r in entries[0].related] == ["recent"]


def test_digest_caps_max_per_tracked(session):
    tp = _make_tracked(session)
    # 7 條，全部 unnotified 非-milestone
    for i in range(7):
        _make_related(
            session, tp, rid=f"r{i}", is_milestone=False,
            score=float(7 - i),                # 高 → 低，i=0 最高
            discovered_minutes_ago=30 + i,
        )
    entries = build_daily_digest(session, now=NOW, max_per_tracked=3)
    assert len(entries) == 1
    # 取 relevance 最高的 3 條 → r0 / r1 / r2
    assert {r.reddit_post_id for r in entries[0].related} == {"r0", "r1", "r2"}


# ---------------------------------------------------------------------------
# Formatter smoke — 不真送，純驗字串
# ---------------------------------------------------------------------------


def test_format_milestone_message_has_label_and_link(session):
    tp = _make_tracked(session)
    r = _make_related(session, tp, rid="m1", relation_type="hot_reply",
                      content="[hot reply, score=300] 大爆炸留言", is_milestone=True)
    from reddit_tracker.services.notification import PendingMilestone
    pending = PendingMilestone(related=r, tracked=tp, candidate=tp.candidate)
    text = format_milestone_message(pending)
    assert "🎯" in text
    assert "🔥 高熱度留言" in text
    assert "大爆炸留言" in text
    assert "原文" in text


def test_format_digest_message_groups_per_tracked(session):
    tp1 = _make_tracked(session, rid="p1", title="A")
    tp2 = _make_tracked(session, rid="p2", title="B")
    _make_related(session, tp1, rid="a1", relation_type="author_reply",
                  is_milestone=False, score=10, discovered_minutes_ago=60)
    _make_related(session, tp2, rid="b1", relation_type="crosspost",
                  is_milestone=False, score=15, discovered_minutes_ago=30)
    entries = build_daily_digest(session, now=NOW)
    text = format_digest_message(entries)
    assert "今日彙整" in text
    assert "💬 原作回覆" in text
    assert "🔁 被轉貼" in text
