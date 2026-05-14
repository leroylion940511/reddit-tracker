"""M2 端到端 smoke：載入 seeds → 跑一輪 subreddit + keyword discovery → 印統計。

不是 M2.13 的「連續 24h」運行（那是排程器要做的事），但能在啟動排程器之前
確認所有 wiring 正常。

用法：
    uv run python scripts/m2_smoke.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import CandidatePost, KeywordSeed, SubredditSource  # noqa: E402
from reddit_tracker.scrapers.factory import build_scraper  # noqa: E402
from reddit_tracker.seeds.loader import load_all  # noqa: E402
from reddit_tracker.services.discovery import (  # noqa: E402
    discover_from_keywords,
    discover_from_subreddits,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("m2_smoke")


def banner(msg: str) -> None:
    print(f"\n{'=' * 72}\n  {msg}\n{'=' * 72}")


def main() -> int:
    load_dotenv()

    banner("Step 1: load seeds (idempotent)")
    with session_scope() as s:
        result = load_all(s)
    for table, (inserted, updated) in result.items():
        print(f"  {table}: +{inserted} new / {updated} back-filled")

    banner("Step 2: subreddit discovery (一輪)")
    scraper = build_scraper()
    with session_scope() as s:
        stats = discover_from_subreddits(s, scraper, per_sub_limit=5)
    if not stats:
        print("  ⚠️  no enabled subreddit sources")
    for st in stats:
        print(
            f"  {st.source:<40} fetched={st.fetched:>3} "
            f"inserted={st.inserted:>3} dupe={st.skipped_dupe:>3} deleted={st.skipped_deleted:>3}"
        )

    banner("Step 3: keyword discovery (一輪)")
    # 為節省一次跑的 API 量，限定前 3 個 keyword
    with session_scope() as s:
        seeds = s.scalars(select(KeywordSeed).where(KeywordSeed.enabled == True)).all()  # noqa: E712
        # 暫時 disable 其他 keyword 避免一次跑光配額
        keep = {seed.keyword for seed in seeds[:3]}
        for seed in seeds:
            if seed.keyword not in keep:
                seed.enabled = False
        s.commit()

    with session_scope() as s:
        stats = discover_from_keywords(s, scraper, per_keyword_limit=10)

    for st in stats:
        print(
            f"  {st.source:<40} fetched={st.fetched:>3} "
            f"inserted={st.inserted:>3} dupe={st.skipped_dupe:>3} deleted={st.skipped_deleted:>3}"
        )

    # 復原 enabled
    with session_scope() as s:
        for seed in s.scalars(select(KeywordSeed)).all():
            seed.enabled = True

    banner("Step 4: DB 狀態檢查")
    with session_scope() as s:
        total = s.scalar(select(func.count(CandidatePost.id))) or 0
        per_sub_rows = s.execute(
            select(CandidatePost.subreddit, func.count(CandidatePost.id))
            .group_by(CandidatePost.subreddit)
            .order_by(func.count(CandidatePost.id).desc())
        ).all()
    print(f"  total candidate_posts: {total}")
    for sub, n in per_sub_rows:
        print(f"    r/{sub:<30} {n:>4d}")

    close = getattr(scraper, "close", None)
    if callable(close):
        close()
    print("\n✅ M2 smoke 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
