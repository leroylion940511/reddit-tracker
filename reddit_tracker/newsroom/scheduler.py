"""Dedicated, sleep-resistant 08:30 Asia/Taipei newspaper scheduler."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_settings
from ..db import session_scope
from ..scheduler import _PollingBackgroundScheduler
from ..scrapers.factory import build_scraper
from ..services.discovery import discover_from_subreddits
from .run import prepare_edition, publish_edition

logger = logging.getLogger(__name__)


def _run_candidate_discovery() -> None:
    """Refresh v5's source cache without invoking any retired v4 workflow."""
    settings = get_settings()
    scraper = build_scraper()
    try:
        with session_scope() as session:
            stats = discover_from_subreddits(
                session,
                scraper,
                per_sub_limit=settings.discovery_per_sub_limit,
                commit_each_source=True,
            )
    finally:
        close = getattr(scraper, "close", None)
        if callable(close):
            close()
    logger.info(
        "newsroom candidate discovery done: sources=%d inserted=%d dupe=%d",
        len(stats),
        sum(stat.inserted for stat in stats),
        sum(stat.skipped_dupe for stat in stats),
    )


def _publish_today() -> None:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    prepared = publish_edition(edition_date=today)
    logger.info("newsroom scheduled edition=%s items=%d delivered", prepared.edition_id, len(prepared.view.items))


def _prepare_today() -> None:
    """Draft before delivery so 08:30 only needs the idempotent send step."""
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    prepared = prepare_edition(edition_date=today)
    logger.info("newsroom prepared edition=%s items=%d writer=%s", prepared.edition_id, len(prepared.view.items), prepared.writer_used)


def build_scheduler() -> _PollingBackgroundScheduler:
    settings = get_settings()
    scheduler = _PollingBackgroundScheduler(timezone=ZoneInfo(settings.newsroom_delivery_timezone))
    scheduler.add_job(
        _run_candidate_discovery,
        IntervalTrigger(minutes=settings.newsroom_discovery_interval_minutes),
        id="newsroom_candidate_discovery",
        name="newsroom_candidate_discovery",
        max_instances=1,
        coalesce=True,
        # Start the scheduler first, then let its worker perform the first
        # crawl.  A successful RSS round can take many minutes because of
        # deliberate per-request throttling; doing it synchronously in main
        # used to defer every other job until the round was complete.
        next_run_time=datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)),
    )
    scheduler.add_job(
        _prepare_today,
        CronTrigger(
            hour=settings.newsroom_preparation_hour,
            minute=settings.newsroom_preparation_minute,
            timezone=ZoneInfo(settings.newsroom_delivery_timezone),
        ),
        id="newsroom_prepare_edition",
        name="newsroom_prepare_edition",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 60,
    )
    scheduler.add_job(
        _publish_today,
        CronTrigger(
            hour=settings.newsroom_delivery_hour,
            minute=settings.newsroom_delivery_minute,
            timezone=ZoneInfo(settings.newsroom_delivery_timezone),
        ),
        id="newsroom_daily_edition",
        name="newsroom_daily_edition",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 60,
    )
    return scheduler


def main() -> int:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    scheduler = build_scheduler()

    def shutdown(signum, frame):  # noqa: ANN001, ARG001
        logger.info("newsroom scheduler shutting down (signal=%s)", signum)
        if scheduler.running:
            scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    logger.info(
        "newsroom scheduler starting: discovery=%dmin, prepare=%02d:%02d, delivery=%02d:%02d %s",
        settings.newsroom_discovery_interval_minutes,
        settings.newsroom_preparation_hour,
        settings.newsroom_preparation_minute,
        settings.newsroom_delivery_hour,
        settings.newsroom_delivery_minute,
        settings.newsroom_delivery_timezone,
    )
    scheduler.start()
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        if scheduler.running:
            scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
