"""Telegram handler — 指令骨架 + 三按鈕 callback（M4.5）。

設計重點：
- async telegram callback 與 sync sqlalchemy 之間用 `asyncio.to_thread` 橋接
- DB 邏輯都在 services/feedback.py，這層只解析 callback_data + 回 UI
- /feed、/saved、/ask 等先放 deferred stub，等 M4.6 / M5 / M6 再填內容
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..db import session_scope
from ..models import (
    CandidatePost,
    PostSnapshot,
    RelatedPost,
    TrackedPost,
)
from ..services.feedback import FeedbackOutcome, record_feedback
from ..services.promotion import promote_to_tracked
from .formatter import ACTION_TO_FEEDBACK, RELATION_LABELS, decode_callback

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "Reddit Tracker 指令：\n"
    "/start             註冊\n"
    "/help              顯示說明\n"
    "/feed              查看今日推送 (M4.6 上線)\n"
    "/saved             列出已收藏\n"
    "/timeline <id>     看單篇時間軸\n"
    "/ask <id>          進入問答模式 (M6 上線)\n"
)

_DEFERRED_MSG = "這個功能還沒上線，等之後的里程碑開放。"


# Callback 後回給使用者的提示文字
ACTION_REPLIES = {
    "collect": "✅ 已收藏 — 之後會自動追蹤這篇的更新",
    "dislike": "✅ 已跳過",
    "mute_author": "🔕 已靜音作者",
}

DUPLICATE_REPLY = "（先前已收到相同的回饋）"
INVALID_REPLY = "無效的按鈕回饋"
MISSING_REPLY = "找不到這篇貼文"


async def start_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(
        "嗨！這裡是 Reddit 素人爆文追蹤 Bot（v4 開發中）。\n\n" + HELP_TEXT
    )


async def help_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(HELP_TEXT)


async def deferred_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(_DEFERRED_MSG)


# ---------------------------------------------------------------------------
# M5.9 — /saved + /timeline
# ---------------------------------------------------------------------------


_TIER_ICON = {"hot": "🔴", "cooling": "🟠", "archive": "🟡"}


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_relative_time(dt: datetime, now: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (now - dt).total_seconds()
    if delta < 60:
        return "剛剛"
    if delta < 3600:
        return f"{int(delta // 60)} 分鐘前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小時前"
    return f"{int(delta // 86400)} 天前"


def _saved_list_sync(user_id: int) -> str:
    """組 /saved 訊息（HTML）。在 thread pool 內跑 sync DB query。"""
    with session_scope() as session:
        rows = session.execute(
            select(TrackedPost, CandidatePost)
            .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
            .where(TrackedPost.user_id == user_id)
            .order_by(TrackedPost.promoted_at.desc())
            .limit(50)
        ).all()
        if not rows:
            return "你還沒收藏任何貼文。"

        # 順手抓 snapshot / related 計數
        tracked_ids = [t.id for t, _ in rows]
        snap_counts = dict(
            session.execute(
                select(PostSnapshot.tracked_post_id, func.count(PostSnapshot.id))
                .where(PostSnapshot.tracked_post_id.in_(tracked_ids))
                .group_by(PostSnapshot.tracked_post_id)
            ).all()
        )
        rel_counts = dict(
            session.execute(
                select(RelatedPost.tracked_post_id, func.count(RelatedPost.id))
                .where(RelatedPost.tracked_post_id.in_(tracked_ids))
                .group_by(RelatedPost.tracked_post_id)
            ).all()
        )
        milestone_counts = dict(
            session.execute(
                select(RelatedPost.tracked_post_id, func.count(RelatedPost.id))
                .where(
                    RelatedPost.tracked_post_id.in_(tracked_ids),
                    RelatedPost.is_milestone.is_(True),
                )
                .group_by(RelatedPost.tracked_post_id)
            ).all()
        )

        lines = [f"📚 你的收藏（{len(rows)} 篇）", ""]
        for i, (t, c) in enumerate(rows, start=1):
            tier_icon = _TIER_ICON.get(t.polling_tier, "⚪")
            arch = " [archived]" if t.status == "archived" else ""
            title = _escape_html((c.title or "(無標題)")[:80])
            lines.append(f"<b>{i}. {tier_icon} r/{_escape_html(c.subreddit)}</b>{arch}")
            lines.append(f"   {title}")
            ms = milestone_counts.get(t.id, 0)
            ms_part = f"（★ {ms}）" if ms else ""
            lines.append(
                f"   tier={t.polling_tier} · snapshots={snap_counts.get(t.id, 0)}"
                f" · related={rel_counts.get(t.id, 0)}{ms_part}"
            )
            lines.append(f"   /timeline {t.id}")
            lines.append("")
        return "\n".join(lines).rstrip()


def _timeline_sync(user_id: int, tracked_id: int) -> str:
    """組 /timeline 訊息（HTML）。"""
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.execute(
            select(TrackedPost, CandidatePost)
            .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
            .where(TrackedPost.id == tracked_id)
        ).first()
        if row is None:
            return f"找不到 tracked_post id={tracked_id}。"
        t, c = row
        if t.user_id != user_id:
            return "這篇不是你的收藏。"

        lines = [
            f"📅 <b>r/{_escape_html(c.subreddit)}</b> · {_escape_html((c.title or '')[:80])}",
            f"作者：u/{_escape_html(c.author_username or '?')} · "
            f"收藏於 {t.promoted_at.strftime('%Y-%m-%d %H:%M') if t.promoted_at else '?'}"
            f" · tier={t.polling_tier} · status={t.status}",
        ]
        link = c.permalink
        if link and not link.startswith("http"):
            link = f"https://www.reddit.com{link}"
        if link:
            lines.append(f'<a href="{_escape_html(link)}">原文</a>')

        # 最近 10 筆 snapshot（時間早→晚）
        snaps = session.scalars(
            select(PostSnapshot)
            .where(PostSnapshot.tracked_post_id == tracked_id)
            .order_by(PostSnapshot.captured_at.desc())
            .limit(10)
        ).all()
        if snaps:
            lines.append("")
            lines.append(f"📊 快照變化（最近 {len(snaps)} 筆，新→舊）")
            for s in snaps:
                rel = _fmt_relative_time(s.captured_at, now) if s.captured_at else "?"
                lines.append(
                    f"  {rel} · score={s.score or 0} · comments={s.num_comments or 0}"
                    + (
                        f" · ↑{s.upvote_ratio:.0%}"
                        if s.upvote_ratio is not None
                        else ""
                    )
                )

        # related，時間早→晚
        rels = session.scalars(
            select(RelatedPost)
            .where(RelatedPost.tracked_post_id == tracked_id)
            .order_by(RelatedPost.discovered_at.asc())
            .limit(30)
        ).all()
        if rels:
            lines.append("")
            lines.append(f"🔗 相關事件（{len(rels)} 筆）")
            for r in rels:
                star = "★ " if r.is_milestone else "  "
                label = RELATION_LABELS.get(r.relation_type, r.relation_type)
                snippet = _escape_html((r.content or "")[:140])
                ts = r.posted_at or r.discovered_at
                ts_str = ts.strftime("%m-%d %H:%M") if ts else "?"
                lines.append(f"  {star}{ts_str} · {label}: {snippet}")

        if not snaps and not rels:
            lines.append("")
            lines.append("尚無任何快照或相關事件。")
        return "\n".join(lines)


async def saved_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    text = await asyncio.to_thread(_saved_list_sync, user.id)
    await msg.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def timeline_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    args = ctx.args or []
    if not args:
        await msg.reply_text(
            "用法：/timeline <tracked_id>，先用 /saved 看到 id。"
        )
        return
    try:
        tracked_id = int(args[0])
    except ValueError:
        await msg.reply_text("tracked_id 必須是整數。")
        return
    text = await asyncio.to_thread(_timeline_sync, user.id, tracked_id)
    await msg.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


def _record_feedback_sync(user_id: int, candidate_id: int, action: str) -> FeedbackOutcome:
    """同步包一層 session_scope，給 async handler 用 to_thread 呼叫。

    action='collect' 時順手升格為 tracked_post（M5.1）— 同一個 session 內做完，
    避免 callback 後再開連線；若 feedback 因 candidate_missing / invalid_action 沒寫
    成功就不走升格。重複收藏（duplicate=True）也仍會嘗試升格，promote_to_tracked
    自己 idempotent。
    """
    with session_scope() as session:
        outcome = record_feedback(
            session,
            user_id=user_id,
            candidate_post_id=candidate_id,
            action=action,
        )
        if (
            action == "collect"
            and outcome.feedback_id is not None
            and not outcome.candidate_missing
        ):
            promote_to_tracked(
                session,
                user_id=user_id,
                candidate_post_id=candidate_id,
            )
        return outcome


async def feedback_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 inline button 點擊。callback_data 格式 `fb:<c|d|m>:<candidate_id>`。"""
    query = update.callback_query
    if query is None:
        return

    parsed = decode_callback(query.data)
    if parsed is None:
        logger.warning("ignored unparseable callback_data=%r", query.data)
        await query.answer(INVALID_REPLY)
        return

    short_action, candidate_id = parsed
    fb_action = ACTION_TO_FEEDBACK.get(short_action)
    if fb_action is None:
        logger.warning("ignored unknown short_action=%r", short_action)
        await query.answer(INVALID_REPLY)
        return

    user = update.effective_user
    user_id = user.id if user else 0

    outcome = await asyncio.to_thread(
        _record_feedback_sync, user_id, candidate_id, fb_action
    )

    if outcome.candidate_missing:
        await query.answer(MISSING_REPLY)
        return
    if outcome.invalid_action:
        await query.answer(INVALID_REPLY)
        return

    base_reply = ACTION_REPLIES[fb_action]
    reply = base_reply if not outcome.duplicate else f"{base_reply} {DUPLICATE_REPLY}"
    await query.answer(reply)

    # 把原訊息結尾追加狀態行 + 移除按鈕，避免重複點擊
    msg = query.message
    if msg is not None and msg.text:
        # 直接拿 html_text 才能保留原本的格式（粗體 / 連結）
        original = msg.text_html if msg.text_html is not None else msg.text
        new_text = f"{original}\n\n— {reply}"
        try:
            await query.edit_message_text(
                new_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("edit_message_text failed: %s", e)


__all__ = [
    "ACTION_REPLIES",
    "DUPLICATE_REPLY",
    "HELP_TEXT",
    "INVALID_REPLY",
    "MISSING_REPLY",
    "_record_feedback_sync",
    "_saved_list_sync",
    "_timeline_sync",
    "deferred_cmd",
    "feedback_callback",
    "help_cmd",
    "saved_cmd",
    "start_cmd",
    "timeline_cmd",
]
