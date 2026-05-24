"""M6 bot handlers — /ask /exit + chat_message。

Async handler 與 sync DB 之間用 asyncio.to_thread 橋接，這層測試重點：
- /ask 各拒絕路徑回對應訊息（not_found / not_owner / archived / already_active）
- /ask 成功時開啟 session 後跟 chat_message 多輪互動可用
- /exit 結束時 in-memory state 與 DB row 都更新
- 沒有 active session 時 chat_message 不打 LLM
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reddit_tracker.bot import handlers
from reddit_tracker.llm.minimax_chat import FakeChat
from reddit_tracker.models import CandidatePost, TrackedPost
from reddit_tracker.services import qa as qa_service


NOW = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_state():
    qa_service.reset_state()
    yield
    qa_service.reset_state()


def _persist_tracked_in_session(session, *, user_id: int = 7) -> TrackedPost:
    c = CandidatePost(
        reddit_post_id="rid1",
        subreddit="Taiwan",
        title="t",
        selftext="x" * 80,
        permalink="/r/Taiwan/comments/rid1/x/",
        author_username="alice",
        author_karma=300,
        posted_at=NOW - timedelta(hours=4),
        initial_score=100,
        initial_num_comments=8,
        upvote_ratio=0.9,
    )
    session.add(c)
    session.flush()
    t = TrackedPost(
        candidate_post_id=c.id, user_id=user_id, polling_tier="hot", status="active"
    )
    session.add(t)
    session.flush()
    session.commit()
    return t


def _make_update(text: str = "", user_id: int = 7, has_message: bool = True):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    if has_message:
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()
        update.effective_message.text = text
    else:
        update.effective_message = None
    return update


def _make_ctx(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ---------------------------------------------------------------------------
# /ask — 拒絕路徑
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_requires_arg():
    update = _make_update()
    await handlers.ask_cmd(update, _make_ctx(args=[]))
    update.effective_message.reply_text.assert_awaited_once()
    args, _ = update.effective_message.reply_text.call_args
    assert "用法：/ask" in args[0]


@pytest.mark.asyncio
async def test_ask_rejects_non_integer():
    update = _make_update()
    await handlers.ask_cmd(update, _make_ctx(args=["abc"]))
    args, _ = update.effective_message.reply_text.call_args
    assert "必須是整數" in args[0]


@pytest.mark.asyncio
async def test_ask_not_found():
    update = _make_update(user_id=7)
    fake = qa_service.OpenOutcome(state=None, not_found=True)
    with patch.object(
        handlers, "_open_session_sync", return_value=(fake, 0)
    ):
        await handlers.ask_cmd(update, _make_ctx(args=["99999"]))
    args, _ = update.effective_message.reply_text.call_args
    assert "找不到" in args[0]


@pytest.mark.asyncio
async def test_ask_not_owner():
    update = _make_update(user_id=7)
    fake = qa_service.OpenOutcome(state=None, not_owner=True)
    with patch.object(handlers, "_open_session_sync", return_value=(fake, 0)):
        await handlers.ask_cmd(update, _make_ctx(args=["42"]))
    args, _ = update.effective_message.reply_text.call_args
    assert "不是你的收藏" in args[0]


@pytest.mark.asyncio
async def test_ask_archived():
    update = _make_update(user_id=7)
    fake = qa_service.OpenOutcome(state=None, archived=True)
    with patch.object(handlers, "_open_session_sync", return_value=(fake, 0)):
        await handlers.ask_cmd(update, _make_ctx(args=["42"]))
    args, _ = update.effective_message.reply_text.call_args
    assert "已封存" in args[0]


@pytest.mark.asyncio
async def test_ask_already_active():
    update = _make_update(user_id=7)
    state = qa_service.QASessionState(
        user_id=7, tracked_post_id=42, qa_session_id=1, system_prompt="x"
    )
    fake = qa_service.OpenOutcome(state=state, already_active=True)
    with patch.object(handlers, "_open_session_sync", return_value=(fake, 100)):
        await handlers.ask_cmd(update, _make_ctx(args=["99"]))
    args, _ = update.effective_message.reply_text.call_args
    assert "已經有一個進行中的問答" in args[0]


@pytest.mark.asyncio
async def test_ask_success_replies_with_tokens():
    update = _make_update(user_id=7)
    state = qa_service.QASessionState(
        user_id=7,
        tracked_post_id=42,
        qa_session_id=1,
        system_prompt="x",
        system_tokens_estimate=1234,
    )
    fake = qa_service.OpenOutcome(state=state)
    with patch.object(
        handlers, "_open_session_sync", return_value=(fake, 1234)
    ):
        await handlers.ask_cmd(update, _make_ctx(args=["42"]))
    args, _ = update.effective_message.reply_text.call_args
    assert "已進入問答模式" in args[0]
    assert "1234" in args[0]


# ---------------------------------------------------------------------------
# /exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_when_no_session():
    update = _make_update(user_id=7)
    out = qa_service.CloseOutcome(closed=False, not_in_session=True)
    with patch.object(handlers, "_close_session_sync", return_value=out):
        await handlers.exit_cmd(update, _make_ctx())
    args, _ = update.effective_message.reply_text.call_args
    assert "沒有進行中" in args[0]


@pytest.mark.asyncio
async def test_exit_success():
    update = _make_update(user_id=7)
    out = qa_service.CloseOutcome(closed=True, qa_session_id=9, turns=3)
    with patch.object(handlers, "_close_session_sync", return_value=out):
        await handlers.exit_cmd(update, _make_ctx())
    args, _ = update.effective_message.reply_text.call_args
    assert "已結束問答" in args[0]
    assert "session=9" in args[0]
    assert "3 輪" in args[0]


# ---------------------------------------------------------------------------
# chat_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_message_no_session_replies_hint():
    update = _make_update(text="嗨", user_id=7)
    # state 為 None — 不應該呼到 _handle_qa_message_sync
    with patch.object(handlers, "_handle_qa_message_sync") as wr:
        await handlers.chat_message(update, _make_ctx())
    wr.assert_not_called()
    args, _ = update.effective_message.reply_text.call_args
    assert "沒有進行中的問答" in args[0]


@pytest.mark.asyncio
async def test_chat_message_active_session_replies(monkeypatch):
    # 用真實 in-memory state 觸發 active path
    state = qa_service.QASessionState(
        user_id=7, tracked_post_id=42, qa_session_id=1, system_prompt="ctx"
    )
    qa_service._set_active(state)
    out = qa_service.TurnOutcome(
        reply="這是回答", cost_usd=0.0005, input_tokens=1500, output_tokens=80
    )
    with patch.object(handlers, "_handle_qa_message_sync", return_value=out) as wr:
        await handlers.chat_message(_make_update(text="這篇怎麼回事？"), _make_ctx())
    wr.assert_called_once_with(7, "這篇怎麼回事？")


@pytest.mark.asyncio
async def test_chat_message_error_shows_message():
    state = qa_service.QASessionState(
        user_id=7, tracked_post_id=42, qa_session_id=1, system_prompt="ctx"
    )
    qa_service._set_active(state)
    out = qa_service.TurnOutcome(reply=None, error="upstream timeout")
    update = _make_update(text="hi")
    with patch.object(handlers, "_handle_qa_message_sync", return_value=out):
        await handlers.chat_message(update, _make_ctx())
    args, _ = update.effective_message.reply_text.call_args
    assert "upstream timeout" in args[0]


@pytest.mark.asyncio
async def test_chat_message_long_reply_truncated():
    state = qa_service.QASessionState(
        user_id=7, tracked_post_id=42, qa_session_id=1, system_prompt="ctx"
    )
    qa_service._set_active(state)
    long_reply = "a" * 5000
    out = qa_service.TurnOutcome(reply=long_reply, input_tokens=10, output_tokens=10, cost_usd=0.0)
    update = _make_update(text="hi")
    with patch.object(handlers, "_handle_qa_message_sync", return_value=out):
        await handlers.chat_message(update, _make_ctx())
    args, _ = update.effective_message.reply_text.call_args
    body = args[0]
    # 截斷尾註存在
    assert "後續截斷" in body
    # 內容 + 尾註合計 < 4096（telegram 限制）
    assert len(body) < 4096


# ---------------------------------------------------------------------------
# 整合：真實 session（用 in-memory DB + FakeChat）跑一輪
# ---------------------------------------------------------------------------


def test_sync_open_and_close_round_trip(monkeypatch, tmp_path):
    """直接驗 _open_session_sync + _close_session_sync 在真實 session_scope 下流通。"""
    from sqlalchemy import create_engine
    from reddit_tracker.models import Base
    from reddit_tracker import db as db_mod

    db_url = f"sqlite:///{tmp_path}/qa.db"
    eng = create_engine(db_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db_mod, "_engine", eng, raising=False)
    monkeypatch.setattr(db_mod, "_SessionLocal", None, raising=False)

    # 寫一筆 tracked + candidate
    with db_mod.session_scope() as s:
        t = _persist_tracked_in_session(s, user_id=7)
        tracked_id = t.id

    # 走 _open_session_sync
    monkeypatch.setattr(handlers, "_build_scraper_safe", lambda: None)
    outcome, tokens = handlers._open_session_sync(7, tracked_id)
    assert outcome.state is not None
    assert tokens > 0
    assert qa_service.get_active(7) is not None

    # FakeChat 替掉 _get_chat_client
    fake = FakeChat()
    monkeypatch.setattr(handlers, "_get_chat_client", lambda: fake)
    turn = handlers._handle_qa_message_sync(7, "你怎麼看？")
    assert turn.reply

    close_out = handlers._close_session_sync(7)
    assert close_out.closed
    assert qa_service.get_active(7) is None
