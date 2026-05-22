"""Scoring service — 三段式評分流水線。

對應 SCHEDULE.md M3.1–M3.5。流程：

    candidate → apply_hard_rules() ─┐
                                    ├─► combine_final() ─► scoring_records(stage=...)
                       Haiku score ─┘

每跑一篇 candidate 會寫 3 筆 scoring_records（stage in {rules, haiku, final}）。
若硬規則沒過，後兩筆都會 passed=False / score=None；Haiku 不會被呼叫，省 token。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ..llm.base import HaikuVerdict, LLMScorer
from ..models import CandidatePost, ScoringRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 硬規則（M3.1）
# ---------------------------------------------------------------------------

# 與企劃書 §4.2 表格一致；常數獨立宣告便於 M3.8 邊界測試。
MIN_VELOCITY = 5.0              # (ups + comments × 2) / age_hours
MAX_AUTHOR_KARMA = 10_000       # 素人輪廓上限
MIN_ACCOUNT_AGE_DAYS = 30       # 過濾水軍 / 新帳號
MIN_BODY_CHARS = 100            # title + selftext 合計
MAX_BODY_CHARS = 3_000

# 業配 / 公告黑名單字串（中英）
BLACKLIST_PATTERNS = (
    "業配", "合作邀請", "廣告", "團購",
    "sponsored", "ad partnership", "affiliate", "promo code",
)


CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


@dataclass
class HardRuleResult:
    """`apply_hard_rules` 的輸出。`passed` 進 scoring_records.passed；
    `details` 進 scoring_records.details 供日後 reproducibility 檢查。
    """

    passed: bool
    details: dict
    velocity: float | None = None      # 拿去 combine_final 算 final


def detect_lang(text: str) -> str:
    """極簡語言偵測：CJK 比例 ≥ 20% → zh，否則 en/other。

    M3 不引入 fasttext / langdetect 等重依賴。Discovery 已有 `lang_hint`
    從 subreddit 帶入；這裡只是貼文層級的二次校驗。
    """
    if not text:
        return "unknown"
    cjk = len(CJK_RE.findall(text))
    ascii_letters = len(ASCII_LETTER_RE.findall(text))
    total = cjk + ascii_letters
    if total == 0:
        return "unknown"
    if cjk / total >= 0.20:
        return "zh"
    return "en"


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """SQLite DateTime(timezone=True) 載回會掉 tzinfo；統一補成 UTC。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _age_hours(post: CandidatePost, now: datetime | None = None) -> float | None:
    """以 posted_at 為準、fallback 到 discovered_at。"""
    ref = _ensure_utc(post.posted_at or post.discovered_at)
    if ref is None:
        return None
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    delta = (now - ref).total_seconds() / 3600.0
    return max(delta, 0.01)        # 避免除以 0


def _interaction_velocity(post: CandidatePost, age_h: float | None) -> float | None:
    if age_h is None or age_h <= 0:
        return None
    ups = post.initial_score or 0
    comments = post.initial_num_comments or 0
    return (ups + comments * 2) / age_h


def apply_hard_rules(
    post: CandidatePost,
    *,
    now: datetime | None = None,
) -> HardRuleResult:
    """六條硬規則。任何一條 fail → passed=False。

    對 author_karma / author_created_utc 採「未知就放行」策略：public JSON
    scraper 拿不到這兩個欄位，硬卡會把幾乎所有 candidate 擋掉。
    """
    now = now or datetime.now(timezone.utc)
    details: dict = {}
    fail_reasons: list[str] = []

    # 1. 互動速度
    age_h = _age_hours(post, now=now)
    velocity = _interaction_velocity(post, age_h)
    details["age_hours"] = round(age_h, 3) if age_h is not None else None
    details["velocity"] = round(velocity, 3) if velocity is not None else None
    if velocity is None:
        fail_reasons.append("missing_posted_at")
    elif velocity < MIN_VELOCITY:
        fail_reasons.append(f"velocity<{MIN_VELOCITY}")

    # 2. 作者 karma（None → 放行）
    karma = post.author_karma
    details["author_karma"] = karma
    if karma is not None and karma >= MAX_AUTHOR_KARMA:
        fail_reasons.append(f"karma>={MAX_AUTHOR_KARMA}")

    # 3. 帳號年齡（None → 放行）
    created = _ensure_utc(post.author_created_utc)
    if created is not None:
        age_days = (now - created).days
        details["account_age_days"] = age_days
        if age_days < MIN_ACCOUNT_AGE_DAYS:
            fail_reasons.append(f"account_age<{MIN_ACCOUNT_AGE_DAYS}d")

    # 4. 文字長度
    body = ((post.title or "") + " " + (post.selftext or "")).strip()
    body_len = len(body)
    details["body_len"] = body_len
    if body_len < MIN_BODY_CHARS:
        fail_reasons.append(f"body_len<{MIN_BODY_CHARS}")
    elif body_len > MAX_BODY_CHARS:
        fail_reasons.append(f"body_len>{MAX_BODY_CHARS}")

    # 5. 語言（zh / en 皆 OK，unknown / other 過濾）
    lang = post.lang or detect_lang(body)
    details["lang"] = lang
    if lang not in ("zh", "en"):
        fail_reasons.append(f"lang={lang}")

    # 6. 黑名單字串 + stickied / distinguished
    lower = body.lower()
    hit = next((pat for pat in BLACKLIST_PATTERNS if pat in body or pat in lower), None)
    if hit:
        fail_reasons.append(f"blacklist:{hit}")
    meta = post.meta_json or {}
    if meta.get("stickied"):
        fail_reasons.append("stickied")
    if meta.get("distinguished") == "moderator":
        fail_reasons.append("distinguished=mod")

    details["fail_reasons"] = fail_reasons
    passed = not fail_reasons
    return HardRuleResult(passed=passed, details=details, velocity=velocity)


