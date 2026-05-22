"""Daily feed picker — 從評分過的 candidate 挑出當日推送清單。

對應 SCHEDULE.md M4.1–M4.3：

    pick_daily_top5()  → 3 already_hot（age ≥ 6h, velocity 排序）
                       + 2 early_bet（age < 3h, semantic 排序）
    check_breaking()   → age < 1h + velocity top 1% + verdict=track + semantic > 0.85
    record_pushes()    → 寫 daily_pushes，靠 UniqueConstraint(push_date, candidate_post_id)
                          防止同篇重推

評分資料從 `scoring_records` 取：
- velocity = stage='rules' 的 score 欄位
- semantic = stage='haiku' 的 score 欄位（= (story+emotional)/2）
- final_score = stage='final' 的 score；passed=True 才入選池
- verdict = stage='haiku' 的 details["verdict"]

M4 不負責實際送 Telegram；那是 M4.4–4.5。本層只算 + 寫 row。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CandidatePost, DailyPush, ScoringRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 預設常數（對應企劃書 §4.3 + §4.4）
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_HOURS = 24
ALREADY_HOT_COUNT = 3
ALREADY_HOT_MIN_AGE_H = 6.0
EARLY_BET_COUNT = 2
EARLY_BET_MAX_AGE_H = 3.0

BREAKING_MAX_AGE_H = 1.0
BREAKING_VELOCITY_PERCENTILE = 0.01      # top 1%
BREAKING_MIN_SEMANTIC = 0.85
BREAKING_DAILY_CAP = 2


# ---------------------------------------------------------------------------
# 資料結構
# ---------------------------------------------------------------------------


@dataclass
class FeedCandidate:
    """一個進入候選池的 candidate 連同它的評分快照。"""

    candidate: CandidatePost
    age_hours: float | None
    velocity: float | None
    semantic: float | None
    final_score: float | None
    verdict: str | None             # 'track' / 'skip' / None


@dataclass
class FeedPick:
    """從候選池挑出的一筆推送。"""

    candidate_post_id: int
    candidate: CandidatePost
    push_type: str                  # 'already_hot' / 'early_bet' / 'breaking'
    rank: int                       # 同 push_type 內 1-based
    velocity: float | None
    semantic: float | None
    final_score: float | None


@dataclass
class PushWriteStat:
    inserted: int
    skipped_dupe: int               # 同 (push_date, candidate_post_id) 已存在


# ---------------------------------------------------------------------------
# 共用 helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """SQLite DateTime(timezone=True) 載回會掉 tzinfo；統一補 UTC（與 scoring.py 一致）。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _age_hours(post: CandidatePost, now: datetime) -> float | None:
    ref = _ensure_utc(post.posted_at or post.discovered_at)
    if ref is None:
        return None
    delta = (now - ref).total_seconds() / 3600.0
    return max(delta, 0.01)


def _latest_scoring_by_stage(
    session: Session, candidate_ids: list[int]
) -> dict[tuple[int, str], ScoringRecord]:
    """每個 (candidate_id, stage) 抓出最新一筆 ScoringRecord。

    M3 流程下一個 candidate 通常只評一次（fetch_unscored 會排除已評）。
    但若日後 re-score 出現多筆，這裡用 max(id) 取最新即可。
    """
    if not candidate_ids:
        return {}
    rows = session.scalars(
        select(ScoringRecord).where(ScoringRecord.candidate_post_id.in_(candidate_ids))
    ).all()
    latest: dict[tuple[int, str], ScoringRecord] = {}
    for r in rows:
        key = (r.candidate_post_id, r.stage)
        prev = latest.get(key)
        if prev is None or (r.id or 0) > (prev.id or 0):
            latest[key] = r
    return latest


