"""M1 連通性驗證腳本。

OAuth 還沒過，這支腳本走 PublicJSONScraper 跑 SCHEDULE.md M1.2–1.7 的等價驗證：
    1. fetch_new(r/Taiwan)
    2. fetch_new(r/tifu)
    3. search("UPDATE", subreddit="all")
    4. fetch_post(已知 ID)
    5. fetch_duplicates（試一下，public JSON 不一定穩）
    6. fetch_user_submissions（試一下，同上）
    7. 列 M1.8 的每日 API call 預算

用法：
    uv run python scripts/m1_hello.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 讓 `python scripts/m1_hello.py` 也能 import 套件（不依賴 editable install）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from reddit_tracker.scrapers.factory import build_scraper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("m1_hello")


def banner(msg: str) -> None:
    print()
    print("=" * 72)
    print(f"  {msg}")
    print("=" * 72)


def show_posts(posts, n: int = 5) -> None:
    if not posts:
        print("  (empty)")
        return
    for p in posts[:n]:
        deleted = " [DELETED]" if p.is_deleted else ""
        nsfw = " [NSFW]" if p.over_18 else ""
        print(
            f"  · {p.reddit_post_id} | r/{p.subreddit} | "
            f"score={p.score:>4d} comments={p.num_comments:>4d}{deleted}{nsfw}\n"
            f"    {p.title[:90]}\n"
            f"    author={p.author} created={p.created_utc.isoformat()}"
        )


def main() -> int:
    load_dotenv()
    scraper = build_scraper()

    banner("M1.2 connectivity smoke — fetch_new(r/Taiwan, limit=10)")
    taiwan = scraper.fetch_new("Taiwan", limit=10)
    print(f"  got {len(taiwan)} posts")
    show_posts(taiwan)

    banner("M1.3 fetch_new(r/tifu, limit=10)")
    tifu = scraper.fetch_new("tifu", limit=10)
    print(f"  got {len(tifu)} posts")
    show_posts(tifu)

    banner('M1.4 search(query="UPDATE", subreddit="all", time_filter="day")')
    hits = scraper.search("UPDATE", subreddit="all", time_filter="day", limit=10)
    print(f"  got {len(hits)} hits")
    show_posts(hits)

    # 拿剛抓到、score 最高那篇來做 M1.5–1.7
    sample_pool = [p for p in tifu + taiwan if not p.is_deleted and p.author]
    sample = max(sample_pool, key=lambda p: p.score, default=None) if sample_pool else None

    if sample:
        banner(f"M1.5 fetch_post({sample.reddit_post_id})  ← top score from above")
        again = scraper.fetch_post(sample.reddit_post_id)
        if again:
            print(f"  re-fetched OK | score={again.score} comments={again.num_comments}")
        else:
            print("  ⚠️  fetch_post 回 None — 可能被 removed")

        banner(f"M1.6 fetch_duplicates({sample.reddit_post_id})  ← public JSON 通常 403")
        dups = scraper.fetch_duplicates(sample.reddit_post_id)
        print(f"  got {len(dups)} duplicates")
        show_posts(dups, n=3)

        banner(f"M1.7 fetch_user_submissions({sample.author}, limit=5)")
        author_posts = scraper.fetch_user_submissions(sample.author, limit=5)
        print(f"  got {len(author_posts)} posts from u/{sample.author}")
        show_posts(author_posts, n=3)

    # ------------------------------------------------------------------
    # M1.8 每日 API call 預算（公式來自 SCHEDULE.md）
    # ------------------------------------------------------------------
    banner("M1.8 daily API call budget")
    n_subs = 16
    sub_polls_per_day = 24       # 60 min interval
    n_keywords = 20
    keyword_polls_per_day = 4    # 6h interval
    tracked_posts = 30
    tracked_polls_per_day = 8    # mixed tier 平均
    daily = (
        n_subs * sub_polls_per_day
        + n_keywords * keyword_polls_per_day
        + tracked_posts * tracked_polls_per_day
    )
    qpm = daily / (24 * 60)
    print(f"  subreddit polling:   {n_subs} × {sub_polls_per_day} = {n_subs * sub_polls_per_day}")
    print(f"  keyword polling:     {n_keywords} × {keyword_polls_per_day} = {n_keywords * keyword_polls_per_day}")
    print(f"  tracked-post polling: {tracked_posts} × {tracked_polls_per_day} = {tracked_posts * tracked_polls_per_day}")
    print(f"  ── total:             {daily} calls/day  ≈ {qpm:.2f} QPM")
    print(f"  PRAW 上限 100 QPM     → 餘裕 {100 / qpm:.0f}× ✅")
    print(f"  public JSON ~10 QPM   → 餘裕 {10 / qpm:.0f}×  (M1/M2 階段可行)")

    print()
    print("✅ M1 連通性驗證完成（走 public JSON path）")
    print("   待 OAuth 過了把 REDDIT_SCRAPER=praw 切過去即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
