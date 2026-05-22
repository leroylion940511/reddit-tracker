"""APScheduler entrypoint — discovery / scoring / push 多 job。

對應 SCHEDULE.md M2.11 + M3.6 + M4.7。

用法：
    uv run python -m reddit_tracker.scheduler

退出：Ctrl-C
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .db import session_scope
from .llm.factory import build_scorer
from .scrapers.factory import build_scraper
from .services.discovery import discover_from_keywords, discover_from_subreddits
from .services.enrichment import enrich_author_profiles
from .services.feed import check_breaking, pick_daily_top5, record_pushes
from .services.scoring import ScoringService, fetch_unscored, score_batch

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


def _telegram_ready(settings) -> tuple[str, int] | None:
    """檢查 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID 都有設。

    回 (token, chat_id) 或 None；None 時呼叫端應印 warning 後 graceful skip，
    不阻塞其他 job。
    """
    token = settings.telegram_bot_token
    chat_id_raw = settings.telegram_chat_id
    if not token or not chat_id_raw:
        return None
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        logger.error("TELEGRAM_CHAT_ID=%r 不是合法整數，push 略過", chat_id_raw)
        return None
    return token, chat_id


def _deliver_picks_sync(picks, *, push_date) -> tuple[int, int]:
    """sync-to-async 橋接：在 BlockingScheduler 的 thread 內 asyncio.run 跑 sender。"""
    settings = get_settings()
    ready = _telegram_ready(settings)
    if ready is None or not picks:
        return (0, 0)
    token, chat_id = ready
    # Lazy import — 避免在 telegram 沒裝（單元測試環境）時 import scheduler 就壞
    from telegram import Bot
    from .bot.sender import deliver_picks

    async def _go() -> tuple[int, int]:
        bot = Bot(token=token)
        async with bot:
            return await deliver_picks(bot, chat_id, picks, push_date=push_date)

    return asyncio.run(_go())


def _run_daily_push() -> None:
    """每日 09:00 (Asia/Taipei) 推 Top 5。"""
    settings = get_settings()
    if _telegram_ready(settings) is None:
        logger.warning("daily_push 略過：TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設")
        return

    now = datetime.now(timezone.utc)
    push_date = now.date()
    with session_scope() as session:
        picks = pick_daily_top5(session, now=now)
        if not picks:
            logger.info("daily_push: 無候選 (今天 24h 內 final.passed=True 的池為空)")
            return
        stat = record_pushes(session, picks, push_date=push_date, now=now)

    sent, failed = _deliver_picks_sync(picks, push_date=push_date)
    logger.info(
        "daily_push: picked=%d inserted=%d dupe=%d sent=%d failed=%d",
        len(picks), stat.inserted, stat.skipped_dupe, sent, failed,
    )


def _run_breaking_check() -> None:
    """每 10 分鐘檢查破例條件。"""
    settings = get_settings()
    if _telegram_ready(settings) is None:
        # 開發環境沒設 telegram 就靜悄悄略過（避免 log 洗版）
        return

    now = datetime.now(timezone.utc)
    push_date = now.date()
    with session_scope() as session:
        picks = check_breaking(session, now=now)
        if not picks:
            return
        stat = record_pushes(session, picks, push_date=push_date, now=now)

    sent, failed = _deliver_picks_sync(picks, push_date=push_date)
    logger.info(
        "breaking: picked=%d inserted=%d dupe=%d sent=%d failed=%d",
        len(picks), stat.inserted, stat.skipped_dupe, sent, failed,
    )


def _run_scoring() -> None:
    settings = get_settings()
    service = ScoringService(scorer=build_scorer())
    scraper = build_scraper()
    with session_scope() as session:
        # 先補 author_karma / account_created_utc，硬規則才不會無條件放行
        batch = fetch_unscored(session, limit=settings.scoring_batch_limit)
        if batch:
            enrich_author_profiles(session, scraper, batch)
        outcomes = score_batch(session, service, limit=settings.scoring_batch_limit)
    _close_scraper(scraper)
    total = len(outcomes)
    passed_rules = sum(1 for o in outcomes if o.rules_passed)
    tracked = sum(1 for o in outcomes if o.haiku_verdict == "track")
    errors = sum(1 for o in outcomes if o.error)
    logger.info(
        "scoring done: scored=%d rules_passed=%d haiku_track=%d errors=%d",
        total, passed_rules, tracked, errors,
    )


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
    sched.add_job(
        _run_scoring,
        trigger=IntervalTrigger(minutes=settings.scoring_minutes),
        id="scoring",
        name="score_unscored_candidates",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )

    # M4.7 — 每日 09:00 Asia/Taipei (= 01:00 UTC) Top 5；breaking 每 10 分鐘
    sched.add_job(
        _run_daily_push,
        trigger=CronTrigger(
            hour=settings.daily_push_hour_utc,
            minute=settings.daily_push_minute_utc,
            timezone="UTC",
        ),
        id="daily_push",
        name="daily_top5_push",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _run_breaking_check,
        trigger=IntervalTrigger(minutes=settings.breaking_check_minutes),
        id="breaking_check",
        name="breaking_check",
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

    tg = _telegram_ready(settings)
    logger.info(
        "scheduler starting | sub=%dmin keyword=%dh scoring=%dmin "
        "daily_push=%02d:%02dUTC breaking=%dmin telegram=%s scraper=%s",
        settings.poll_subreddit_minutes,
        settings.poll_keyword_hours,
        settings.scoring_minutes,
        settings.daily_push_hour_utc,
        settings.daily_push_minute_utc,
        settings.breaking_check_minutes,
        "ready" if tg else "disabled",
        settings.reddit_scraper,
    )
    # 啟動時各跑一次 — 不然要等 60 分鐘才看到第一批資料
    logger.info("running initial pass...")
    _run_subreddit_discovery()
    _run_keyword_discovery()
    _run_scoring()

    sched.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
