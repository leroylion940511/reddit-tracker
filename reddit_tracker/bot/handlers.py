"""Telegram handler — 指令骨架 + 三按鈕 callback（M4.5）。

設計重點：
- async telegram callback 與 sync sqlalchemy 之間用 `asyncio.to_thread` 橋接
- DB 邏輯都在 services/feedback.py，這層只解析 callback_data + 回 UI
- /feed、/saved、/ask 等先放 deferred stub，等 M4.6 / M5 / M6 再填內容
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..config import get_settings
from ..db import session_scope
from ..llm.minimax_chat import ChatClient, build_chat
from ..models import (
    CandidatePost,
    DailyPush,
    PostSnapshot,
    RelatedPost,
    ScoringRecord,
    TrackedPost,
)
from ..scrapers.base import RedditScraper
from ..services import qa as qa_service
from ..services.feedback import FeedbackOutcome, record_feedback
from ..services.promotion import promote_to_tracked
from .formatter import ACTION_TO_FEEDBACK, RELATION_LABELS, decode_callback

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "Reddit Tracker 指令：\n"
    "/start             註冊\n"
    "/help              顯示說明\n"
    "/feed              查看今日推送\n"
    "/digest            本週收藏動態摘要\n"
    "/settings          系統狀態與設定\n"
    "/saved             列出已收藏\n"
    "/timeline <id>     看單篇時間軸\n"
    "/ask <id>          進入問答模式（5 分鐘無互動自動結束）\n"
    "/exit              離開問答模式\n"
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


# ---------------------------------------------------------------------------
# /feed /digest /settings — Plan C 階段補齊的指令
# ---------------------------------------------------------------------------


_PUSH_TYPE_META = {
    "already_hot": ("🔥", "已爆貼"),
    "early_bet":   ("⚡", "早期下注"),
    "breaking":    ("🚨", "即時破例"),
}


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _permalink_url(c: CandidatePost) -> str | None:
    link = c.permalink
    if not link:
        return None
    return link if link.startswith("http") else f"https://www.reddit.com{link}"


def _feed_today_sync(user_id: int) -> str:
    """組 /feed 訊息：今日 daily_pushes 依 push_type 分組；
    若今日無推送則 fallback 列過去 24h 通過 final scoring 的 top 5。"""
    _ = user_id  # 推送是全體共用，不分使用者；保留參數以對齊 cmd 介面
    today = _today_utc()
    with session_scope() as session:
        rows = session.execute(
            select(DailyPush, CandidatePost)
            .join(CandidatePost, CandidatePost.id == DailyPush.candidate_post_id)
            .where(DailyPush.push_date == today)
            .order_by(DailyPush.push_type.asc(), DailyPush.rank.asc().nulls_last())
        ).all()

        if rows:
            grouped: dict[str, list[tuple[DailyPush, CandidatePost]]] = {}
            for dp, c in rows:
                grouped.setdefault(dp.push_type, []).append((dp, c))
            lines = [f"📬 今日推送（{today.isoformat()}，共 {len(rows)} 篇）", ""]
            for ptype, items in grouped.items():
                emoji, label = _PUSH_TYPE_META.get(ptype, ("•", ptype))
                lines.append(f"<b>{emoji} {label}（{len(items)}）</b>")
                for dp, c in items:
                    rank = f"#{dp.rank}" if dp.rank is not None else ""
                    title = _escape_html((c.title or "(無標題)")[:80])
                    url = _permalink_url(c)
                    link_html = (
                        f'<a href="{_escape_html(url)}">{title}</a>' if url else title
                    )
                    lines.append(
                        f"  {rank} r/{_escape_html(c.subreddit)} · {link_html}"
                    )
                lines.append("")
            return "\n".join(lines).rstrip()

        # fallback：過去 24h 通過 final scoring 的 top 5
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        finals = session.execute(
            select(ScoringRecord, CandidatePost)
            .join(CandidatePost, CandidatePost.id == ScoringRecord.candidate_post_id)
            .where(
                ScoringRecord.stage == "final",
                ScoringRecord.passed.is_(True),
                ScoringRecord.scored_at >= since,
            )
            .order_by(ScoringRecord.score.desc().nulls_last())
            .limit(5)
        ).all()

        if not finals:
            return (
                f"📬 今日（{today.isoformat()}）尚未推送。\n"
                "過去 24 小時也沒有通過評分的候選——可能是 scheduler 剛起、"
                "或 Plan C 階段 RSS 訊號退化（沒有 score / comments）。\n"
                "用 /settings 看系統健康狀態。"
            )

        lines = [
            f"📬 今日（{today.isoformat()}）尚未推送。",
            "",
            f"近 24h 通過評分的候選 top {len(finals)}：",
            "",
        ]
        for i, (sr, c) in enumerate(finals, start=1):
            title = _escape_html((c.title or "(無標題)")[:80])
            url = _permalink_url(c)
            link_html = (
                f'<a href="{_escape_html(url)}">{title}</a>' if url else title
            )
            score = f"{sr.score:.2f}" if sr.score is not None else "—"
            lines.append(
                f"{i}. r/{_escape_html(c.subreddit)} · final={score}\n   {link_html}"
            )
        return "\n".join(lines)


def _digest_sync(user_id: int) -> str:
    """組 /digest 訊息：列出 user 自己 tracked_posts 過去 7 天的 milestone。"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    with session_scope() as session:
        rows = session.execute(
            select(RelatedPost, TrackedPost, CandidatePost)
            .join(TrackedPost, TrackedPost.id == RelatedPost.tracked_post_id)
            .join(CandidatePost, CandidatePost.id == TrackedPost.candidate_post_id)
            .where(
                TrackedPost.user_id == user_id,
                RelatedPost.is_milestone.is_(True),
                RelatedPost.discovered_at >= since,
            )
            .order_by(
                TrackedPost.id.asc(),
                RelatedPost.relevance_score.desc().nulls_last(),
                RelatedPost.discovered_at.desc(),
            )
        ).all()

        if not rows:
            owned = session.scalar(
                select(func.count(TrackedPost.id)).where(
                    TrackedPost.user_id == user_id,
                    TrackedPost.status == "active",
                )
            ) or 0
            if owned == 0:
                return "你還沒收藏任何貼文。用 ❤️ 收藏推送的貼文後，這裡會出現摘要。"
            return (
                f"📭 過去 7 天沒有任何 milestone。\n"
                f"目前 active 收藏 {owned} 篇。\n"
                "（Plan C 期間 detection 暫停，milestone 訊號只能等 OAuth 通過後恢復）"
            )

        grouped: dict[int, list[RelatedPost]] = {}
        meta: dict[int, tuple[TrackedPost, CandidatePost]] = {}
        for r, t, c in rows:
            grouped.setdefault(t.id, []).append(r)
            meta.setdefault(t.id, (t, c))

        lines = [f"📰 本週摘要（{len(rows)} 個 milestone，{len(grouped)} 篇收藏）", ""]
        for tid, items in grouped.items():
            t, c = meta[tid]
            title = _escape_html((c.title or "(無標題)")[:70])
            lines.append(
                f"<b>★ r/{_escape_html(c.subreddit)} · {title}</b>"
                f"  <code>/timeline {tid}</code>"
            )
            type_counts: dict[str, int] = {}
            for r in items:
                type_counts[r.relation_type] = type_counts.get(r.relation_type, 0) + 1
            summary = "、".join(
                f"{RELATION_LABELS.get(k, k)} ×{v}" for k, v in type_counts.items()
            )
            lines.append(f"  {summary}")
            for r in items[:3]:  # 每篇只列 top 3 milestone snippet
                snippet = _escape_html((r.content or "")[:120])
                ts = r.posted_at or r.discovered_at
                ts_str = _fmt_relative_time(ts, now) if ts else "?"
                label = RELATION_LABELS.get(r.relation_type, r.relation_type)
                lines.append(f"    {ts_str} · {label}: {snippet}")
            if len(items) > 3:
                lines.append(f"    …還有 {len(items) - 3} 筆，看 /timeline {tid}")
            lines.append("")
        return "\n".join(lines).rstrip()


