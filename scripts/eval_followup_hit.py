"""M7.2 — 後續命中率評估 (SCHEDULE.md 7.2)。

定義:
    related-hit  = N(tracked.has any related_post) / N(tracked)
    milestone-hit = N(tracked.has any milestone) / N(tracked)
    per-tracked 平均/中位數 related count 與 milestone count

切分:
    - 全體 (含 active + archived)
    - 按 lang
    - 按 status (active / archived)
    - 按 push_type 來源 (從 candidate.daily_pushes 反推第一個 push_type)

用法:
    uv run python scripts/eval_followup_hit.py
"""

from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import (  # noqa: E402
    CandidatePost,
    DailyPush,
    RelatedPost,
    TrackedPost,
)


def _summary(label: str, counts: list[int], ms_counts: list[int]) -> str:
    n = len(counts)
    hit = sum(1 for c in counts if c > 0)
    ms_hit = sum(1 for c in ms_counts if c > 0)
    if n == 0:
        return f"| {label} | 0 | — | — | — | — |"
    return (
        f"| {label} | {n} | "
        f"{hit}/{n} ({hit / n * 100:.0f}%) | "
        f"{ms_hit}/{n} ({ms_hit / n * 100:.0f}%) | "
        f"{statistics.mean(counts):.1f} (中位 {statistics.median(counts):.0f}) | "
        f"{statistics.mean(ms_counts):.1f} (中位 {statistics.median(ms_counts):.0f}) |"
    )


def _print_table(title: str, groups: dict[str, tuple[list[int], list[int]]]) -> None:
    print(f"\n### {title}\n")
    print("| 分類 | N | related-hit | milestone-hit | avg related/篇 | avg milestone/篇 |")
    print("|---|---:|---:|---:|---:|---:|")
    for label, (counts, ms_counts) in groups.items():
        print(_summary(label, counts, ms_counts))


def main() -> None:
    with session_scope() as s:
        tracked_rows = s.execute(
            select(TrackedPost, CandidatePost)
            .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
        ).all()
        if not tracked_rows:
            print("沒有 tracked_posts。")
            return

        tracked_ids = [t.id for t, _ in tracked_rows]

        # related / milestone counts per tracked
        rel_counts_raw = s.execute(
            select(
                RelatedPost.tracked_post_id,
                RelatedPost.is_milestone,
            ).where(RelatedPost.tracked_post_id.in_(tracked_ids))
        ).all()
        rel_total: dict[int, int] = defaultdict(int)
        ms_total: dict[int, int] = defaultdict(int)
        for tid, is_ms in rel_counts_raw:
            rel_total[tid] += 1
            if is_ms:
                ms_total[tid] += 1

        # 從 daily_pushes 反推每篇 tracked 來自的第一個 push_type
        push_types_raw = s.execute(
            select(DailyPush.candidate_post_id, DailyPush.push_type, DailyPush.push_date)
            .order_by(DailyPush.push_date.asc())
        ).all()
        push_type_by_cand: dict[int, str] = {}
        for cid, ptype, _ in push_types_raw:
            push_type_by_cand.setdefault(cid, ptype)

        # 整體
        all_rel = [rel_total[t.id] for t, _ in tracked_rows]
        all_ms = [ms_total[t.id] for t, _ in tracked_rows]
        print(f"# M7.2 後續命中率 ({len(tracked_rows)} 篇 tracked)\n")
        _print_table("全體", {"all": (all_rel, all_ms)})

        # by lang
        by_lang_rel: dict[str, list[int]] = defaultdict(list)
        by_lang_ms: dict[str, list[int]] = defaultdict(list)
        for t, c in tracked_rows:
            key = c.lang or "unknown"
            by_lang_rel[key].append(rel_total[t.id])
            by_lang_ms[key].append(ms_total[t.id])
        _print_table(
            "按 lang",
            {k: (by_lang_rel[k], by_lang_ms[k]) for k in sorted(by_lang_rel)},
        )

        # by status
        by_status_rel: dict[str, list[int]] = defaultdict(list)
        by_status_ms: dict[str, list[int]] = defaultdict(list)
        for t, _ in tracked_rows:
            by_status_rel[t.status].append(rel_total[t.id])
            by_status_ms[t.status].append(ms_total[t.id])
        _print_table(
            "按 status",
            {k: (by_status_rel[k], by_status_ms[k]) for k in sorted(by_status_rel)},
        )

        # by push_type (來源)
        by_pt_rel: dict[str, list[int]] = defaultdict(list)
        by_pt_ms: dict[str, list[int]] = defaultdict(list)
        for t, _ in tracked_rows:
            key = push_type_by_cand.get(t.candidate_post_id, "(unpushed)")
            by_pt_rel[key].append(rel_total[t.id])
            by_pt_ms[key].append(ms_total[t.id])
        _print_table(
            "按 push_type 來源",
            {k: (by_pt_rel[k], by_pt_ms[k]) for k in sorted(by_pt_rel)},
        )

        # 個別 tracked 明細
        print("\n### 個別 tracked 明細 (給人工複查用)\n")
        print("| tracked_id | r/sub | 標題 (60 chr) | status | related | milestone |")
        print("|---:|---|---|---|---:|---:|")
        for t, c in sorted(tracked_rows, key=lambda r: -rel_total[r[0].id]):
            title = (c.title or "(無標題)")[:60].replace("|", "/")
            print(
                f"| {t.id} | r/{c.subreddit} | {title} | {t.status} | "
                f"{rel_total[t.id]} | {ms_total[t.id]} |"
            )


if __name__ == "__main__":
    main()
