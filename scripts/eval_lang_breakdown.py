"""M7.3 — 中英 subreddit 對照 (SCHEDULE.md 7.3)。

每個 sub 顯示:
    candidates / rules_pass / haiku_track / final_pass / pushed / collected / tracked
    + 各層通過率

最後 aggregate 出中文 sub vs 英文 sub 兩列總表。

中英 sub 的判定: 用 CandidatePost.lang 多數決 (single sub 內部 lang 比較,
取 >= 50% 那邊). 但 seeds 已預先標 lang_hint, 同樣可用.

用法:
    uv run python scripts/eval_lang_breakdown.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import case, func, select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import (  # noqa: E402
    CandidatePost,
    DailyPush,
    Feedback,
    ScoringRecord,
    SubredditSource,
    TrackedPost,
)


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "—"
    return f"{numerator / denominator * 100:.1f}%"


def main() -> None:
    with session_scope() as s:
        # 每 sub 的 candidate count + lang 分布 (用來定義 sub 主要語言)
        cand_rows = s.execute(
            select(
                CandidatePost.subreddit,
                CandidatePost.lang,
                func.count(CandidatePost.id),
            ).group_by(CandidatePost.subreddit, CandidatePost.lang)
        ).all()
        cand_by_sub: dict[str, dict[str | None, int]] = defaultdict(dict)
        for sub, lang, n in cand_rows:
            cand_by_sub[sub][lang] = n

        # 每 sub 的 candidate 總數
        cand_total: dict[str, int] = {
            sub: sum(d.values()) for sub, d in cand_by_sub.items()
        }

        # seed lang_hint (備用 — 若該 sub candidate 全是 None lang)
        seed_hint = dict(
            s.execute(
                select(SubredditSource.name, SubredditSource.lang_hint)
            ).all()
        )

        def sub_lang(sub: str) -> str:
            d = cand_by_sub.get(sub, {})
            zh = d.get("zh", 0)
            en = d.get("en", 0)
            if zh + en == 0:
                return seed_hint.get(sub) or "unknown"
            return "zh" if zh > en else "en"

        # scoring: 每 sub 的 rules_pass / haiku_track / final_pass
        # rules 的 passed=True 來算 pass; haiku 的 passed=True 來算 track-verdict;
        # final 的 passed=True 來算 final pass
        scoring_rows = s.execute(
            select(
                CandidatePost.subreddit,
                ScoringRecord.stage,
                func.sum(case((ScoringRecord.passed.is_(True), 1), else_=0)),
                func.count(ScoringRecord.id),
            )
            .join(CandidatePost, CandidatePost.id == ScoringRecord.candidate_post_id)
            .group_by(CandidatePost.subreddit, ScoringRecord.stage)
        ).all()
        score_table: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
        for sub, stage, passed, total in scoring_rows:
            score_table[sub][stage] = (int(passed or 0), int(total))

        # pushed per sub
        push_rows = s.execute(
            select(CandidatePost.subreddit, func.count(DailyPush.id))
            .join(CandidatePost, CandidatePost.id == DailyPush.candidate_post_id)
            .group_by(CandidatePost.subreddit)
        ).all()
        pushed_by_sub = {sub: int(n) for sub, n in push_rows}

        # collected per sub (unique candidate with collect feedback)
        collected_cids = set(
            s.scalars(
                select(Feedback.candidate_post_id).where(Feedback.action == "collect")
            ).all()
        )
        collected_subs_rows = s.execute(
            select(CandidatePost.subreddit, func.count(CandidatePost.id))
            .where(CandidatePost.id.in_(collected_cids))
            .group_by(CandidatePost.subreddit)
        ).all() if collected_cids else []
        collected_by_sub = {sub: int(n) for sub, n in collected_subs_rows}

        # tracked per sub
        tracked_rows = s.execute(
            select(CandidatePost.subreddit, func.count(TrackedPost.id))
            .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
            .group_by(CandidatePost.subreddit)
        ).all()
        tracked_by_sub = {sub: int(n) for sub, n in tracked_rows}

        # 列每 sub
        all_subs = sorted(
            cand_total.keys(),
            key=lambda x: -cand_total[x],
        )

        print(f"# M7.3 中英 subreddit 對照 ({len(all_subs)} 個 sub)\n")
        print(
            "| r/sub | lang | candidates | rules pass | haiku track | final pass | pushed | collected | tracked |"
        )
        print(
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"
        )

        # 用同一個 row 結構 aggregate
        lang_agg: dict[str, dict[str, int]] = defaultdict(lambda: {
            "cand": 0, "rules_pass": 0, "rules_total": 0,
            "haiku_pass": 0, "haiku_total": 0,
            "final_pass": 0, "final_total": 0,
            "pushed": 0, "collected": 0, "tracked": 0, "n_sub": 0,
        })

        for sub in all_subs:
            ln = sub_lang(sub)
            cnt = cand_total[sub]
            rules_p, rules_t = score_table[sub].get("rules", (0, 0))
            haiku_p, haiku_t = score_table[sub].get("haiku", (0, 0))
            final_p, final_t = score_table[sub].get("final", (0, 0))
            pushed = pushed_by_sub.get(sub, 0)
            collected = collected_by_sub.get(sub, 0)
            tracked = tracked_by_sub.get(sub, 0)
            print(
                f"| r/{sub} | {ln} | {cnt} | "
                f"{rules_p}/{rules_t} ({_pct(rules_p, rules_t)}) | "
                f"{haiku_p}/{haiku_t} ({_pct(haiku_p, haiku_t)}) | "
                f"{final_p}/{final_t} ({_pct(final_p, final_t)}) | "
                f"{pushed} | {collected} | {tracked} |"
            )

            agg = lang_agg[ln]
            agg["cand"] += cnt
            agg["rules_pass"] += rules_p
            agg["rules_total"] += rules_t
            agg["haiku_pass"] += haiku_p
            agg["haiku_total"] += haiku_t
            agg["final_pass"] += final_p
            agg["final_total"] += final_t
            agg["pushed"] += pushed
            agg["collected"] += collected
            agg["tracked"] += tracked
            agg["n_sub"] += 1

        # aggregate
        print("\n### 語言層彙整\n")
        print(
            "| lang | n_sub | candidates | rules pass | haiku track | final pass | pushed | collected | tracked |"
        )
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for ln in sorted(lang_agg):
            a = lang_agg[ln]
            print(
                f"| {ln} | {a['n_sub']} | {a['cand']} | "
                f"{a['rules_pass']}/{a['rules_total']} ({_pct(a['rules_pass'], a['rules_total'])}) | "
                f"{a['haiku_pass']}/{a['haiku_total']} ({_pct(a['haiku_pass'], a['haiku_total'])}) | "
                f"{a['final_pass']}/{a['final_total']} ({_pct(a['final_pass'], a['final_total'])}) | "
                f"{a['pushed']} | {a['collected']} | {a['tracked']} |"
            )

        # 漏斗整體 (中英合計)
        total_cand = sum(a["cand"] for a in lang_agg.values())
        total_rules = sum(a["rules_pass"] for a in lang_agg.values())
        total_haiku = sum(a["haiku_pass"] for a in lang_agg.values())
        total_final = sum(a["final_pass"] for a in lang_agg.values())
        total_pushed = sum(a["pushed"] for a in lang_agg.values())
        total_collected = sum(a["collected"] for a in lang_agg.values())
        total_tracked = sum(a["tracked"] for a in lang_agg.values())

        print("\n### 整體漏斗\n")
        print(
            f"discovered {total_cand}\n"
            f"  → rules pass {total_rules} ({_pct(total_rules, total_cand)})\n"
            f"  → haiku track {total_haiku} ({_pct(total_haiku, total_rules)} of rules)\n"
            f"  → final pass {total_final} ({_pct(total_final, total_haiku)} of haiku)\n"
            f"  → pushed {total_pushed} ({_pct(total_pushed, total_final)} of final)\n"
            f"  → collected {total_collected} ({_pct(total_collected, total_pushed)} of pushed)\n"
            f"  → tracked {total_tracked}"
        )


if __name__ == "__main__":
    main()