def _settings_sync(user_id: int) -> str:
    """組 /settings 訊息：scraper mode + 系統健康 + 該 user 統計。"""
    s = get_settings()
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    plan_c_modes = {"rss"}
    scraper_label = {
        "public_json": "public JSON (anonymous)",
        "praw":        "PRAW (OAuth)",
        "rss":         "RSS fallback (Plan C)",
        "fake":        "Fake (dev)",
    }.get(s.reddit_scraper, s.reddit_scraper)
    in_plan_c = s.reddit_scraper in plan_c_modes

    with session_scope() as session:
        # 系統面（全體）
        cand_24h = session.scalar(
            select(func.count(CandidatePost.id)).where(
                CandidatePost.discovered_at >= since_24h
            )
        ) or 0
        rules_24h = session.scalar(
            select(func.count(ScoringRecord.id)).where(
                ScoringRecord.stage == "rules",
                ScoringRecord.scored_at >= since_24h,
            )
        ) or 0
        rules_pass_24h = session.scalar(
            select(func.count(ScoringRecord.id)).where(
                ScoringRecord.stage == "rules",
                ScoringRecord.passed.is_(True),
                ScoringRecord.scored_at >= since_24h,
            )
        ) or 0
        final_pass_24h = session.scalar(
            select(func.count(ScoringRecord.id)).where(
                ScoringRecord.stage == "final",
                ScoringRecord.passed.is_(True),
                ScoringRecord.scored_at >= since_24h,
            )
        ) or 0
        pushed_today = session.scalar(
            select(func.count(DailyPush.id)).where(
                DailyPush.push_date == _today_utc()
            )
        ) or 0

        # 個人面
        my_active = session.scalar(
            select(func.count(TrackedPost.id)).where(
                TrackedPost.user_id == user_id,
                TrackedPost.status == "active",
            )
        ) or 0
        my_archived = session.scalar(
            select(func.count(TrackedPost.id)).where(
                TrackedPost.user_id == user_id,
                TrackedPost.status == "archived",
            )
        ) or 0

    rules_rate = (rules_pass_24h / rules_24h * 100) if rules_24h else 0.0

    lines = [
        "⚙️ <b>系統設定</b>",
        f"  scraper：<code>{_escape_html(scraper_label)}</code>",
        f"  user_agent：<code>{_escape_html(s.reddit_user_agent)}</code>",
        f"  poll：sub={s.poll_subreddit_minutes}min · scoring={s.scoring_minutes}min"
        f" · breaking={s.breaking_check_minutes}min",
    ]
    if in_plan_c:
        lines.append(
            "  ⚠️ Plan C：keyword_discovery / detection / Q&A 暫停，等 OAuth 通過切回 PRAW"
        )
    lines.append("")
    lines.append("📊 <b>過去 24 小時</b>")
    lines.append(f"  新候選：{cand_24h}")
    lines.append(
        f"  rules 通過：{rules_pass_24h}/{rules_24h}（{rules_rate:.0f}%）"
    )
    lines.append(f"  final 通過：{final_pass_24h}")
    lines.append(f"  今日已推送：{pushed_today}")
    lines.append("")
    lines.append("👤 <b>你的狀態</b>")
    lines.append(f"  active 收藏：{my_active}")
    lines.append(f"  archived：{my_archived}")
    lines.append(f"  user_id：<code>{user_id}</code>")
    return "\n".join(lines)


