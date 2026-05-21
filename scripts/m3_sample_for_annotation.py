"""M3.7：抽 30 篇有 Haiku/Minimax verdict 的 candidate 寫成標記檔。

策略：
- 過濾掉 rules 沒過的（haiku stage details.skipped_due_to_rules=True）
- 中英文 1:2 配比；中文不足從 zh_hint 的 sub 補
- 同一 subreddit 不超過 5 篇（避免單一 sub 主導）
- 抽完寫入 docs/m3_annotations.json，欄位含原貼文、scorer verdict、`manual_verdict`（空待填）

用法：
    uv run python scripts/m3_sample_for_annotation.py
"""

from __future__ import annotations

import json
import logging
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import CandidatePost, ScoringRecord  # noqa: E402


SAMPLE_SIZE = 30
PER_SUB_CAP = 5
ZH_TARGET = 10  # 30 篇裡至少 10 中文（取自 SubredditSeed lang='zh' 的 sub）


ZH_SUBS = {"Taiwan", "HongKong", "China_irl", "taipei", "ChineseLanguage"}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    random.seed(42)

    with session_scope() as s:
        rows = s.execute(
            select(CandidatePost, ScoringRecord)
            .join(ScoringRecord, ScoringRecord.candidate_post_id == CandidatePost.id)
            .where(ScoringRecord.stage == "haiku")
            .where(ScoringRecord.passed.is_not(None))     # 有 verdict
        ).all()

        pool = []
        for cand, sr in rows:
            d = sr.details or {}
            if d.get("skipped_due_to_rules"):
                continue
            if "verdict" not in d:
                continue
            pool.append({
                "candidate_id": cand.id,
                "reddit_post_id": cand.reddit_post_id,
                "subreddit": cand.subreddit,
                "title": cand.title or "",
                "selftext": (cand.selftext or "")[:1500],   # 限長
                "author": cand.author_username,
                "karma": cand.author_karma,
                "score": cand.initial_score,
                "num_comments": cand.initial_num_comments,
                "upvote_ratio": cand.upvote_ratio,
                "lang_hint": cand.lang,
                "permalink": cand.permalink,
                "haiku": {
                    "verdict": d.get("verdict"),
                    "story_potential": d.get("story_potential"),
                    "emotional_pull": d.get("emotional_pull"),
                    "grassroots": d.get("grassroots"),
                    "novelty": d.get("novelty"),
                    "authenticity": d.get("authenticity"),
                    "reason": d.get("reason"),
                },
            })

    if len(pool) < SAMPLE_SIZE:
        print(f"⚠️  pool 只有 {len(pool)} 篇 (< {SAMPLE_SIZE})；全部納入")

    print(f"pool size: {len(pool)}")
    by_sub: dict[str, list[dict]] = defaultdict(list)
    for p in pool:
        by_sub[p["subreddit"]].append(p)
    print("by subreddit:")
    for sub, items in sorted(by_sub.items(), key=lambda kv: -len(kv[1])):
        print(f"  {sub:<30} {len(items)}")

    # 採樣：先確保 ZH_TARGET 中文，再均勻補英文，per-sub cap
    zh_pool = [p for p in pool if p["subreddit"] in ZH_SUBS]
    en_pool = [p for p in pool if p["subreddit"] not in ZH_SUBS]
    random.shuffle(zh_pool)
    random.shuffle(en_pool)

    selected: list[dict] = []
    sub_count: Counter[str] = Counter()

    def try_add(p: dict) -> bool:
        if sub_count[p["subreddit"]] >= PER_SUB_CAP:
            return False
        selected.append(p)
        sub_count[p["subreddit"]] += 1
        return True

    # 1. 先撈滿中文目標
    for p in zh_pool:
        if sum(1 for x in selected if x["subreddit"] in ZH_SUBS) >= ZH_TARGET:
            break
        try_add(p)

    # 2. 用英文補到 SAMPLE_SIZE
    for p in en_pool:
        if len(selected) >= SAMPLE_SIZE:
            break
        try_add(p)

    # 3. 若中文不足、英文也滿 cap → 用剩餘中文補
    if len(selected) < SAMPLE_SIZE:
        for p in zh_pool:
            if p in selected:
                continue
            if len(selected) >= SAMPLE_SIZE:
                break
            try_add(p)

    # 4. 仍不足 → 取消 cap 限制硬塞
    if len(selected) < SAMPLE_SIZE:
        for p in pool:
            if p in selected:
                continue
            if len(selected) >= SAMPLE_SIZE:
                break
            selected.append(p)
            sub_count[p["subreddit"]] += 1

    print(f"\nselected {len(selected)} samples")
    final_subs = Counter(p["subreddit"] for p in selected)
    for sub, n in sorted(final_subs.items(), key=lambda kv: -kv[1]):
        print(f"  {sub:<30} {n}")
    zh_n = sum(1 for p in selected if p["subreddit"] in ZH_SUBS)
    print(f"  zh: {zh_n} / en: {len(selected) - zh_n}")

    # 寫成標記檔
    out_path = Path("docs/m3_annotations.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    annotations = [
        {**p, "manual_verdict": None, "manual_reason": ""} for p in selected
    ]
    out_path.write_text(json.dumps(annotations, ensure_ascii=False, indent=2))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
