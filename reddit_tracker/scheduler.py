"""APScheduler entrypoint — discovery 雙 job。

對應 SCHEDULE.md M2.11。M3+ 還會加 scoring_job / push_job / breaking_check / polling，
這支先做 discovery 兩個 job 跑起來。

用法：
    uv run python -m reddit_tracker.scheduler

退出：Ctrl-C
"""

from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .db import session_scope
from .scrapers.factory import build_scraper
from .services.discovery import discover_from_keywords, discover_from_subreddits

logger = logging.getLogger("scheduler")


def _run_subreddit_discovery() -> None:
    settings = get_settings()
    scraper = build_scraper()
    with session_scope() as session:
        stats = discover_from_subreddits(
            session, scraper, per_sub_limit=settings.discovery_per_sub_limit
        )
    total_in = sum(s.inserted for s in stats)
    total_dup = sum(s.skipped_dupe for s in stats)
    logger.info(
        "subreddit discovery done: sources=%d inserted=%d dupe=%d",
        len(stats), total_in, total_dup,
    )
    _close_scraper(scraper)


def _run_keyword_discovery() -> None:
    settings = get_settings()
    scraper = build_scraper()
    with session_scope() as session:
        stats = discover_from_keywords(
            session, scraper, per_keyword_limit=settings.discovery_per_keyword_limit
        )
    total_in = sum(s.inserted for s in stats)
    total_dup = sum(s.skipped_dupe for s in stats)
    logger.info(
        "keyword discovery done: keywords=%d inserted=%d dupe=%d",
        len(stats), total_in, total_dup,
    )
    _close_scraper(scraper)


def _close_scraper(scraper) -> None:
    close = getattr(scraper, "close", None)
    if callable(close):
        close()


def build_scheduler() -> BlockingScheduler:
    settings = get_settings()
    sched = BlockingScheduler(timezone="UTC")

    sched.add_job(
        _run_subreddit_discovery,
        trigger=IntervalTrigger(minutes=settings.poll_subreddit_minutes),
        id="subreddit_discovery",
        name="discover_from_subreddits",
        next_run_time=None,  # 由 main() 視情況啟動時跑一次
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _run_keyword_discovery,
        trigger=IntervalTrigger(hours=settings.poll_keyword_hours),
        id="keyword_discovery",
        name="discover_from_keywords",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )
    return sched


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    sched = build_scheduler()

    def _shutdown(signum, frame):  # noqa: ARG001
        logger.info("Shutting down scheduler (signal=%s)", signum)
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "scheduler starting | subreddit every %d min | keyword every %d h | scraper=%s",
        settings.poll_subreddit_minutes,
        settings.poll_keyword_hours,
        settings.reddit_scraper,
    )
    # 啟動時各跑一次 — 不然要等 60 分鐘才看到第一批資料
    logger.info("running initial pass...")
    _run_subreddit_discovery()
    _run_keyword_discovery()

    sched.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