# ---------------------------------------------------------------------------
# 加權合併（M3.4）
# ---------------------------------------------------------------------------

# velocity 從未上界化 → 用 sigmoid-ish 正規化進 [0, 1]
VELOCITY_REFERENCE = 50.0     # 互動速度達 50 → 對應 ~0.83；100 → 0.95


def normalize_velocity(velocity: float | None) -> float:
    if velocity is None or velocity <= 0:
        return 0.0
    return velocity / (velocity + VELOCITY_REFERENCE / 5.0)


def combine_final(
    velocity: float | None,
    haiku: HaikuVerdict | None,
) -> float | None:
    """final_score = 0.4·v + 0.3·s + 0.2·g + 0.1·n

    s = (story_potential + emotional_pull) / 2
    Haiku 為 None（rules 沒過或評分失敗）→ 回 None。
    """
    if haiku is None:
        return None
    v = normalize_velocity(velocity)
    s = (haiku.story_potential + haiku.emotional_pull) / 2.0
    g = haiku.grassroots
    n = haiku.novelty
    return round(0.4 * v + 0.3 * s + 0.2 * g + 0.1 * n, 4)


# ---------------------------------------------------------------------------
# Scoring service (M3.5)
# ---------------------------------------------------------------------------


@dataclass
class ScoringOutcome:
    candidate_id: int
    rules_passed: bool
    haiku_verdict: str | None       # 'track' / 'skip' / None（沒過 rules）
    final_score: float | None
    skipped: bool = False           # 已評過 → 略過
    error: str | None = None

    # 給 scheduler 報告用
    rules_record_id: int | None = None
    haiku_record_id: int | None = None
    final_record_id: int | None = None


