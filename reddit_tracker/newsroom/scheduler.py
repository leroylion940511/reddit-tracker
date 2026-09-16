"""Dedicated, sleep-resistant 08:30 Asia/Taipei newspaper scheduler."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from ..config import get_settings
from ..scheduler import _PollingBackgroundScheduler
from .run import publish_edition

logger = logging.getLogger(__name__)


def _publish_today() -> None:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    prepared = publish_edition(edition_date=today)
    logger.info("newsroom scheduled edition=%s items=%d delivered", prepared.edition_id, len(prepared.view.items))


def build_scheduler() -> _PollingBackgroundScheduler:
    settings = get_settings()
    scheduler = _PollingBackgroundScheduler(timezone=ZoneInfo(settings.newsroom_delivery_timezone))
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
        "newsroom scheduler waiting for %02d:%02d %s",
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
