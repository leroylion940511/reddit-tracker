"""SCHEDULE.md M4.4 — 訊息格式器 + callback_data 編解碼測試。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from reddit_tracker.bot.formatter import (
    ACTION_COLLECT,
    ACTION_DISLIKE,
    ACTION_MUTE,
    CALLBACK_PREFIX,
    PUSH_TYPE_HEADERS,
    decode_callback,
    encode_callback,
    format_push_message,
)
from reddit_tracker.models import CandidatePost
from reddit_tracker.services.feed import FeedPick


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


def _pick(
    *,
    push_type: str = "already_hot",
    rank: int = 1,
    title: str = "事件記錄",
    permalink: str | None = "/r/Taiwan/comments/abc1/x/",
    karma: int | None = 500,
    velocity: float | None = 33.0,
    semantic: float | None = 0.78,
    final_score: float | None = 0.74,
) -> FeedPick:
    c = CandidatePost(
        id=42,
        reddit_post_id="abc1",
        subreddit="Taiwan",
        title=title,
        selftext="x" * 100,
        permalink=permalink,
        author_username="alice",
        author_karma=karma,
        author_created_utc=NOW - timedelta(days=180),
        posted_at=NOW - timedelta(hours=8),
        initial_score=120,
        initial_num_comments=45,
        upvote_ratio=0.9,
        lang="zh",
        meta_json={},
    )
    return FeedPick(
        candidate_post_id=c.id,
        candidate=c,
        push_type=push_type,
        rank=rank,
        velocity=velocity,
        semantic=semantic,
        final_score=final_score,
    )


# ---------------------------------------------------------------------------
# encode / decode callback_data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", [ACTION_COLLECT, ACTION_DISLIKE, ACTION_MUTE])
def test_encode_decode_roundtrip(action):
    data = encode_callback(action, 12345)
    assert data.startswith(f"{CALLBACK_PREFIX}:")
    assert decode_callback(data) == (action, 12345)


def test_decode_rejects_none():
    assert decode_callback(None) is None
    assert decode_callback("") is None


def test_decode_rejects_bad_prefix():
    assert decode_callback("xx:c:42") is None


def test_decode_rejects_wrong_field_count():
    assert decode_callback("fb:c") is None
    assert decode_callback("fb:c:42:extra") is None


def test_decode_rejects_non_integer_id():
    assert decode_callback("fb:c:notanumber") is None


def test_callback_data_under_64_bytes():
    # Telegram 限制 callback_data ≤ 64 bytes；用一個大的 candidate id 試
    data = encode_callback(ACTION_COLLECT, 9_999_999_999_999)
    assert len(data.encode("utf-8")) <= 64


# ---------------------------------------------------------------------------
# format_push_message — 內容
# ---------------------------------------------------------------------------


def test_format_already_hot_basic():
    text, kbd = format_push_message(_pick(push_type="already_hot", rank=2))
    assert PUSH_TYPE_HEADERS["already_hot"] in text
    assert "#2" in text
    assert "r/Taiwan" in text
    assert "u/alice" in text
    assert "karma 500" in text
    assert "<b>事件記錄</b>" in text
    assert "互動 120 ⬆ / 45 💬" in text
    assert "velocity 33" in text
    assert "semantic 0.78" in text
    assert "final 0.74" in text
    assert '<a href="https://www.reddit.com/r/Taiwan/comments/abc1/x/">原文連結</a>' in text
    assert kbd.inline_keyboard[0][0].text.startswith("❤️")
    assert kbd.inline_keyboard[0][1].text.startswith("👎")
    assert kbd.inline_keyboard[0][2].text.startswith("🔕")


def test_format_early_bet_header():
    text, _ = format_push_message(_pick(push_type="early_bet"))
    assert PUSH_TYPE_HEADERS["early_bet"] in text


def test_format_breaking_header():
    text, _ = format_push_message(_pick(push_type="breaking"))
    assert PUSH_TYPE_HEADERS["breaking"] in text


def test_format_buttons_have_correct_callback_data():
    pick = _pick()
    _, kbd = format_push_message(pick)
    actions = [
        decode_callback(btn.callback_data)
        for btn in kbd.inline_keyboard[0]
    ]
    assert actions == [
        (ACTION_COLLECT, pick.candidate_post_id),
        (ACTION_DISLIKE, pick.candidate_post_id),
        (ACTION_MUTE, pick.candidate_post_id),
    ]


def test_format_handles_missing_optional_fields():
    """karma / semantic / final / permalink 都 None 也不能炸。"""
    pick = _pick(karma=None, semantic=None, final_score=None, permalink=None)
    text, kbd = format_push_message(pick)
    # 不應該出現 karma / semantic / final / 原文連結 區段
    assert "karma" not in text
    assert "semantic" not in text
    assert "final" not in text
    assert "原文連結" not in text
    # 但基本欄位仍在
    assert "r/Taiwan" in text
    assert "u/alice" in text
    assert len(kbd.inline_keyboard[0]) == 3


def test_format_no_velocity_omits_velocity_segment():
    text, _ = format_push_message(_pick(velocity=None))
    assert "velocity" not in text


def test_format_escapes_html_in_title():
    text, _ = format_push_message(_pick(title="reaction to <script> & </b>"))
    # < > & 必須被逃逸；不能出現原始 <script> / </b>
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text
    assert "&lt;/b&gt;" in text


def test_format_escapes_html_in_subreddit_and_user():
    """很罕見但 username 也可能含 < — 一律 escape。"""
    pick = _pick()
    pick.candidate.subreddit = "sub<x>"
    pick.candidate.author_username = "user&me"
    text, _ = format_push_message(pick)
    assert "r/sub&lt;x&gt;" in text
    assert "u/user&amp;me" in text


def test_format_absolute_permalink_passthrough():
    text, _ = format_push_message(_pick(permalink="https://example.com/x"))
    assert '<a href="https://example.com/x">原文連結</a>' in text


def test_format_empty_title_replaced():
    text, _ = format_push_message(_pick(title=""))
    assert "(無標題)" in text
