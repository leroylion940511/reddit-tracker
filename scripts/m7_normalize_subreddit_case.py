"""M7 retune #3 — 把既有 mixed-case subreddit 字串 normalize 成 lowercase。

背景:
    Reddit 對 /r/Taiwan 與 /r/taiwan 都 200，但 JSON 內 d["subreddit"] 兩種寫法
    都看過，造成 candidate_posts.subreddit 跟 subreddit_sources.name 大小寫不一致、
    無法 JOIN 統計。例:
        candidate_posts.subreddit: "taiwan"(381) + "Taiwan"(8) + "Taipei"(197) +
                                   "Updateme"(17)
        subreddit_sources.name:    "Taiwan" / "taipei" / "UpdateMe"
    PostPayload.__post_init__ 與 seeds_loader 已修，新資料一律 lowercase。
    此腳本一次性把舊資料也對齊。

預設 dry-run。加 --apply 才實際 UPDATE。

用法:
    uv run python scripts/m7_normalize_subreddit_case.py           # dry-run
    uv run python scripts/m7_normalize_subreddit_case.py --apply   # 真改
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, update  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import CandidatePost, SubredditSource  # noqa: E402


def main() -> None:
    apply = "--apply" in sys.argv

    with session_scope() as s:
        # --- subreddit_sources ---
        mixed_sources = s.scalars(
            select(SubredditSource).where(
                func.lower(SubredditSource.name) != SubredditSource.name
            )
        ).all()
        print("# Subreddit case normalization\n")
        print("## subreddit_sources (mixed-case rows)\n")
        if not mixed_sources:
            print("_no mixed-case rows_\n")
        else:
            print("| current name | → canonical | note |")
            print("|---|---|---|")
            for src in mixed_sources:
                canonical = src.name.lower()
                # 同時是否已有 lowercase row？若有，要合併計數
                dup = s.scalar(
                    select(SubredditSource).where(SubredditSource.name == canonical)
                )
                note = "rename" if dup is None else f"merge into existing id={dup.id}"
                print(f"| {src.name} | {canonical} | {note} |")

        # --- candidate_posts ---
        mixed_cand_rows = s.execute(
            select(CandidatePost.subreddit, func.count(CandidatePost.id))
            .where(func.lower(CandidatePost.subreddit) != CandidatePost.subreddit)
            .group_by(CandidatePost.subreddit)
        ).all()
        print("\n## candidate_posts (mixed-case rows)\n")
        if not mixed_cand_rows:
            print("_no mixed-case rows_\n")
        else:
            print("| current | → canonical | count |")
            print("|---|---|---:|")
            for sub, n in sorted(mixed_cand_rows, key=lambda r: -r[1]):
                print(f"| {sub} | {sub.lower()} | {n} |")

        total_cand = sum(n for _, n in mixed_cand_rows)
        print(
            f"\n**summary**: sources to fix = {len(mixed_sources)}, "
            f"candidate rows to fix = {total_cand}"
        )

        if not apply:
            print("\n_dry-run mode_: 加 --apply 才會實際 UPDATE。")
            return

        # === apply ===
        # subreddit_sources：逐筆處理，避免撞 UNIQUE 上的兩筆同 lowercase name
        rename_count = 0
        merge_count = 0
        for src in mixed_sources:
            canonical = src.name.lower()
            dup = s.scalar(
                select(SubredditSource).where(SubredditSource.name == canonical)
            )
            if dup is None:
                src.name = canonical
                rename_count += 1
            else:
                # 計數合進 dup，刪除大寫 row
                dup.total_candidates_yielded += src.total_candidates_yielded
                dup.total_promoted += src.total_promoted
                dup.total_collected += src.total_collected
                if src.last_polled_at and (
                    dup.last_polled_at is None
                    or src.last_polled_at > dup.last_polled_at
                ):
                    dup.last_polled_at = src.last_polled_at
                # enabled 取 OR
                dup.enabled = dup.enabled or src.enabled
                s.delete(src)
                merge_count += 1

        # candidate_posts：批量 UPDATE
        cand_updated = s.execute(
            update(CandidatePost)
            .where(func.lower(CandidatePost.subreddit) != CandidatePost.subreddit)
            .values(subreddit=func.lower(CandidatePost.subreddit))
        ).rowcount

        s.flush()
        print(
            f"\n✓ subreddit_sources: renamed {rename_count}, merged {merge_count}; "
            f"candidate_posts updated: {cand_updated}"
        )


if __name__ == "__main__":
    main()
