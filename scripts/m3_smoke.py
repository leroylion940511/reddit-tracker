"""M3 端到端 smoke：FakeScraper → 載 seeds → discovery → scoring → 統計輸出。

不依賴 OAuth / 真實 Reddit。FakeScraper 提供 50 筆固定資料；scoring 跑完印：
    - 通過硬規則的比例
    - Haiku verdict 分布（track / skip）
    - final_score 分布概況

用法：
    uv run python scripts/m3_smoke.py
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.llm.factory import build_scorer  # noqa: E402
from reddit_tracker.models import CandidatePost, ScoringRecord  # noqa: E402
from reddit_tracker.scrapers.fake import FakeScraper  # noqa: E402
from reddit_tracker.seeds.loader import load_all  # noqa: E402
from reddit_tracker.services.discovery import (  # noqa: E402
    discover_from_keywords,
    discover_from_subreddits,
)
from reddit_tracker.services.scoring import ScoringService, score_batch  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("m3_smoke")


def banner(msg: str) -> None:
    print(f"\n{'=' * 72}\n  {msg}\n{'=' * 72}")


def main() -> int:
    banner("Step 1: load seeds (idempotent)")
    with session_scope() as s:
        result = load_all(s)
    for table, (inserted, updated) in result.items():
        print(f"  {table}: +{inserted} new / {updated} back-filled")

    banner("Step 2: discovery (fake scraper)")
    scraper = FakeScraper()
    with session_scope() as s:
        sub_stats = discover_from_subreddits(s, scraper, per_sub_limit=50)
        kw_stats = discover_from_keywords(s, scraper, per_keyword_limit=50)
    inserted = sum(st.inserted for st in sub_stats) + sum(st.inserted for st in kw_stats)
    print(f"  subreddit sources={len(sub_stats)}, keyword seeds={len(kw_stats)}, inserted={inserted}")

    banner("Step 3: scoring batch")
    service = ScoringService(scorer=build_scorer())
    with session_scope() as s:
        outcomes = score_batch(s, service, limit=500)
    print(f"  scored: {len(outcomes)}")
    print(f"    rules_pass:  {sum(1 for o in outcomes if o.rules_passed)}")
    print(f"    rules_fail:  {sum(1 for o in outcomes if not o.rules_passed)}")
    print(f"    haiku_track: {sum(1 for o in outcomes if o.haiku_verdict == 'track')}")
    print(f"    haiku_skip:  {sum(1 for o in outcomes if o.haiku_verdict == 'skip')}")
    print(f"    errors:      {sum(1 for o in outcomes if o.error)}")

    banner("Step 4: DB inspection")
    with session_scope() as s:
        n_cand = s.scalar(select(func.count(CandidatePost.id))) or 0
        n_rules = s.scalar(
            select(func.count()).select_from(ScoringRecord).where(ScoringRecord.stage == "rules")
        ) or 0
        n_haiku = s.scalar(
            select(func.count()).select_from(ScoringRecord).where(ScoringRecord.stage == "haiku")
        ) or 0
        n_final = s.scalar(
            select(func.count()).select_from(ScoringRecord).where(ScoringRecord.stage == "final")
        ) or 0
        # final_score 分布
        scores = s.scalars(
            select(ScoringRecord.score).where(
                ScoringRecord.stage == "final", ScoringRecord.score.is_not(None)
            )
        ).all()
        # rules fail_reasons top 5
        fail_dets = s.scalars(
            select(ScoringRecord.details).where(
                ScoringRecord.stage == "rules", ScoringRecord.passed.is_(False)
            )
        ).all()

    print(f"  candidate_posts:  {n_cand}")
    print(f"  scoring_records:  rules={n_rules} haiku={n_haiku} final={n_final}")
    if scores:
        print(
            f"  final_score:     min={min(scores):.3f} mean={mean(scores):.3f} max={max(scores):.3f} n={len(scores)}"
        )
    else:
        print("  final_score:     (none)")
    reason_counter: Counter[str] = Counter()
    for d in fail_dets:
        for r in (d or {}).get("fail_reasons", []):
            reason_counter[r.split(":")[0]] += 1
    if reason_counter:
        print("  top fail reasons:")
        for r, n in reason_counter.most_common(8):
            print(f"    {r:<20} {n}")

    print("\n✅ M3 smoke 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
