"""Sleep-resistant scheduler for multi-source collection and the v2.0 daily."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import select

from ..backup import run_scheduled_backup
from ..collection.clustering import cluster_recent_items
from ..collection.collector import collect_due_sources
from ..config import get_settings
from ..daily.run import prepare_daily, prepare_with_shadow, publish_daily
from ..db import session_scope
from ..models import DailyEdition
from ..llm.codex_version import check_codex_version
from ..llm.deadline import deadline_on, llm_deadline
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


# 06:00 準備與收集的協調（同一個 process 內）。M 組從寫稿到出刊稿落地是同一個 SQLite 寫入交易，
# 收集撞上就等鎖 30 秒後 `database is locked`（11/11、11/24–11/26）。準備期間收集讓開，結束後立刻補一輪；
# 和 tick 從哪一分鐘起算無關，重載時間不用再挑。只管 scheduler 內的 job，手動 CLI prepare 不在此列。
_PREPARING = threading.Event()
_COLLECTION_LOCK = threading.Lock()
_collection_deferred = False
# 準備開始前最多等進行中的收集多久（平常幾秒；RSSHub 慢時一兩分鐘）
COLLECTION_DRAIN_SECONDS = 300.0


def _run_source_collection() -> None:
    """Collect due multi-source feeds into source_items (v2.0 daily)."""
    global _collection_deferred
    if _PREPARING.is_set():
        _collection_deferred = True
        logger.info("source collection deferred: daily prepare is running; will catch up when it finishes")
        return
    if not _COLLECTION_LOCK.acquire(blocking=False):
        logger.info("source collection skipped: another round is still running")
        return
    try:
        _collect_and_cluster()
    finally:
        _COLLECTION_LOCK.release()


def _collect_and_cluster() -> None:
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
    """準備期間擋下收集；先等進行中的那輪寫完，準備結束（成功或失敗）後補一輪被延後的收集。"""
    global _collection_deferred
    _PREPARING.set()
    try:
        if _COLLECTION_LOCK.acquire(timeout=COLLECTION_DRAIN_SECONDS):
            _COLLECTION_LOCK.release()
        else:
            logger.warning("collection still running after %.0fs; daily prepare starts anyway", COLLECTION_DRAIN_SECONDS)
        _prepare_daily_today_inner()
    finally:
        _PREPARING.clear()
        if _collection_deferred:
            _collection_deferred = False
            try:
                _run_source_collection()
            except Exception:  # noqa: BLE001 - 補抓失敗不能蓋掉準備的結果；下一個 tick 照常
                logger.exception("deferred source collection failed after daily prepare")


def _prepare_daily_today_inner() -> None:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.newsroom_delivery_timezone)).date()
    # 版本不一致只記 ERROR＋Telegram 警告，照常出刊
    check_codex_version(settings)
    # 過了截止（預設 08:20）就不再呼叫模型，角色降級成模板稿，08:35 照常有版可發（llm/deadline.py）
    deadline = deadline_on(today, getattr(settings, "daily_prepare_deadline", "08:20"), settings.newsroom_delivery_timezone)
    with llm_deadline(deadline):
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


def _run_db_backup() -> None:
    run_scheduled_backup()


def startup_catchup(now: datetime | None = None) -> str:
    """冷啟動時補做錯過的準備或發行（DAILY_STARTUP_CATCHUP_MINUTES>0 才做）。回傳做了什麼，給 log 與測試。"""
    settings = get_settings()
    window = int(getattr(settings, "daily_startup_catchup_minutes", 0) or 0)
    if window <= 0 or not getattr(settings, "daily_edition_enabled", False):
        return "off"
    tz = ZoneInfo(settings.newsroom_delivery_timezone)
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    prepare_at = now.replace(hour=settings.daily_prepare_hour, minute=settings.daily_prepare_minute, second=0, microsecond=0)
    deliver_at = now.replace(hour=settings.daily_delivery_hour, minute=settings.daily_delivery_minute, second=0, microsecond=0)
    with session_scope() as session:
        status = session.scalar(select(DailyEdition.status).where(DailyEdition.edition_date == today))
    if status is None:
        if prepare_at <= now < deliver_at:
            logger.warning("startup catch-up: no edition for %s after %s; running prepare now", today, prepare_at.strftime("%H:%M"))
            _prepare_daily_today()
            return "prepared"
        return "none"
    if status == "drafted" and deliver_at <= now <= deliver_at + timedelta(minutes=window):
        logger.warning("startup catch-up: edition %s still drafted after %s; publishing now", today, deliver_at.strftime("%H:%M"))
        _publish_daily_today()
        return "published"
    if status in ("publishing", "delivery_failed") and now >= deliver_at:
        logger.error(
            "startup catch-up: edition %s is %s; delivery state unknown, check Telegram before `daily publish`", today, status,
        )
        return "needs_check"
    return "none"


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
    if getattr(settings, "db_backup_dir", ""):
        scheduler.add_job(
            _run_db_backup,
            CronTrigger(hour=settings.db_backup_hour, minute=settings.db_backup_minute, timezone=tz),
            id="db_backup",
            name="db_backup",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60,
        )
    if int(getattr(settings, "daily_startup_catchup_minutes", 0) or 0) > 0 and getattr(settings, "daily_edition_enabled", False):
        # 一次性：排程啟動後在 worker 執行，不卡住 main thread
        scheduler.add_job(startup_catchup, id="daily_startup_catchup", name="daily_startup_catchup",
                          next_run_time=datetime.now(tz) + timedelta(seconds=30))
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
