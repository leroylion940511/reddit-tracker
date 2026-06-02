"""M7.7 — 把累積零產出的 sub / keyword 標 enabled=false (SCHEDULE.md 7.7)。

判定條件 (dead = 兩條都成立):
    1. 該 sub/keyword 從未產出任何 collect feedback (從 Feedback table 反查,
       不靠 SubredditSource.total_collected 這個 stale counter)
    2. total_candidates_yielded >= 200 (有跑足夠久, 不是新加入的種子)

預設 dry-run 列出候選名單; 加 --apply 才實際 update.

用法:
    uv run python scripts/m7_disable_dead_sources.py           # dry-run
    uv run python scripts/m7_disable_dead_sources.py --apply   # 真改
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import (  # noqa: E402
    CandidatePost,
    Feedback,
    KeywordSeed,
    SubredditSource,
)


MIN_YIELDED = 200  # 至少跑出這麼多 candidate 才能說 "確定零產出"


def main() -> None:
    apply = "--apply" in sys.argv

    with session_scope() as s:
        # 從 Feedback 反查每 sub 的真實 collect 數 (避開 stale counter)
        collect_by_sub_raw = s.execute(
            select(
                CandidatePost.subreddit,
                func.count(func.distinct(Feedback.candidate_post_id)),
            )
            .join(CandidatePost, CandidatePost.id == Feedback.candidate_post_id)
            .where(Feedback.action == "collect")
            .group_by(CandidatePost.subreddit)
        ).all()
        # 不分大小寫做歸併: r/Taiwan vs r/taiwan 都算同 sub
        real_collected: dict[str, int] = {}
        for sub_name, n in collect_by_sub_raw:
            real_collected[sub_name.lower()] = real_collected.get(sub_name.lower(), 0) + int(n)

        # Subreddit
        sub_rows = s.scalars(
            select(SubredditSource)
            .where(SubredditSource.enabled.is_(True))
            .order_by(SubredditSource.name)
        ).all()

        sub_to_disable: list[SubredditSource] = []
        print("# M7.7 dead source 偵測\n")
        print("## subreddit_sources (enabled=true 中)\n")
        print(
            "| sub | yielded | real collect | 動作 |"
        )
        print("|---|---:|---:|---|")
        for sub in sub_rows:
            yielded = sub.total_candidates_yielded
            collected = real_collected.get(sub.name.lower(), 0)
            action = "保留"
            if collected == 0 and yielded >= MIN_YIELDED:
                action = "**DISABLE (零收藏)**"
                sub_to_disable.append(sub)
            elif yielded < MIN_YIELDED:
                action = f"觀察 (yielded < {MIN_YIELDED})"
            elif collected > 0:
                action = f"保留 ({collected} collected)"
            print(
                f"| r/{sub.name} | {yielded} | {collected} | {action} |"
            )

        # 額外: 看 CandidatePost.subreddit 中是否有 SubredditSource 沒記錄到的 sub
        # (例如大小寫不同 / 手動加入的 — r/Taiwan 大寫案例)
        candidate_subs_raw = s.execute(
            select(
                CandidatePost.subreddit,
                func.count(CandidatePost.id),
            ).group_by(CandidatePost.subreddit)
        ).all()
        registered = {s_.name for s_ in sub_rows}
        ghost_subs = [(sub, n) for sub, n in candidate_subs_raw if sub not in registered]
        if ghost_subs:
            print("\n### 在 candidates 中但沒在 subreddit_sources 的 sub (大小寫 / 已 disable)\n")
            print("| sub | candidate count |")
            print("|---|---:|")
            for sub, n in sorted(ghost_subs, key=lambda x: -x[1]):
                print(f"| r/{sub} | {n} |")

        # Keyword
        kw_rows = s.scalars(
            select(KeywordSeed)
            .where(KeywordSeed.enabled.is_(True))
            .order_by(KeywordSeed.keyword)
        ).all()
        kw_to_disable: list[KeywordSeed] = []
        print("\n## keyword_seeds (enabled=true 中)\n")
        print(
            "| keyword | lang | yielded | collected (counter) | 動作 |"
        )
        print("|---|---|---:|---:|---|")
        for kw in kw_rows:
            yielded = kw.total_candidates_yielded
            collected = kw.total_collected
            action = "保留"
            if collected == 0 and yielded >= MIN_YIELDED:
                action = "**DISABLE (零收藏)**"
                kw_to_disable.append(kw)
            elif yielded < MIN_YIELDED:
                action = f"觀察 (yielded < {MIN_YIELDED})"
            print(
                f"| {kw.keyword} | {kw.lang or '-'} | {yielded} | {collected} | {action} |"
            )
        print(
            "\n_keyword 部分仍用 stale counter 估計 (keyword discovery 沒打 feedback "
            "table 直接的反查路徑); Plan C 期間 keyword discovery 整支 disable 中, "
            "資料不會增加, dry-run 結果穩定_"
        )

        # 加查每個 candidate-to-disable sub 是否曾被 push 過 (作判定的健全性檢查)
        from reddit_tracker.models import DailyPush
        push_by_sub_raw = s.execute(
            select(CandidatePost.subreddit, func.count(DailyPush.id))
            .join(CandidatePost, CandidatePost.id == DailyPush.candidate_post_id)
            .group_by(CandidatePost.subreddit)
        ).all()
        pushed_count: dict[str, int] = {sub.lower(): int(n) for sub, n in push_by_sub_raw}
        true_dead = [
            sub for sub in sub_to_disable
            if pushed_count.get(sub.name.lower(), 0) > 0
        ]
        never_pushed_dead = [
            sub for sub in sub_to_disable
            if pushed_count.get(sub.name.lower(), 0) == 0
        ]

        print(
            f"\n**summary**: subs flagged dead = {len(sub_to_disable)}, "
            f"keywords flagged dead = {len(kw_to_disable)}"
        )
        print(
            f"  └─ 其中 {len(true_dead)} 個曾被 push 過但 0 collect (真 dead) — "
            f"{[s.name for s in true_dead] or '(無)'}"
        )
        print(
            f"  └─ 其中 {len(never_pushed_dead)} 個從未被 push 過 (picker 沒選到, "
            f"不是 sub 內容問題) — {[s.name for s in never_pushed_dead]}"
        )
        print(
            "\n⚠️  **判定健全性警告**: 目前 push 樣本只有 14 筆, 大部分 zero-collect "
            "其實是 picker 沒選到 (rules/haiku 通過後仍排不進 daily top 5). "
            "建議 OAuth 通過後再累積 ≥ 50 push 樣本, 重跑此腳本決定 cleanup."
        )

        if not apply:
            print("\n_dry-run mode_: 加 --apply 才會實際 update。")
            return
        if not true_dead and not kw_to_disable:
            print(
                "\n沒有真正該 disable 的 source (上面 flagged 的都是 never-pushed). "
                "不執行 --apply 以避免誤刪。"
            )
            return

        # 真改 — 只動 true_dead, 跳過 never-pushed (避免誤刪)
        for sub in true_dead:
            sub.enabled = False
        for kw in kw_to_disable:
            kw.enabled = False
        s.flush()
        print(
            f"\n✓ 已 disable {len(true_dead)} subs (跳過 {len(never_pushed_dead)} "
            f"never-pushed) + {len(kw_to_disable)} keywords。"
        )


if __name__ == "__main__":
    main()
