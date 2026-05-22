"""SCHEDULE.md M4.1–M4.3 — feed picker / breaking / daily_pushes 寫入測試。

涵蓋：
- pool 過濾（24h 視窗、final 未過 / 未評過排除）
- pick_daily_top5：already_hot / early_bet 桶分配、排序、邊界
- check_breaking：條件、top 1% 門檻、每日上限、不重推
- record_pushes：dedup（DB 既存 + 同批次重複）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from reddit_tracker.llm.base import HaikuVerdict
from reddit_tracker.models import CandidatePost, DailyPush, ScoringRecord
from reddit_tracker.services.feed import (
    ALREADY_HOT_MIN_AGE_H,
    BREAKING_DAILY_CAP,
    BREAKING_MAX_AGE_H,
    BREAKING_MIN_SEMANTIC,
    EARLY_BET_MAX_AGE_H,
    FeedPick,
    check_breaking,
    pick_daily_top5,
    record_pushes,
)


NOW = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_post(
    *,
    rid: str,
    age_hours: float = 4.0,
    subreddit: str = "Taiwan",
    score: int = 50,
    num_comments: int = 5,
    lang: str = "zh",
) -> CandidatePost:
    posted_at = NOW - timedelta(hours=age_hours)
    return CandidatePost(
        reddit_post_id=rid,
        subreddit=subreddit,
        title=f"標題 {rid}",
        selftext="本文 " * 50,
        permalink=f"/r/{subreddit}/comments/{rid}/x/",
        author_username="alice",
        author_karma=500,
        author_created_utc=NOW - timedelta(days=180),
        posted_at=posted_at,
        initial_score=score,
        initial_num_comments=num_comments,
        upvote_ratio=0.9,
        lang=lang,
        meta_json={"stickied": False},
    )


def _write_scoring(
    session,
    post: CandidatePost,
    *,
    velocity: float | None,
    semantic: float | None,
    final_score: float | None,
    verdict: str | None = "track",
    final_passed: bool | None = True,
) -> None:
    """直接寫三筆 scoring_records，繞過 ScoringService 以便精準控制每篇分數。"""
    session.add(
        ScoringRecord(
            candidate_post_id=post.id,
            stage="rules",
            passed=True,
            score=velocity,
            details={"velocity": velocity},
        )
    )
    haiku_details = {"verdict": verdict} if verdict else {}
    session.add(
        ScoringRecord(
            candidate_post_id=post.id,
            stage="haiku",
            passed=(verdict == "track"),
            score=semantic,
            details=haiku_details,
        )
    )
    session.add(
        ScoringRecord(
            candidate_post_id=post.id,
            stage="final",
            passed=final_passed,
            score=final_score,
            details={},
        )
    )


def _persist(session, post: CandidatePost) -> CandidatePost:
    session.add(post)
    session.flush()
    return post


# ---------------------------------------------------------------------------
# _load_pool 行為（透過 pick_daily_top5 觀察）
# ---------------------------------------------------------------------------


def test_pool_excludes_out_of_window(session):
    """posted_at 早於 24h 的不應該入池。"""
    old = _persist(session, _make_post(rid="old1", age_hours=30.0))
    fresh = _persist(session, _make_post(rid="fresh1", age_hours=8.0, score=200))
    _write_scoring(session, old, velocity=100.0, semantic=0.9, final_score=0.9)
    _write_scoring(session, fresh, velocity=50.0, semantic=0.7, final_score=0.7)
    session.flush()

    picks = pick_daily_top5(session, now=NOW)
    rids = {p.candidate.reddit_post_id for p in picks}
    assert "old1" not in rids
    assert "fresh1" in rids


def test_pool_excludes_unscored(session):
    p = _persist(session, _make_post(rid="unscored", age_hours=8.0))
    # 不寫 scoring_records → final 不存在 → 不入池
    picks = pick_daily_top5(session, now=NOW)
    assert picks == []


def test_pool_excludes_final_not_passed(session):
    p = _persist(session, _make_post(rid="failed", age_hours=8.0))
    _write_scoring(
        session, p,
        velocity=50.0, semantic=0.5, final_score=None,
        verdict="skip", final_passed=False,
    )
    session.flush()
    picks = pick_daily_top5(session, now=NOW)
    assert picks == []


# ---------------------------------------------------------------------------
# pick_daily_top5
# ---------------------------------------------------------------------------


def test_pick_top5_splits_buckets_by_age(session):
    """3 already_hot（age ≥ 6h）+ 2 early_bet（age < 3h）。"""
    # 3 hot 候選（不同 velocity，便於驗排序）
    h1 = _persist(session, _make_post(rid="h1", age_hours=8.0))
    h2 = _persist(session, _make_post(rid="h2", age_hours=10.0))
    h3 = _persist(session, _make_post(rid="h3", age_hours=12.0))
    h4 = _persist(session, _make_post(rid="h4", age_hours=12.0))  # 第 4 名會被丟
    _write_scoring(session, h1, velocity=80.0, semantic=0.6, final_score=0.7)
    _write_scoring(session, h2, velocity=120.0, semantic=0.6, final_score=0.7)
    _write_scoring(session, h3, velocity=40.0, semantic=0.6, final_score=0.7)
    _write_scoring(session, h4, velocity=10.0, semantic=0.6, final_score=0.6)

    # 2 early 候選
    e1 = _persist(session, _make_post(rid="e1", age_hours=1.0))
    e2 = _persist(session, _make_post(rid="e2", age_hours=2.0))
    e3 = _persist(session, _make_post(rid="e3", age_hours=2.5))
    _write_scoring(session, e1, velocity=20.0, semantic=0.75, final_score=0.6)
    _write_scoring(session, e2, velocity=20.0, semantic=0.9, final_score=0.65)
    _write_scoring(session, e3, velocity=20.0, semantic=0.5, final_score=0.5)

    session.flush()
    picks = pick_daily_top5(session, now=NOW)

    assert len(picks) == 5
    hot = [p for p in picks if p.push_type == "already_hot"]
    early = [p for p in picks if p.push_type == "early_bet"]
    assert [p.candidate.reddit_post_id for p in hot] == ["h2", "h1", "h3"]   # velocity 大→小
    assert [p.rank for p in hot] == [1, 2, 3]
    assert [p.candidate.reddit_post_id for p in early] == ["e2", "e1"]       # semantic 大→小
    assert [p.rank for p in early] == [1, 2]


def test_pick_top5_skips_middle_age_gap(session):
    """age 介於 3h–6h 之間既不算 hot 也不算 early，落空。"""
    p = _persist(session, _make_post(rid="mid", age_hours=4.5))
    _write_scoring(session, p, velocity=80.0, semantic=0.9, final_score=0.9)
    session.flush()
    assert pick_daily_top5(session, now=NOW) == []


def test_pick_top5_dedupes_across_buckets(session):
    """一個 candidate 不會同時出現在 hot + early（age 不會同時符合，這裡擋的是邏輯 path）。"""
    h = _persist(session, _make_post(rid="h", age_hours=8.0))
    _write_scoring(session, h, velocity=80.0, semantic=0.95, final_score=0.9)
    session.flush()
    picks = pick_daily_top5(session, now=NOW)
    rids = [p.candidate.reddit_post_id for p in picks]
    assert rids.count("h") == 1
    assert picks[0].push_type == "already_hot"


def test_pick_top5_partial_buckets(session):
    """只有 1 篇 hot，沒有 early → 回傳 1 筆，不會湊滿 5。"""
    h = _persist(session, _make_post(rid="h", age_hours=8.0))
    _write_scoring(session, h, velocity=80.0, semantic=0.6, final_score=0.7)
    session.flush()
    picks = pick_daily_top5(session, now=NOW)
    assert len(picks) == 1
    assert picks[0].push_type == "already_hot"


def test_pick_top5_age_boundary_exact_6h(session):
    """age 剛好等於 6h → 算 already_hot（>=）。"""
    p = _persist(session, _make_post(rid="bnd", age_hours=ALREADY_HOT_MIN_AGE_H))
    _write_scoring(session, p, velocity=50.0, semantic=0.6, final_score=0.6)
    session.flush()
    picks = pick_daily_top5(session, now=NOW)
    assert len(picks) == 1
    assert picks[0].push_type == "already_hot"


def test_pick_top5_age_boundary_exact_3h(session):
    """age 剛好等於 3h → 不算 early_bet（< 嚴格小於）。"""
    p = _persist(session, _make_post(rid="bnd", age_hours=EARLY_BET_MAX_AGE_H))
    _write_scoring(session, p, velocity=50.0, semantic=0.95, final_score=0.7)
    session.flush()
    picks = pick_daily_top5(session, now=NOW)
    assert picks == []


# ---------------------------------------------------------------------------
# check_breaking
# ---------------------------------------------------------------------------


def test_breaking_picks_one_when_all_conditions_met(session):
    # 高 velocity / 新鮮 / track / 高 semantic
    p = _persist(session, _make_post(rid="brk", age_hours=0.5, score=200, num_comments=40))
    _write_scoring(session, p, velocity=300.0, semantic=0.9, final_score=0.9)
    # 加幾個低分當分母
    for i in range(5):
        c = _persist(session, _make_post(rid=f"lo{i}", age_hours=5.0))
        _write_scoring(session, c, velocity=10.0, semantic=0.5, final_score=0.5)
    session.flush()

    picks = check_breaking(session, now=NOW)
    assert len(picks) == 1
    assert picks[0].candidate.reddit_post_id == "brk"
    assert picks[0].push_type == "breaking"


def test_breaking_age_must_be_under_1h(session):
    p = _persist(session, _make_post(rid="too_old", age_hours=2.0))
    _write_scoring(session, p, velocity=500.0, semantic=0.95, final_score=0.95)
    session.flush()
    assert check_breaking(session, now=NOW) == []


def test_breaking_semantic_must_be_above_threshold(session):
    p = _persist(session, _make_post(rid="meh", age_hours=0.5))
    _write_scoring(session, p, velocity=500.0, semantic=BREAKING_MIN_SEMANTIC, final_score=0.7)
    session.flush()
    # > 嚴格大於，等於不過
    assert check_breaking(session, now=NOW) == []


def test_breaking_verdict_must_be_track(session):
    p = _persist(session, _make_post(rid="skipv", age_hours=0.5))
    _write_scoring(session, p, velocity=500.0, semantic=0.9, final_score=0.6, verdict="skip", final_passed=False)
    session.flush()
    # final 沒過 → 連 pool 都不入
    assert check_breaking(session, now=NOW) == []


def test_breaking_respects_daily_cap(session):
    """已經有 2 篇 breaking 寫進 daily_pushes → 不再選。"""
    # 預先寫兩筆 breaking
    for i in range(BREAKING_DAILY_CAP):
        c = _persist(session, _make_post(rid=f"prev{i}", age_hours=0.5))
        session.add(
            DailyPush(
                push_date=NOW.date(),
                candidate_post_id=c.id,
                push_type="breaking",
                rank=i + 1,
            )
        )
    session.flush()
    # 第三個候選即使條件全中也不該被選
    p = _persist(session, _make_post(rid="brk3", age_hours=0.5))
    _write_scoring(session, p, velocity=999.0, semantic=0.95, final_score=0.95)
    session.flush()
    assert check_breaking(session, now=NOW) == []


def test_breaking_skips_already_pushed_today(session):
    """同一篇今天已經被推（例如早上 already_hot），不再因破例重推。"""
    p = _persist(session, _make_post(rid="dup", age_hours=0.5))
    _write_scoring(session, p, velocity=999.0, semantic=0.95, final_score=0.95)
    session.add(
        DailyPush(
            push_date=NOW.date(),
            candidate_post_id=p.id,
            push_type="early_bet",
            rank=1,
        )
    )
    session.flush()
    assert check_breaking(session, now=NOW) == []


# ---------------------------------------------------------------------------
# record_pushes — daily_pushes 寫入 + 防重複
# ---------------------------------------------------------------------------


def _pick_for(post, *, push_type="already_hot", rank=1) -> FeedPick:
    return FeedPick(
        candidate_post_id=post.id,
        candidate=post,
        push_type=push_type,
        rank=rank,
        velocity=50.0,
        semantic=0.7,
        final_score=0.7,
    )


def test_record_pushes_writes_new_rows(session):
    a = _persist(session, _make_post(rid="a", age_hours=8.0))
    b = _persist(session, _make_post(rid="b", age_hours=2.0))
    stat = record_pushes(session, [_pick_for(a), _pick_for(b, push_type="early_bet")], now=NOW)
    assert stat.inserted == 2
    assert stat.skipped_dupe == 0
    rows = session.scalars(select(DailyPush)).all()
    assert {r.candidate_post_id for r in rows} == {a.id, b.id}
    assert all(r.pushed_at is None for r in rows)  # 還沒送，留給 bot 寫回


def test_record_pushes_skips_existing_for_same_date(session):
    a = _persist(session, _make_post(rid="a", age_hours=8.0))
    # 已存在
    session.add(DailyPush(push_date=NOW.date(), candidate_post_id=a.id, push_type="already_hot", rank=1))
    session.flush()
    stat = record_pushes(session, [_pick_for(a)], now=NOW)
    assert stat.inserted == 0
    assert stat.skipped_dupe == 1


def test_record_pushes_dedupes_within_batch(session):
    """同一批 picks 含重複 candidate（例如 breaking 跟 already_hot 都選到同一篇）只寫一次。"""
    a = _persist(session, _make_post(rid="a", age_hours=0.5))
    stat = record_pushes(
        session,
        [_pick_for(a, push_type="already_hot"), _pick_for(a, push_type="breaking")],
        now=NOW,
    )
    assert stat.inserted == 1
    assert stat.skipped_dupe == 1
    rows = session.scalars(select(DailyPush)).all()
    assert len(rows) == 1


def test_record_pushes_empty_input(session):
    stat = record_pushes(session, [], now=NOW)
    assert stat.inserted == 0
    assert stat.skipped_dupe == 0
