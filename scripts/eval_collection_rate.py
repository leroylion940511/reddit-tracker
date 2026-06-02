"""M7.1 — 收藏率評估 (SCHEDULE.md 7.1)。

定義:
    收藏率 = 「被推送過且至少有一筆 feedback.action='collect' 的 candidate」/
            「被推送過的 candidate」

每個 candidate 在 daily_pushes 內可能出現多次 (同篇被多日推送 — UniqueConstraint
是 (push_date, candidate_post_id), 所以 distinct candidate 才是分母).

切分:
    - 全體
    - 按 push_type (already_hot / early_bet / breaking)
    - 按 lang (zh / en / unknown)
    - 按時段 (pre-Plan-C: ≤ 2026-05-28 / Plan-C: ≥ 2026-05-29)

用法:
    uv run python scripts/eval_collection_rate.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import CandidatePost, DailyPush, Feedback  # noqa: E402

PLAN_C_START = date(2026, 5, 29)


def _phase(d: date) -> str:
    return "Plan-C (RSS)" if d >= PLAN_C_START else "pre-Plan-C (JSON)"


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({numerator / denominator * 100:.1f}%)" \
        if denominator else f"{numerator}/0 (—)"


def _print_table(title: str, rows: list[tuple[str, int, int]]) -> None:
    """rows: [(label, collected, pushed)]"""
    print(f"\n### {title}\n")
    print("| 分類 | collect/push | 命中率 |")
    print("|---|---:|---:|")
    for label, c, p in rows:
        pct = f"{c / p * 100:.1f}%" if p else "—"
        print(f"| {label} | {c}/{p} | {pct} |")


def main() -> None:
    with session_scope() as s:
        # 抓所有 (push, candidate) pair
        pushes = s.execute(
            select(
                DailyPush.id,
                DailyPush.push_date,
                DailyPush.push_type,
                DailyPush.candidate_post_id,
                CandidatePost.lang,
                CandidatePost.subreddit,
            ).join(CandidatePost, CandidatePost.id == DailyPush.candidate_post_id)
        ).all()

        # 抓所有 collect feedback 的 candidate_id (set)
        collected_cids: set[int] = set(
            s.scalars(
                select(Feedback.candidate_post_id).where(Feedback.action == "collect")
            ).all()
        )

        if not pushes:
            print("沒有 daily_pushes 紀錄。")
            return

        # 分母用 (push_date, candidate_id) 不重複 (UniqueConstraint 保證已 unique)
        # 整體
        total_pushed = len(pushes)
        total_collected = sum(
            1 for p in pushes if p.candidate_post_id in collected_cids
        )

        print(f"# M7.1 收藏率 baseline ({len(pushes)} 筆 push)\n")
        print(
            f"**全體**：{_rate(total_collected, total_pushed)}　"
            f"（unique candidates={len({p.candidate_post_id for p in pushes})}）"
        )

        # by push_type
        by_type: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        for p in pushes:
            c, t = by_type[p.push_type]
            hit = 1 if p.candidate_post_id in collected_cids else 0
            by_type[p.push_type] = (c + hit, t + 1)
        rows = [
            (label, c, t) for label, (c, t) in sorted(by_type.items())
        ]
        _print_table("按 push_type", rows)

        # by lang
        by_lang: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        for p in pushes:
            key = p.lang or "unknown"
            c, t = by_lang[key]
            hit = 1 if p.candidate_post_id in collected_cids else 0
            by_lang[key] = (c + hit, t + 1)
        _print_table(
            "按 lang", [(k, c, t) for k, (c, t) in sorted(by_lang.items())]
        )

        # by phase
        by_phase: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        for p in pushes:
            key = _phase(p.push_date)
            c, t = by_phase[key]
            hit = 1 if p.candidate_post_id in collected_cids else 0
            by_phase[key] = (c + hit, t + 1)
        _print_table(
            "按時段 (Plan C 切換點 2026-05-29)",
            [(k, c, t) for k, (c, t) in sorted(by_phase.items())],
        )

        # by push_type × phase (交叉)
        by_type_phase: dict[tuple[str, str], tuple[int, int]] = defaultdict(
            lambda: (0, 0)
        )
        for p in pushes:
            key = (p.push_type, _phase(p.push_date))
            c, t = by_type_phase[key]
            hit = 1 if p.candidate_post_id in collected_cids else 0
            by_type_phase[key] = (c + hit, t + 1)
        _print_table(
            "push_type × 時段",
            [
                (f"{pt} / {ph}", c, t)
                for (pt, ph), (c, t) in sorted(by_type_phase.items())
            ],
        )

        # by subreddit (只列被推超過 1 次的)
        by_sub: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        for p in pushes:
            c, t = by_sub[p.subreddit]
            hit = 1 if p.candidate_post_id in collected_cids else 0
            by_sub[p.subreddit] = (c + hit, t + 1)
        sub_rows = sorted(
            ((sub, c, t) for sub, (c, t) in by_sub.items() if t >= 1),
            key=lambda r: (-r[2], -r[1], r[0]),
        )
        _print_table("按 subreddit", [(f"r/{s}", c, t) for s, c, t in sub_rows])

        # 給後續分析用：所有 dislike 過的 candidate
        dislike_cids: set[int] = set(
            s.scalars(
                select(Feedback.candidate_post_id).where(Feedback.action == "dislike")
            ).all()
        )
        print(f"\n_附註_：dislike 累積 {len(dislike_cids)} 個 unique candidate；M7.6 prompt retune 時細看其特徵。")


if __name__ == "__main__":
    main()