class ScoringService:
    """rules → haiku → final 三段式。

    呼叫方應保證 caller 自己管 commit；本 service 只 add + flush，讓 batch
    作業可以一筆失敗不影響其他（外層 try/except + savepoint）。
    """

    def __init__(self, scorer: LLMScorer):
        self.scorer = scorer

    def score_candidate(
        self,
        session: Session,
        post: CandidatePost,
        *,
        now: datetime | None = None,
    ) -> ScoringOutcome:
        rules = apply_hard_rules(post, now=now)
        rules_record = ScoringRecord(
            candidate_post_id=post.id,
            stage="rules",
            passed=rules.passed,
            score=rules.velocity,
            details=rules.details,
        )
        session.add(rules_record)
        session.flush()

        if not rules.passed:
            # 為了之後查得到「曾經評過、結果是沒過」，仍寫 haiku / final 空 row
            haiku_record = ScoringRecord(
                candidate_post_id=post.id,
                stage="haiku",
                passed=False,
                score=None,
                details={"skipped_due_to_rules": True},
            )
            final_record = ScoringRecord(
                candidate_post_id=post.id,
                stage="final",
                passed=False,
                score=None,
                details={"skipped_due_to_rules": True},
            )
            session.add_all([haiku_record, final_record])
            session.flush()
            return ScoringOutcome(
                candidate_id=post.id,
                rules_passed=False,
                haiku_verdict=None,
                final_score=None,
                rules_record_id=rules_record.id,
                haiku_record_id=haiku_record.id,
                final_record_id=final_record.id,
            )

        # Haiku 五軸
        try:
            verdict = self.scorer.score(post)
        except Exception as e:  # noqa: BLE001
            logger.error("Haiku scoring failed for candidate %s: %s", post.id, e)
            haiku_record = ScoringRecord(
                candidate_post_id=post.id,
                stage="haiku",
                passed=False,
                score=None,
                details={"error": str(e)[:200]},
            )
            final_record = ScoringRecord(
                candidate_post_id=post.id,
                stage="final",
                passed=False,
                score=None,
                details={"error": "haiku_failed"},
            )
            session.add_all([haiku_record, final_record])
            session.flush()
            return ScoringOutcome(
                candidate_id=post.id,
                rules_passed=True,
                haiku_verdict=None,
                final_score=None,
                error=str(e)[:200],
                rules_record_id=rules_record.id,
                haiku_record_id=haiku_record.id,
                final_record_id=final_record.id,
            )

        haiku_record = ScoringRecord(
            candidate_post_id=post.id,
            stage="haiku",
            passed=(verdict.verdict == "track"),
            score=(verdict.story_potential + verdict.emotional_pull) / 2.0,
            details={
                "story_potential": verdict.story_potential,
                "emotional_pull": verdict.emotional_pull,
                "grassroots": verdict.grassroots,
                "novelty": verdict.novelty,
                "authenticity": verdict.authenticity,
                "verdict": verdict.verdict,
                "reason": verdict.reason,
            },
            cost_usd=Decimal(str(verdict.cost_usd)) if verdict.cost_usd else None,
        )
        session.add(haiku_record)
        session.flush()

        final_score = combine_final(rules.velocity, verdict)
        final_record = ScoringRecord(
            candidate_post_id=post.id,
            stage="final",
            passed=(verdict.verdict == "track"),
            score=final_score,
            details={
                "weights": {"velocity": 0.4, "semantic": 0.3, "grassroots": 0.2, "novelty": 0.1},
                "velocity_normalized": normalize_velocity(rules.velocity),
            },
        )
        session.add(final_record)
        session.flush()

        return ScoringOutcome(
            candidate_id=post.id,
            rules_passed=True,
            haiku_verdict=verdict.verdict,
            final_score=final_score,
            rules_record_id=rules_record.id,
            haiku_record_id=haiku_record.id,
            final_record_id=final_record.id,
        )


# ---------------------------------------------------------------------------
# Batch helpers（給 scheduler / scripts 用）
# ---------------------------------------------------------------------------


def fetch_unscored(session: Session, *, limit: int = 50) -> list[CandidatePost]:
    """挑出尚未有 stage='rules' scoring_records 的 candidate（先進先評）。"""
    scored_subq = (
        select(ScoringRecord.candidate_post_id)
        .where(ScoringRecord.stage == "rules")
        .scalar_subquery()
    )
    stmt = (
        select(CandidatePost)
        .where(~CandidatePost.id.in_(scored_subq))
        .order_by(CandidatePost.discovered_at.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def score_batch(
    session: Session,
    service: ScoringService,
    *,
    limit: int = 50,
    now: datetime | None = None,
) -> list[ScoringOutcome]:
    """掃一批未評分的 candidate，逐筆走 ScoringService。"""
    posts = fetch_unscored(session, limit=limit)
    outcomes: list[ScoringOutcome] = []
    for p in posts:
        try:
            outcomes.append(service.score_candidate(session, p, now=now))
        except Exception as e:  # noqa: BLE001
            logger.exception("score_candidate(%s) hard fail", p.id)
            outcomes.append(
                ScoringOutcome(
                    candidate_id=p.id,
                    rules_passed=False,
                    haiku_verdict=None,
                    final_score=None,
                    error=str(e)[:200],
                )
            )
    return outcomes


__all__ = [
    "BLACKLIST_PATTERNS",
    "HardRuleResult",
    "MAX_AUTHOR_KARMA",
    "MAX_BODY_CHARS",
    "MIN_ACCOUNT_AGE_DAYS",
    "MIN_BODY_CHARS",
    "MIN_VELOCITY",
    "ScoringOutcome",
    "ScoringService",
    "VELOCITY_REFERENCE",
    "apply_hard_rules",
    "combine_final",
    "detect_lang",
    "fetch_unscored",
    "normalize_velocity",
    "score_batch",
]
