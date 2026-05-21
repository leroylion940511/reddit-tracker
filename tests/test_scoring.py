"""SCHEDULE.md M3.8 — scoring 三段式 unit test。

涵蓋：
- 硬規則邊界（velocity / karma / 帳號齡 / 長度 / 語言 / 黑名單 / stickied）
- combine_final 加權與正規化
- ScoringService 三段寫入 + 略過 / 失敗路徑
- Haiku response 解析（JSON fence / invalid verdict / out-of-range）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from reddit_tracker.llm.base import HaikuVerdict
from reddit_tracker.llm.fake import FakeScorer
from reddit_tracker.llm.haiku import (
    parse_haiku_response,
    verdict_from_payload,
)
from reddit_tracker.models import CandidatePost, ScoringRecord
from reddit_tracker.services.scoring import (
    MAX_AUTHOR_KARMA,
    MAX_BODY_CHARS,
    MIN_BODY_CHARS,
    MIN_VELOCITY,
    ScoringService,
    apply_hard_rules,
    combine_final,
    detect_lang,
    fetch_unscored,
    normalize_velocity,
    score_batch,
)


NOW = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)


def _make_post(
    *,
    age_hours: float = 4.0,
    score: int = 50,
    num_comments: int = 5,
    karma: int | None = 500,
    account_age_days: int | None = 90,
    title: str = "事件記錄",
    selftext: str = "x" * 200,
    lang: str | None = "zh",
    meta: dict | None = None,
    rid: str = "abc1",
    subreddit: str = "Taiwan",
) -> CandidatePost:
    posted_at = NOW - timedelta(hours=age_hours)
    created = (
        NOW - timedelta(days=account_age_days) if account_age_days is not None else None
    )
    return CandidatePost(
        reddit_post_id=rid,
        subreddit=subreddit,
        title=title,
        selftext=selftext,
        permalink=f"/r/{subreddit}/comments/{rid}/x/",
        author_username="alice",
        author_karma=karma,
        author_created_utc=created,
        posted_at=posted_at,
        initial_score=score,
        initial_num_comments=num_comments,
        upvote_ratio=0.9,
        lang=lang,
        meta_json=meta or {"stickied": False},
    )


# ---------------------------------------------------------------------------
# detect_lang
# ---------------------------------------------------------------------------


def test_detect_lang_zh_majority():
    assert detect_lang("這是一段中文 with some english") == "zh"


def test_detect_lang_en_default():
    assert detect_lang("totally english sentence here") == "en"


def test_detect_lang_empty():
    assert detect_lang("") == "unknown"
    assert detect_lang("12345 !!!") == "unknown"


# ---------------------------------------------------------------------------
# apply_hard_rules — 各條規則邊界
# ---------------------------------------------------------------------------


def test_rules_pass_baseline():
    post = _make_post()
    res = apply_hard_rules(post, now=NOW)
    assert res.passed
    assert res.details["fail_reasons"] == []
    assert res.velocity is not None
    assert res.velocity >= MIN_VELOCITY


def test_rules_fail_low_velocity():
    # ups + 2c = 5 + 0 = 5, age 4h → velocity = 1.25 < 5
    post = _make_post(score=5, num_comments=0)
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any("velocity" in r for r in res.details["fail_reasons"])


def test_rules_fail_high_karma():
    post = _make_post(karma=MAX_AUTHOR_KARMA + 1)
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any("karma" in r for r in res.details["fail_reasons"])


def test_rules_karma_unknown_passes():
    """public JSON 拿不到 karma 時不應該被擋。"""
    post = _make_post(karma=None)
    res = apply_hard_rules(post, now=NOW)
    assert res.passed


def test_rules_fail_young_account():
    post = _make_post(account_age_days=10)
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any("account_age" in r for r in res.details["fail_reasons"])


def test_rules_account_age_unknown_passes():
    post = _make_post(account_age_days=None)
    res = apply_hard_rules(post, now=NOW)
    assert res.passed


def test_rules_fail_too_short():
    post = _make_post(selftext="短", title="t")
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any(f"body_len<{MIN_BODY_CHARS}" in r for r in res.details["fail_reasons"])


def test_rules_fail_too_long():
    post = _make_post(selftext="x" * (MAX_BODY_CHARS + 10))
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any(f"body_len>{MAX_BODY_CHARS}" in r for r in res.details["fail_reasons"])


def test_rules_fail_unknown_lang():
    post = _make_post(lang="ko", selftext="한국어 본문 " * 30, title="한국어")
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any("lang=" in r for r in res.details["fail_reasons"])


def test_rules_fail_blacklist():
    post = _make_post(title="業配文", selftext="這是業配內容 " * 30)
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert any("blacklist" in r for r in res.details["fail_reasons"])


def test_rules_fail_stickied():
    post = _make_post(meta={"stickied": True})
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert "stickied" in res.details["fail_reasons"]


def test_rules_fail_mod_distinguished():
    post = _make_post(meta={"stickied": False, "distinguished": "moderator"})
    res = apply_hard_rules(post, now=NOW)
    assert not res.passed
    assert "distinguished=mod" in res.details["fail_reasons"]


# ---------------------------------------------------------------------------
# combine_final
# ---------------------------------------------------------------------------


def test_normalize_velocity_monotonic():
    assert normalize_velocity(None) == 0.0
    assert normalize_velocity(0) == 0.0
    a, b, c = normalize_velocity(5), normalize_velocity(50), normalize_velocity(500)
    assert 0 < a < b < c < 1


def test_combine_final_haiku_none_returns_none():
    assert combine_final(velocity=10.0, haiku=None) is None


def test_combine_final_weights_apply():
    verdict = HaikuVerdict(
        story_potential=0.8,
        emotional_pull=0.6,
        grassroots=0.9,
        novelty=0.5,
        authenticity=0.7,
        verdict="track",
        reason="t",
    )
    score = combine_final(velocity=50.0, haiku=verdict)
    # 手算：v_norm = 50 / (50 + 10) = 0.8333
    # s = (0.8 + 0.6) / 2 = 0.7
    # final = 0.4·0.8333 + 0.3·0.7 + 0.2·0.9 + 0.1·0.5 = 0.7733
    assert score is not None
    assert abs(score - 0.7733) < 0.001


# ---------------------------------------------------------------------------
# Haiku response parsing
# ---------------------------------------------------------------------------


def test_parse_haiku_response_pure_json():
    raw = '{"story_potential": 0.6, "emotional_pull": 0.5, "grassroots": 0.7, ' \
          '"novelty": 0.4, "authenticity": 0.8, "verdict": "track", "reason": "ok"}'
    data = parse_haiku_response(raw)
    v = verdict_from_payload(data)
    assert v.verdict == "track"
    assert v.story_potential == 0.6


def test_parse_haiku_response_with_fence():
    raw = "閒聊一下\n```json\n{\"story_potential\": 0.5, \"emotional_pull\": 0.5, " \
          "\"grassroots\": 0.5, \"novelty\": 0.5, \"authenticity\": 0.5, " \
          "\"verdict\": \"skip\", \"reason\": \"meh\"}\n```\n結束"
    data = parse_haiku_response(raw)
    v = verdict_from_payload(data)
    assert v.verdict == "skip"


def test_verdict_invalid_verdict_raises():
    data = {
        "story_potential": 0.5, "emotional_pull": 0.5, "grassroots": 0.5,
        "novelty": 0.5, "authenticity": 0.5,
        "verdict": "maybe", "reason": "x",
    }
    with pytest.raises(ValueError, match="invalid verdict"):
        verdict_from_payload(data)


def test_verdict_axis_out_of_range_raises():
    data = {
        "story_potential": 1.5, "emotional_pull": 0.5, "grassroots": 0.5,
        "novelty": 0.5, "authenticity": 0.5,
        "verdict": "track", "reason": "x",
    }
    with pytest.raises(ValueError, match="out of range"):
        verdict_from_payload(data)


def test_parse_haiku_invalid_json_raises():
    with pytest.raises(Exception):
        parse_haiku_response("not json at all, just text")


# ---------------------------------------------------------------------------
# ScoringService 整合（用 in-memory SQLite）
# ---------------------------------------------------------------------------


def _persist_post(session, post: CandidatePost) -> CandidatePost:
    session.add(post)
    session.flush()
    return post


def test_service_rules_pass_writes_three_records(session):
    post = _persist_post(session, _make_post())
    svc = ScoringService(scorer=FakeScorer())
    out = svc.score_candidate(session, post, now=NOW)

    assert out.rules_passed
    assert out.haiku_verdict == "track"
    assert out.final_score is not None

    rows = session.scalars(
        select(ScoringRecord).where(ScoringRecord.candidate_post_id == post.id)
    ).all()
    stages = {r.stage for r in rows}
    assert stages == {"rules", "haiku", "final"}


def test_service_rules_fail_skips_haiku_call(session):
    post = _persist_post(session, _make_post(score=1, num_comments=0))
    scorer = FakeScorer()
    svc = ScoringService(scorer=scorer)
    out = svc.score_candidate(session, post, now=NOW)

    assert not out.rules_passed
    assert out.haiku_verdict is None
    assert out.final_score is None
    assert scorer.call_count == 0          # 沒打 Haiku，省 token

    # 仍寫三筆 row 便於後續查詢
    rows = session.scalars(
        select(ScoringRecord).where(ScoringRecord.candidate_post_id == post.id)
    ).all()
    assert len(rows) == 3
    haiku_row = next(r for r in rows if r.stage == "haiku")
    assert haiku_row.details.get("skipped_due_to_rules") is True


def test_service_haiku_failure_writes_error_row(session):
    post = _persist_post(session, _make_post())
    scorer = FakeScorer(raise_exc=ValueError("invalid JSON"))
    svc = ScoringService(scorer=scorer)
    out = svc.score_candidate(session, post, now=NOW)

    assert out.rules_passed
    assert out.haiku_verdict is None
    assert out.final_score is None
    assert out.error and "invalid JSON" in out.error

    rows = session.scalars(
        select(ScoringRecord).where(ScoringRecord.candidate_post_id == post.id)
    ).all()
    haiku_row = next(r for r in rows if r.stage == "haiku")
    assert haiku_row.passed is False
    assert "error" in haiku_row.details


def test_fetch_unscored_excludes_already_scored(session):
    a = _persist_post(session, _make_post(rid="aa1"))
    _persist_post(session, _make_post(rid="bb2"))
    svc = ScoringService(scorer=FakeScorer())
    svc.score_candidate(session, a, now=NOW)

    leftover = fetch_unscored(session, limit=10)
    assert [p.reddit_post_id for p in leftover] == ["bb2"]


def test_score_batch_handles_mixed_outcomes(session):
    # 用 stickied=True 確保 rules 失敗（與 real clock 無關）
    _persist_post(session, _make_post(rid="ok1", age_hours=12.0))
    _persist_post(
        session,
        _make_post(rid="bad1", age_hours=12.0, meta={"stickied": True}),
    )
    _persist_post(session, _make_post(rid="ok2", age_hours=12.0))

    svc = ScoringService(scorer=FakeScorer())
    outcomes = score_batch(session, svc, limit=10)
    assert len(outcomes) == 3
    # 兩篇過、一篇 rules fail
    assert sum(1 for o in outcomes if o.rules_passed) == 2
    assert sum(1 for o in outcomes if not o.rules_passed) == 1