def _load_pool(
    session: Session,
    *,
    now: datetime,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[FeedCandidate]:
    """過去 window_hours 內、最終分數已產生且通過的候選池。"""
    cutoff = now - timedelta(hours=window_hours)
    posted = func.coalesce(CandidatePost.posted_at, CandidatePost.discovered_at)
    candidates = session.scalars(
        select(CandidatePost).where(posted >= cutoff)
    ).all()
    if not candidates:
        return []

    latest = _latest_scoring_by_stage(session, [c.id for c in candidates])
    pool: list[FeedCandidate] = []
    for c in candidates:
        final_r = latest.get((c.id, "final"))
        if final_r is None or final_r.score is None or not final_r.passed:
            continue                # 未評分 / 評分未過 → 不入池
        rules_r = latest.get((c.id, "rules"))
        haiku_r = latest.get((c.id, "haiku"))
        verdict = None
        if haiku_r and haiku_r.details:
            verdict = haiku_r.details.get("verdict")
        pool.append(
            FeedCandidate(
                candidate=c,
                age_hours=_age_hours(c, now),
                velocity=rules_r.score if rules_r else None,
                semantic=haiku_r.score if haiku_r else None,
                final_score=final_r.score,
                verdict=verdict,
            )
        )
    return pool


def _to_pick(fc: FeedCandidate, *, push_type: str, rank: int) -> FeedPick:
    return FeedPick(
        candidate_post_id=fc.candidate.id,
        candidate=fc.candidate,
        push_type=push_type,
        rank=rank,
        velocity=fc.velocity,
        semantic=fc.semantic,
        final_score=fc.final_score,
    )


# ---------------------------------------------------------------------------
# M4.1 — pick_daily_top5
# ---------------------------------------------------------------------------


def pick_daily_top5(
    session: Session,
    *,
    now: datetime | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    already_hot_count: int = ALREADY_HOT_COUNT,
    already_hot_min_age_h: float = ALREADY_HOT_MIN_AGE_H,
    early_bet_count: int = EARLY_BET_COUNT,
    early_bet_max_age_h: float = EARLY_BET_MAX_AGE_H,
) -> list[FeedPick]:
    """挑 3 已爆 + 2 早期。

    Already hot 桶：age ≥ 6h、velocity 由大到小取 N。
    Early bet 桶：age < 3h、semantic 由大到小取 M，且不能與已選桶重複。
    缺額不補（5 篇是上限不是下限）— 若兩桶各只有 1 篇，回傳就是 2 筆。
    """
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    pool = _load_pool(session, now=now, window_hours=window_hours)
    if not pool:
        return []

    hot = [
        p for p in pool
        if p.age_hours is not None
        and p.age_hours >= already_hot_min_age_h
        and p.velocity is not None
    ]
    hot.sort(key=lambda p: p.velocity, reverse=True)  # type: ignore[arg-type]
    hot_picks = hot[:already_hot_count]
    chosen_ids = {p.candidate.id for p in hot_picks}

    early = [
        p for p in pool
        if p.candidate.id not in chosen_ids
        and p.age_hours is not None
        and p.age_hours < early_bet_max_age_h
        and p.semantic is not None
    ]
    early.sort(key=lambda p: p.semantic, reverse=True)  # type: ignore[arg-type]
    early_picks = early[:early_bet_count]

    picks: list[FeedPick] = []
    for i, fc in enumerate(hot_picks, start=1):
        picks.append(_to_pick(fc, push_type="already_hot", rank=i))
    for i, fc in enumerate(early_picks, start=1):
        picks.append(_to_pick(fc, push_type="early_bet", rank=i))
    return picks


# ---------------------------------------------------------------------------
# M4.2 — check_breaking
# ---------------------------------------------------------------------------


def _velocity_percentile_threshold(
    velocities: list[float], top_fraction: float
) -> float | None:
    """回傳 velocity 池中對應 top_fraction 比例（例如 0.01 → top 1%）的門檻值。

    用 ceil(N · fraction) 計位置，最少 1 筆。所以小樣本（< 100）時 top 1% = 最高 1 筆。
    """
    if not velocities:
        return None
    sorted_desc = sorted(velocities, reverse=True)
    k = max(1, math.ceil(len(sorted_desc) * top_fraction))
    return sorted_desc[k - 1]


def check_breaking(
    session: Session,
    *,
    now: datetime | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    max_age_h: float = BREAKING_MAX_AGE_H,
    velocity_percentile: float = BREAKING_VELOCITY_PERCENTILE,
    min_semantic: float = BREAKING_MIN_SEMANTIC,
    daily_cap: int = BREAKING_DAILY_CAP,
) -> list[FeedPick]:
    """即時破例。所有條件須同時成立：

    - age < 1h
    - velocity ≥ 當前候選池 velocity 的 top 1% 門檻
    - haiku verdict == 'track'
    - semantic > 0.85

    每日 push_type='breaking' 上限 daily_cap（預設 2），且 (push_date, candidate)
    已存在不重推。
    """
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    pool = _load_pool(session, now=now, window_hours=window_hours)
    if not pool:
        return []

    today = now.date()
    breaking_today = session.scalar(
        select(func.count(DailyPush.id)).where(
            DailyPush.push_date == today,
            DailyPush.push_type == "breaking",
        )
    ) or 0
    quota_left = daily_cap - int(breaking_today)
    if quota_left <= 0:
        return []

    velocities = [p.velocity for p in pool if p.velocity is not None]
    threshold = _velocity_percentile_threshold(velocities, velocity_percentile)
    if threshold is None:
        return []

    already_today_ids: set[int] = set(
        session.scalars(
            select(DailyPush.candidate_post_id).where(DailyPush.push_date == today)
        ).all()
    )

    breaking = [
        p for p in pool
        if p.candidate.id not in already_today_ids
        and p.age_hours is not None and p.age_hours < max_age_h
        and p.velocity is not None and p.velocity >= threshold
        and p.verdict == "track"
        and p.semantic is not None and p.semantic > min_semantic
    ]
    if not breaking:
        return []

    breaking.sort(key=lambda p: p.velocity, reverse=True)  # type: ignore[arg-type]
    chosen = breaking[:quota_left]
    return [_to_pick(fc, push_type="breaking", rank=i) for i, fc in enumerate(chosen, start=1)]


# ---------------------------------------------------------------------------
# M4.3 — record_pushes
# ---------------------------------------------------------------------------


def record_pushes(
    session: Session,
    picks: list[FeedPick],
    *,
    push_date: date | None = None,
    now: datetime | None = None,
) -> PushWriteStat:
    """把 picks 寫進 daily_pushes，靠 (push_date, candidate_post_id) UNIQUE 防重複。

    `pushed_at` 留 None — 真正送到 Telegram 的時刻由 bot 那層回寫（M4.4–4.5）。
    回傳實際寫入 / 略過的筆數。caller 負責 commit。
    """
    if not picks:
        return PushWriteStat(inserted=0, skipped_dupe=0)

    if push_date is None:
        now = _ensure_utc(now) or datetime.now(timezone.utc)
        push_date = now.date()

    cand_ids = [p.candidate_post_id for p in picks]
    existing_ids: set[int] = set(
        session.scalars(
            select(DailyPush.candidate_post_id).where(
                DailyPush.push_date == push_date,
                DailyPush.candidate_post_id.in_(cand_ids),
            )
        ).all()
    )

    inserted = 0
    dupe = 0
    seen_in_batch: set[int] = set()
    for p in picks:
        if p.candidate_post_id in existing_ids or p.candidate_post_id in seen_in_batch:
            dupe += 1
            continue
        session.add(
            DailyPush(
                push_date=push_date,
                candidate_post_id=p.candidate_post_id,
                push_type=p.push_type,
                rank=p.rank,
            )
        )
        seen_in_batch.add(p.candidate_post_id)
        inserted += 1

    session.flush()
    return PushWriteStat(inserted=inserted, skipped_dupe=dupe)


__all__ = [
    "ALREADY_HOT_COUNT",
    "ALREADY_HOT_MIN_AGE_H",
    "BREAKING_DAILY_CAP",
    "BREAKING_MAX_AGE_H",
    "BREAKING_MIN_SEMANTIC",
    "BREAKING_VELOCITY_PERCENTILE",
    "DEFAULT_WINDOW_HOURS",
    "EARLY_BET_COUNT",
    "EARLY_BET_MAX_AGE_H",
    "FeedCandidate",
    "FeedPick",
    "PushWriteStat",
    "check_breaking",
    "pick_daily_top5",
    "record_pushes",
]
