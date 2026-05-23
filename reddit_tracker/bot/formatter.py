"""推送訊息格式器（M4.4）— 純函式，無 I/O，便於測試。

format_push_message(pick) → (html_text, InlineKeyboardMarkup)

訊息使用 Telegram HTML parse mode（escape 集合只有 `<` `>` `&`，比 Markdown 穩定）。
caller 端送出時帶 `parse_mode="HTML"`。

按鈕 callback_data 編碼：`fb:<action>:<candidate_post_id>`
  ↑↑                   ↑↑
  prefix (識別本 bot)   單字節 action（c/d/m），給 Telegram 64-byte 上限留 buffer
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..services.feed import FeedPick
from ..services.notification import DigestEntry, PendingMilestone


# 按鈕 callback_data 設計：盡量短，Telegram 限制 1–64 bytes。
CALLBACK_PREFIX = "fb"
ACTION_COLLECT = "c"     # ❤️ → Feedback.action = 'collect'
ACTION_DISLIKE = "d"     # 👎 → 'dislike'
ACTION_MUTE = "m"        # 🔕 → 'mute_author'

ACTION_TO_FEEDBACK = {
    ACTION_COLLECT: "collect",
    ACTION_DISLIKE: "dislike",
    ACTION_MUTE: "mute_author",
}

PUSH_TYPE_HEADERS = {
    "already_hot": "🔥 已爆貼",
    "early_bet": "⚡ 早期下注",
    "breaking": "🚨 即時破例",
}


def encode_callback(action: str, candidate_id: int) -> str:
    return f"{CALLBACK_PREFIX}:{action}:{candidate_id}"


def decode_callback(data: str | None) -> tuple[str, int] | None:
    """parse `fb:<action>:<int>`，格式錯誤回 None（caller 自行決定回應）。"""
    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


def _permalink_url(permalink: str | None) -> str | None:
    if not permalink:
        return None
    if permalink.startswith("http"):
        return permalink
    return f"https://www.reddit.com{permalink}"


def _escape_html(text: str) -> str:
    """Telegram HTML 的逃逸：& < > 三個字元（attribute 內還需 \"，本格式只在 href 用）。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_push_message(pick: FeedPick) -> tuple[str, InlineKeyboardMarkup]:
    """組訊息文字 + 三按鈕鍵盤（Telegram HTML parse mode）。

    格式：
        🔥 已爆貼 #1
        r/Taiwan · u/alice · karma 500

        <b>標題</b>

        互動 120 ⬆ / 45 💬 · velocity 33
        semantic 0.78 · final 0.74

        <a href="https://...">原文連結</a>
    """
    c = pick.candidate
    header = PUSH_TYPE_HEADERS.get(pick.push_type, pick.push_type)
    title = _escape_html(c.title or "(無標題)")

    meta_bits = [
        f"r/{_escape_html(c.subreddit)}",
        f"u/{_escape_html(c.author_username or '?')}",
    ]
    if c.author_karma is not None:
        meta_bits.append(f"karma {c.author_karma:,}")
    meta_line = " · ".join(meta_bits)

    lines: list[str] = [
        f"{header} #{pick.rank}",
        meta_line,
        "",
        f"<b>{title}</b>",
    ]

    ups = c.initial_score or 0
    comments = c.initial_num_comments or 0
    stats_bits = [f"互動 {ups:,} ⬆ / {comments:,} 💬"]
    if pick.velocity is not None:
        stats_bits.append(f"velocity {pick.velocity:.0f}")
    lines.append("")
    lines.append(" · ".join(stats_bits))

    score_bits: list[str] = []
    if pick.semantic is not None:
        score_bits.append(f"semantic {pick.semantic:.2f}")
    if pick.final_score is not None:
        score_bits.append(f"final {pick.final_score:.2f}")
    if score_bits:
        lines.append(" · ".join(score_bits))

    link = _permalink_url(c.permalink)
    if link:
        lines.append("")
        # href 內也要 escape & < >（同 _escape_html 邏輯），但不需 escape "（URL 不含 "）
        lines.append(f'<a href="{_escape_html(link)}">原文連結</a>')

    text = "\n".join(lines)

    buttons = [
        [
            InlineKeyboardButton("❤️ 收藏", callback_data=encode_callback(ACTION_COLLECT, c.id)),
            InlineKeyboardButton("👎 跳過", callback_data=encode_callback(ACTION_DISLIKE, c.id)),
            InlineKeyboardButton("🔕 靜音", callback_data=encode_callback(ACTION_MUTE, c.id)),
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)


RELATION_LABELS = {
    "author_followup": "📝 作者新貼文",
    "author_reply": "💬 原作回覆",
    "hot_reply": "🔥 高熱度留言",
    "crosspost": "🔁 被轉貼",
}


def _candidate_link(c) -> str | None:
    link = _permalink_url(c.permalink)
    if link is None:
        return None
    return f'<a href="{_escape_html(link)}">原文</a>'


def format_milestone_message(pending: PendingMilestone) -> str:
    """單筆 milestone 的即時推送訊息（M5.8）。

    無按鈕 — milestone 不需 collect/dislike，使用者已經收藏這篇了。
    """
    c, t, r = pending.candidate, pending.tracked, pending.related  # noqa: F841
    label = RELATION_LABELS.get(r.relation_type, r.relation_type)
    title = _escape_html(c.title or "(無標題)")
    lines = [
        f"🎯 收藏追蹤 · {label}",
        f"r/{_escape_html(c.subreddit)} · u/{_escape_html(c.author_username or '?')}",
        "",
        f"<b>{title}</b>",
        "",
        _escape_html((r.content or "")[:500]),
    ]
    link = _candidate_link(c)
    if link:
        lines += ["", link]
    return "\n".join(lines)


def format_digest_message(entries: list[DigestEntry]) -> str:
    """彙整訊息（M5.8）— 一封訊息整理今日所有 tracked 的非-milestone 後續事件。"""
    if not entries:
        return ""
    lines = [f"📰 收藏追蹤 · 今日彙整（{len(entries)} 篇）", ""]
    for i, e in enumerate(entries, start=1):
        title = _escape_html(e.candidate.title or "(無標題)")
        lines.append(f"<b>{i}. r/{_escape_html(e.candidate.subreddit)} · {title}</b>")
        link = _permalink_url(e.candidate.permalink)
        if link:
            lines.append(f'   <a href="{_escape_html(link)}">原文</a>')
        for r in e.related:
            label = RELATION_LABELS.get(r.relation_type, r.relation_type)
            snippet = _escape_html((r.content or "")[:140])
            lines.append(f"   • {label}: {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip()


__all__ = [
    "ACTION_COLLECT",
    "ACTION_DISLIKE",
    "ACTION_MUTE",
    "ACTION_TO_FEEDBACK",
    "CALLBACK_PREFIX",
    "PUSH_TYPE_HEADERS",
    "RELATION_LABELS",
    "decode_callback",
    "encode_callback",
    "format_digest_message",
    "format_milestone_message",
    "format_push_message",
]