async def feed_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    text = await asyncio.to_thread(_feed_today_sync, user.id)
    await msg.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def digest_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    text = await asyncio.to_thread(_digest_sync, user.id)
    await msg.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def settings_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    text = await asyncio.to_thread(_settings_sync, user.id)
    await msg.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


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


# ---------------------------------------------------------------------------
# M6 — /ask /exit + 自由文字路由
# ---------------------------------------------------------------------------


# 在第一次呼叫時 lazy-build；保留 module-level 以便 unit test 直接 patch
_CHAT_CLIENT: ChatClient | None = None


def _get_chat_client() -> ChatClient:
    global _CHAT_CLIENT
    if _CHAT_CLIENT is None:
        _CHAT_CLIENT = build_chat()
    return _CHAT_CLIENT


def _build_scraper_safe() -> RedditScraper | None:
    """組 system prompt 用，抓不到 scraper 就回 None（context 留空）。"""
    try:
        from ..scrapers.factory import build_scraper

        return build_scraper()
    except Exception as e:  # noqa: BLE001
        logger.warning("qa /ask: build_scraper failed: %s — comment tree 留空", e)
        return None


def _open_session_sync(
    user_id: int, tracked_id: int
) -> tuple[qa_service.OpenOutcome, int]:
    """同步包裝；回 (outcome, system_tokens_estimate)。"""
    scraper = _build_scraper_safe()
    try:
        with session_scope() as session:
            outcome = qa_service.open_session(
                session,
                user_id=user_id,
                tracked_post_id=tracked_id,
                scraper=scraper,
            )
            tokens = (
                outcome.state.system_tokens_estimate
                if outcome.state is not None
                else 0
            )
            return outcome, tokens
    finally:
        if scraper is not None:
            close = getattr(scraper, "close", None)
            if callable(close):
                close()


