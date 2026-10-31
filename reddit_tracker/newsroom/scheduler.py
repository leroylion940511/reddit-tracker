"""Sleep-resistant scheduler for multi-source collection and the v2.0 daily."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..collection.clustering import cluster_recent_items
from ..collection.collector import collect_due_sources
from ..config import get_settings
from ..daily.run import prepare_daily, prepare_with_shadow, publish_daily
from ..db import session_scope
from ..llm.codex_version import check_codex_version
from ..seeds.news_sources import load_registry

logger = logging.getLogger(__name__)

# 手冊步驟 1 要停的舊 job；程式已在 commit 2d95c07 刪除，這裡只留名字做防護與測試。
LEGACY_JOB_IDS = frozenset({
    "newsroom_candidate_discovery",  # 每 90 分鐘爬 Reddit
    "newsroom_prepare_edition",      # 05:30 編舊版 Reddit 早報
    "newsroom_daily_edition",        # 08:30 發舊版 Reddit 早報
})


class _PollingBackgroundScheduler(BackgroundScheduler):
    """繞 macOS cv_wait coalesce — _main_loop 改用 time.sleep polling.

    APScheduler 預設 _main_loop 用 threading.Event.wait(timeout) 算下次 fire,
    但 macOS 對長 cv_wait 會 coalesce, BlockingScheduler / BackgroundScheduler
    同樣中招 (實測 launchd + caffeinate -i + main thread 每秒 sched.wakeup()
    都救不了 — wakeup 的 Event.set() 也被 mach kernel batched).
    這裡 override _main_loop 用 time.sleep (走 nanosleep, 非 cv_wait) polling.
    """

    def _main_loop(self) -> None:
        while self.state != STATE_STOPPED:
            wait_seconds = self._process_jobs()
            # _process_jobs 回到下個 fire 的秒數, None = TIMEOUT_MAX.
            # 卡 ≤1s 確保 misfire 不會被延遲過久.
            sleep_for = 1.0 if wait_seconds is None else min(wait_seconds, 1.0)
            time.sleep(sleep_for)


def _run_source_collection() -> None:
    """Collect due multi-source feeds into source_items (v2.0 daily)."""
    settings = get_settings()
    registry = load_registry(settings.news_sources_path)
    with session_scope() as session:
        stats = collect_due_sources(session, registry)
    logger.info(
        "source collection done: sources=%d ok=%d new=%d duplicate=%d",
        len(stats),
        sum(stat.ok for stat in stats),
        sum(stat.new for stat in stats),
        sum(stat.duplicate for stat in stats),
    )
    # 聚合獨立 commit：失敗只影響本輪事件，不會讓已收的素材回滾。
    with session_scope() as session:
        clustered = cluster_recent_items(
            session,
            general_sources=registry.general_source_ids(),
            disabled_sources=registry.disabled_source_ids(),
        )
    logger.info("story clustering done: %s", clustered)


def _prepare_daily_today() -> None:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    # 版本不一致只記 ERROR＋Telegram 警告，照常出刊
    check_codex_version(settings)
    if shadow_enabled(settings):
        # 手冊步驟 10、12：P 影子先跑、M 後跑，同一份快照；影子失敗只記 log
        edition_id = prepare_with_shadow(today)
    else:
        edition_id = prepare_daily(today)
    logger.info("daily edition prepared: date=%s id=%s", today, edition_id)


def shadow_enabled(settings) -> bool:
    """只有 DAILY_MODE=mas 且 DAILY_SHADOW_ENABLED=true 才跑 P 影子；pipeline 模式行為不變。"""
    return getattr(settings, "daily_mode", "pipeline") == "mas" and bool(getattr(settings, "daily_shadow_enabled", False))


def _publish_daily_today() -> None:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    edition_id = publish_daily(today)
    logger.info("daily edition published: date=%s id=%s", today, edition_id)


def build_scheduler() -> _PollingBackgroundScheduler:
    settings = get_settings()
    tz = ZoneInfo(settings.newsroom_delivery_timezone)
    scheduler = _PollingBackgroundScheduler(timezone=tz)
    if getattr(settings, "legacy_jobs_enabled", False):
        # 不復活已刪的程式：舊 job 一律不註冊，只提醒設定沒有作用。
        logger.warning(
            "LEGACY_JOBS_ENABLED=true ignored: legacy jobs %s were removed in commit 2d95c07",
            ", ".join(sorted(LEGACY_JOB_IDS)),
        )
    if getattr(settings, "news_collection_enabled", False):
        scheduler.add_job(
            _run_source_collection,
            IntervalTrigger(minutes=settings.news_collection_tick_minutes),
            id="newsroom_source_collection",
            name="newsroom_source_collection",
            max_instances=1,
            coalesce=True,
            # Start the scheduler first, then let its worker perform the first
            # round; a slow RSSHub round must not defer the other jobs.
            next_run_time=datetime.now(tz),
        )
    if getattr(settings, "daily_edition_enabled", False):
        scheduler.add_job(
            _prepare_daily_today,
            CronTrigger(hour=settings.daily_prepare_hour, minute=settings.daily_prepare_minute, timezone=tz),
            id="daily_prepare_edition",
            name="daily_prepare_edition",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60,
        )
        scheduler.add_job(
            _publish_daily_today,
            CronTrigger(hour=settings.daily_delivery_hour, minute=settings.daily_delivery_minute, timezone=tz),
            id="daily_publish_edition",
            name="daily_publish_edition",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60,
        )
    leaked = LEGACY_JOB_IDS & {job.id for job in scheduler.get_jobs()}
    if leaked:  # pragma: no cover - 防護：之後的改動不得把舊 job 加回來
        raise RuntimeError(f"legacy jobs must not be registered: {sorted(leaked)}")
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
        "newsroom scheduler starting: collection=%s/%dmin, daily=%s mode=%s shadow=%s "
        "prepare=%02d:%02d delivery=%02d:%02d %s",
        settings.news_collection_enabled,
        settings.news_collection_tick_minutes,
        settings.daily_edition_enabled,
        settings.daily_mode,
        shadow_enabled(settings),
        settings.daily_prepare_hour,
        settings.daily_prepare_minute,
        settings.daily_delivery_hour,
        settings.daily_delivery_minute,
        settings.newsroom_delivery_timezone,
    )
    check_codex_version(settings)
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
