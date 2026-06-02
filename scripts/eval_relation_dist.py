"""M7.4 — 四類 related_posts 的分布 (SCHEDULE.md 7.4)。

四類:
    author_followup — 作者後續發文
    author_reply    — 原作者在留言區回覆 (OP reply)
    hot_reply       — 留言區高熱度回覆
    crosspost       — 被轉貼到其他 sub

每類顯示:
    count / milestone count / milestone rate / avg relevance / 每篇 tracked 平均

切中英對照 (用 tracked → candidate.lang).

用法:
    uv run python scripts/eval_relation_dist.py
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
    RelatedPost,
    TrackedPost,
)


RELATION_TYPES = ["author_followup", "author_reply", "hot_reply", "crosspost"]


def _pct(num: int, den: int) -> str:
    return f"{num / den * 100:.1f}%" if den else "—"


def _print_dist(title: str, rows: dict[str, list[RelatedPost]], n_tracked: int) -> None:
    print(f"\n### {title}\n")
    print("| relation | count | milestone | milestone rate | avg relevance | 每 tracked 篇均 |")
    print("|---|---:|---:|---:|---:|---:|")
    for rt in RELATION_TYPES:
        items = rows.get(rt, [])
        ms = [r for r in items if r.is_milestone]
        scores = [r.relevance_score for r in items if r.relevance_score is not None]
        avg_score = f"{statistics.mean(scores):.2f}" if scores else "—"
        per_tracked = f"{len(items) / n_tracked:.2f}" if n_tracked else "—"
        print(
            f"| {rt} | {len(items)} | {len(ms)} | "
            f"{_pct(len(ms), len(items))} | {avg_score} | {per_tracked} |"
        )
    print(
        f"| **TOTAL** | **{sum(len(rows.get(rt, [])) for rt in RELATION_TYPES)}** | "
        f"**{sum(1 for rt in RELATION_TYPES for r in rows.get(rt, []) if r.is_milestone)}** "
        f"| | | |"
    )


def main() -> None:
    with session_scope() as s:
        all_rels = s.scalars(select(RelatedPost)).all()
        if not all_rels:
            print("沒有 related_posts。")
            return

        # tracked → lang lookup
        tracked_lang_rows = s.execute(
            select(TrackedPost.id, CandidatePost.lang)
            .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
        ).all()
        lang_by_tid = {tid: (ln or "unknown") for tid, ln in tracked_lang_rows}
        n_tracked = len(lang_by_tid)

        # 整體
        all_by_type: dict[str, list[RelatedPost]] = defaultdict(list)
        for r in all_rels:
            all_by_type[r.relation_type].append(r)

        print(f"# M7.4 四類 related 分布 ({len(all_rels)} 筆 / {n_tracked} 篇 tracked)\n")
        _print_dist("整體", all_by_type, n_tracked)

        # by lang
        lang_groups: dict[str, dict[str, list[RelatedPost]]] = defaultdict(
            lambda: defaultdict(list)
        )
        n_tracked_by_lang: dict[str, int] = defaultdict(int)
        for tid, ln in lang_by_tid.items():
            n_tracked_by_lang[ln] += 1
        for r in all_rels:
            ln = lang_by_tid.get(r.tracked_post_id, "unknown")
            lang_groups[ln][r.relation_type].append(r)
        for ln in sorted(lang_groups):
            _print_dist(
                f"lang = {ln} ({n_tracked_by_lang[ln]} 篇 tracked)",
                lang_groups[ln],
                n_tracked_by_lang[ln],
            )

        # milestone 距離原貼時間分布 (給 v4 crosspost 賣點分析用)
        print("\n### Milestone 觸發時間 (relative to discovery)\n")
        ms_rels = [r for r in all_rels if r.is_milestone]
        if not ms_rels:
            print("沒有 milestone。")
            return
        print("| relation | n | discovered_at vs posted_at avg | sample content (60 chr) |")
        print("|---|---:|---|---|")
        for rt in RELATION_TYPES:
            items = [r for r in ms_rels if r.relation_type == rt]
            if not items:
                continue
            # 略過時間 delta — 兩個欄位常常缺一個, 直接列頭兩筆 sample
            sample = (items[0].content or "")[:60].replace("|", "/")
            print(f"| {rt} | {len(items)} | (略) | {sample} |")


if __name__ == "__main__":
    main()