def _handle_qa_message_sync(user_id: int, text: str) -> qa_service.TurnOutcome:
    chat = _get_chat_client()
    with session_scope() as session:
        return qa_service.handle_message(
            session, user_id=user_id, text=text, chat=chat
        )


def _close_session_sync(user_id: int) -> qa_service.CloseOutcome:
    with session_scope() as session:
        return qa_service.close_session(session, user_id=user_id)


async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    args = ctx.args or []
    if not args:
        await msg.reply_text(
            "用法：/ask <tracked_id>。先用 /saved 看到 id。"
        )
        return
    try:
        tracked_id = int(args[0])
    except ValueError:
        await msg.reply_text("tracked_id 必須是整數。")
        return

    outcome, system_tokens = await asyncio.to_thread(
        _open_session_sync, user.id, tracked_id
    )
    if outcome.not_found:
        await msg.reply_text(f"找不到 tracked_post id={tracked_id}。")
        return
    if outcome.not_owner:
        await msg.reply_text("這篇不是你的收藏。")
        return
    if outcome.archived:
        await msg.reply_text("這篇已封存（archived），無法開問答模式。")
        return
    if outcome.already_active:
        existing_id = (
            outcome.state.tracked_post_id if outcome.state is not None else "?"
        )
        await msg.reply_text(
            f"你已經有一個進行中的問答（tracked={existing_id}）。"
            f"先 /exit 再 /ask <id> 換主題。"
        )
        return

    await msg.reply_text(
        f"✅ 已進入問答模式（tracked={tracked_id}, system≈{system_tokens} tokens）。\n"
        "可以直接打字提問；/exit 結束。5 分鐘沒動作會自動結束。"
    )


async def exit_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    outcome = await asyncio.to_thread(_close_session_sync, user.id)
    if outcome.not_in_session:
        await msg.reply_text("你目前沒有進行中的問答。")
        return
    await msg.reply_text(
        f"已結束問答（session={outcome.qa_session_id}，{outcome.turns} 輪對話）。"
    )


async def chat_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """active QA session 中的自由文字 — 走 chat；否則回提示。"""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None or not msg.text:
        return
    state = qa_service.get_active(user.id)
    if state is None:
        # 非 session 中收到自由文字 — 給最小提示，避免噪訊
        await msg.reply_text(
            "目前沒有進行中的問答。用 /ask <id> 開始，或 /help 看指令。"
        )
        return

    outcome = await asyncio.to_thread(_handle_qa_message_sync, user.id, msg.text)
    if outcome.not_in_session:
        # 與上面理論不會打到 — 防競態
        await msg.reply_text("問答 session 已結束，請重新 /ask <id>。")
        return
    if outcome.error:
        await msg.reply_text(f"問答出錯：{outcome.error}")
        return
    reply = outcome.reply or "(LLM 回了空訊息)"
    # Telegram 4096 限制；長回覆切到 3900 留 footer 空間
    if len(reply) > 3900:
        reply = reply[:3900] + "\n\n…（後續截斷）"
    footer = ""
    if outcome.cost_usd is not None:
        footer = (
            f"\n\n— in={outcome.input_tokens} out={outcome.output_tokens}"
            f" cost=${outcome.cost_usd:.4f}"
        )
    await msg.reply_text(reply + footer)


__all__ = [
    "ACTION_REPLIES",
    "DUPLICATE_REPLY",
    "HELP_TEXT",
    "INVALID_REPLY",
    "MISSING_REPLY",
    "_close_session_sync",
    "_digest_sync",
    "_feed_today_sync",
    "_handle_qa_message_sync",
    "_open_session_sync",
    "_record_feedback_sync",
    "_saved_list_sync",
    "_settings_sync",
    "_timeline_sync",
    "ask_cmd",
    "chat_message",
    "deferred_cmd",
    "digest_cmd",
    "exit_cmd",
    "feed_cmd",
    "feedback_callback",
    "help_cmd",
    "saved_cmd",
    "settings_cmd",
    "start_cmd",
    "timeline_cmd",
]
