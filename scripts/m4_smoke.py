"""M4.8 端到端 smoke — 真的把 daily push 送到 Telegram。

流程：
    1. 驗 token + chat_id
    2. pick_daily_top5（自動放寬 window 直到有料 / 或上限）
    3. record_pushes（寫 daily_pushes，pushed_at=None）
    4. deliver_picks（送出 + 回寫 pushed_at）
    5. 印 summary，包含 daily_pushes 表狀態

用法：
    uv run python scripts/m4_smoke.py
    uv run python scripts/m4_smoke.py --breaking      # 跑破例分支
    uv run python scripts/m4_smoke.py --window 240   # 強制 240h 視窗
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from reddit_tracker.bot.sender import deliver_picks
from reddit_tracker.config import get_settings
from reddit_tracker.db import session_scope
from reddit_tracker.models import DailyPush
from reddit_tracker.services.feed import (
    BREAKING_MIN_SEMANTIC,
    check_breaking,
    pick_daily_top5,
    record_pushes,
)


def _validate_env() -> tuple[str, int]:
    s = get_settings()
    token = s.telegram_bot_token
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN 未設", file=sys.stderr)
        sys.exit(2)
    chat_id_raw = s.telegram_chat_id
    if not chat_id_raw:
        print(
            "ERROR: TELEGRAM_CHAT_ID 未設。"
            "先跑 `uv run python scripts/m4_capture_chat_id.py` 抓 chat_id 後填回 .env",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        chat_id = int(chat_id_raw)
    except ValueError:
        print(f"ERROR: TELEGRAM_CHAT_ID={chat_id_raw!r} 不是整數", file=sys.stderr)
        sys.exit(2)
    return token, chat_id


def _try_widening_windows(session, *, now, breaking: bool, max_window: int):
    windows = [24, 48, 72, 120, 240]
    if max_window not in windows:
        windows.append(max_window)
        windows.sort()
    for w in windows:
        if w > max_window:
            break
        if breaking:
            # 為 smoke 把 breaking 的 semantic 門檻降低，提高擊中機率
            picks = check_breaking(
                session, now=now, window_hours=w,
                min_semantic=0.0, max_age_h=240.0,
            )
        else:
            picks = pick_daily_top5(session, now=now, window_hours=w)
        if picks:
            return picks, w
    return [], windows[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--breaking", action="store_true", help="跑 check_breaking 而不是 daily")
    parser.add_argument("--window", type=int, default=240, help="最寬視窗（小時）")
    args = parser.parse_args()

    token, chat_id = _validate_env()
    now = datetime.now(timezone.utc)
    push_date = now.date()
    print(f"[..] now={now.isoformat()} push_date={push_date}")

    with session_scope() as session:
        picks, window_used = _try_widening_windows(
            session, now=now, breaking=args.breaking, max_window=args.window,
        )
        if not picks:
            print(f"[err] 沒有候選可推（試過 ≤{window_used}h）。", file=sys.stderr)
            return 1
        print(f"[ok] picked={len(picks)}（window={window_used}h, mode={'breaking' if args.breaking else 'daily'}）")
        for p in picks:
            print(
                f"     #{p.rank} {p.push_type:<11s} cand={p.candidate_post_id} "
                f"r/{p.candidate.subreddit} v={p.velocity!r} s={p.semantic!r} f={p.final_score!r}"
            )
            print(f"        title: {(p.candidate.title or '')[:70]}")

        stat = record_pushes(session, picks, push_date=push_date, now=now)
        print(f"[ok] record_pushes: inserted={stat.inserted} skipped_dupe={stat.skipped_dupe}")

    # deliver_picks 用自己的 session_scope 回寫 pushed_at — 這裡 await
    from telegram import Bot

    async def _run():
        bot = Bot(token=token)
        async with bot:
            return await deliver_picks(bot, chat_id, picks, push_date=push_date)

    sent, failed = asyncio.run(_run())
    print(f"[ok] deliver_picks: sent={sent} failed={failed}")

    # 驗 pushed_at 真的寫進去了
    with session_scope() as session:
        rows = session.scalars(
            select(DailyPush).where(
                DailyPush.push_date == push_date,
                DailyPush.candidate_post_id.in_([p.candidate_post_id for p in picks]),
            )
        ).all()
        for r in rows:
            print(
                f"     daily_push id={r.id} cand={r.candidate_post_id} "
                f"type={r.push_type} pushed_at={r.pushed_at}"
            )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
