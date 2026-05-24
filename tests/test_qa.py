"""M6 — services/qa.py (session state machine + context assembler)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from reddit_tracker.llm.minimax_chat import FakeChat
from reddit_tracker.models import (
    CandidatePost,
    LLMRecord,
    PostSnapshot,
    QAMessage,
    QASession,
    RelatedPost,
    TrackedPost,
)
from reddit_tracker.scrapers.base import CommentNode
from reddit_tracker.scrapers.fake import FakeScraper
from reddit_tracker.services import qa as qa_service


NOW = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state():
    """每個 test 開始前先清 in-memory active session 字典。"""
    qa_service.reset_state()
    yield
    qa_service.reset_state()


def _persist_tracked(
    session,
    *,
    user_id: int = 7,
    rid: str = "abc",
    status: str = "active",
    author: str = "alice",
    title: str = "我家貓會講話",
    selftext: str = "前情提要：我家貓會講話。",
    subreddit: str = "Taiwan",
) -> TrackedPost:
    c = CandidatePost(
        reddit_post_id=rid,
        subreddit=subreddit,
        title=title,
        selftext=selftext,
        permalink=f"/r/{subreddit}/comments/{rid}/x/",
        author_username=author,
        author_karma=500,
        posted_at=NOW - timedelta(hours=8),
        initial_score=120,
        initial_num_comments=18,
        upvote_ratio=0.93,
    )
    session.add(c)
    session.flush()
    t = TrackedPost(
        candidate_post_id=c.id,
        user_id=user_id,
        polling_tier="hot",
        status=status,
    )
    session.add(t)
    session.flush()
    return t


def _add_snapshot(session, tracked_id: int, **fields):
    snap = PostSnapshot(tracked_post_id=tracked_id, **fields)
    session.add(snap)
    session.flush()
    return snap


def _add_related(session, tracked_id: int, **fields):
    fields.setdefault("relation_type", "hot_reply")
    fields.setdefault("relevance_score", 100.0)
    fields.setdefault("content", "fake content")
    rp = RelatedPost(tracked_post_id=tracked_id, **fields)
    session.add(rp)
    session.flush()
    return rp


# ---------------------------------------------------------------------------
# context assembler
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_post_snapshots_related(session):
    t = _persist_tracked(session)
    _add_snapshot(
        session,
        t.id,
        captured_at=NOW - timedelta(hours=4),
        score=200,
        num_comments=30,
        upvote_ratio=0.94,
    )
    _add_related(
        session,
        t.id,
        relation_type="hot_reply",
        reddit_post_id="cm1",
        relevance_score=180.0,
        is_milestone=False,
        content="這篇我也遇過 (score=180)",
    )
    _add_related(
        session,
        t.id,
        relation_type="crosspost",
        reddit_post_id="xpost1",
        relevance_score=300.0,
        is_milestone=True,
        content="[crosspost r/HongKong score=300] 我家貓會講話",
    )
    prompt, kept = qa_service.build_system_prompt(session, t.id, scraper=None)
    assert "[ORIGINAL POST]" in prompt
    assert "r/Taiwan" in prompt
    assert "我家貓會講話" in prompt
    assert "[SNAPSHOTS]" in prompt
    assert "score=200" in prompt
    assert "[RELATED EVENTS]" in prompt
    assert "高熱度留言" in prompt
    assert "跨 sub 轉貼" in prompt
    assert "[COMMENT TREE]" in prompt
    assert kept == 0


def test_build_system_prompt_with_scraper_includes_comments(session):
    t = _persist_tracked(session, rid="abc1")
    scraper = FakeScraper(corpus=[])
    # 直接餵一棵小樹給 FakeScraper（不靠 corpus，需 monkey-patch 一個 fetch_comment_tree）
    sample = [
        CommentNode(
            comment_id="c1", parent_id="t3_abc1", author="bob", body="加一",
            score=42, created_utc=NOW, depth=0, is_submitter=False,
        ),
        CommentNode(
            comment_id="c2", parent_id="t3_abc1", author="alice", body="OP補充：",
            score=15, created_utc=NOW, depth=0, is_submitter=True,
        ),
    ]
    scraper.fetch_comment_tree = lambda post_id, limit=500, depth=10: sample
    prompt, kept = qa_service.build_system_prompt(session, t.id, scraper=scraper)
    assert kept == 2
    assert "[COMMENT TREE] 共 2 節點" in prompt
    assert "bob" in prompt
    assert "[OP]" in prompt


def test_build_system_prompt_trims_when_over_budget(session):
    t = _persist_tracked(session, rid="big")
    big_body = "中文很長很長很長很長很長很長很長很長很長" * 30
    sample = [
        CommentNode(
            comment_id=f"c{i:03d}",
            parent_id="t3_big",
            author=f"u{i}",
            body=big_body,
            score=10 + i,
            created_utc=NOW,
            depth=0,
            is_submitter=False,
        )
        for i in range(200)
    ]
    scraper = FakeScraper(corpus=[])
    scraper.fetch_comment_tree = lambda post_id, limit=500, depth=10: sample
    prompt, kept = qa_service.build_system_prompt(
        session, t.id, scraper=scraper, token_budget=2000
    )
    assert kept == qa_service.COMMENT_TRIM_TOP_N
    assert "trimmed to top" in prompt


def test_build_system_prompt_scraper_error_falls_back_to_empty(session):
    t = _persist_tracked(session)

    class _Boom(FakeScraper):
        def fetch_comment_tree(self, post_id, *, limit=500, depth=10):
            raise RuntimeError("boom")

    prompt, kept = qa_service.build_system_prompt(
        session, t.id, scraper=_Boom(corpus=[])
    )
    assert kept == 0
    assert "[COMMENT TREE]" in prompt
    assert "(無留言)" in prompt


def test_build_system_prompt_not_found(session):
    with pytest.raises(LookupError):
        qa_service.build_system_prompt(session, 99999)


# ---------------------------------------------------------------------------
# open_session
# ---------------------------------------------------------------------------


def test_open_session_creates_db_and_state(session):
    t = _persist_tracked(session, user_id=7)
    outcome = qa_service.open_session(
        session, user_id=7, tracked_post_id=t.id, scraper=None
    )
    assert outcome.state is not None
    assert outcome.state.user_id == 7
    assert outcome.state.tracked_post_id == t.id
    # DB row 寫了
    rows = session.scalars(select(QASession)).all()
    assert len(rows) == 1
    assert rows[0].state == "active"
    # in-memory state 寫了
    assert qa_service.get_active(7) is not None


def test_open_session_already_active_returns_existing(session):
    t = _persist_tracked(session, user_id=7)
    out1 = qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    out2 = qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    assert out2.already_active
    assert out2.state is out1.state


def test_open_session_not_owner(session):
    t = _persist_tracked(session, user_id=7)
    out = qa_service.open_session(session, user_id=99, tracked_post_id=t.id)
    assert out.not_owner
    assert out.state is None


def test_open_session_archived_rejected(session):
    t = _persist_tracked(session, user_id=7, status="archived")
    out = qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    assert out.archived
    assert out.state is None


def test_open_session_not_found(session):
    out = qa_service.open_session(session, user_id=7, tracked_post_id=42424)
    assert out.not_found


# ---------------------------------------------------------------------------
# handle_message
# ---------------------------------------------------------------------------


def test_handle_message_writes_db_and_history(session):
    t = _persist_tracked(session, user_id=7)
    qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    chat = FakeChat()
    out = qa_service.handle_message(
        session, user_id=7, text="這篇怎麼還沒爆？", chat=chat
    )
    assert out.reply and out.reply.startswith("(fake reply)")
    msgs = session.scalars(
        select(QAMessage).order_by(QAMessage.id.asc())
    ).all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "這篇怎麼還沒爆？"
    assert msgs[1].input_tokens == 1500
    # llm_records 寫了
    lrs = session.scalars(select(LLMRecord)).all()
    assert len(lrs) == 1
    assert lrs[0].purpose == "qa"
    assert lrs[0].provider == "fake"
    # history kept
    state = qa_service.get_active(7)
    assert [h["role"] for h in state.history] == ["user", "assistant"]


def test_handle_message_no_session(session):
    out = qa_service.handle_message(
        session, user_id=1, text="hi", chat=FakeChat()
    )
    assert out.not_in_session
    assert out.reply is None


def test_handle_message_chat_failure_rolls_back_history(session):
    t = _persist_tracked(session, user_id=7)
    qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    chat = FakeChat(raise_exc=RuntimeError("upstream down"))
    out = qa_service.handle_message(
        session, user_id=7, text="嗨", chat=chat
    )
    assert out.error == "upstream down"
    state = qa_service.get_active(7)
    assert state.history == []  # rollback
    # user row 仍寫入（追蹤已嘗試對話）
    msgs = session.scalars(select(QAMessage)).all()
    assert len(msgs) == 1
    assert msgs[0].role == "user"


def test_handle_message_multi_turn_history_grows(session):
    t = _persist_tracked(session, user_id=7)
    qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    chat = FakeChat()
    qa_service.handle_message(session, user_id=7, text="第一輪", chat=chat)
    qa_service.handle_message(session, user_id=7, text="第二輪", chat=chat)
    state = qa_service.get_active(7)
    assert [h["content"] for h in state.history] == [
        "第一輪",
        state.history[1]["content"],
        "第二輪",
        state.history[3]["content"],
    ]
    # FakeChat 第二輪收到的 messages 應包含上一輪 assistant
    last_call_messages = chat.calls[-1][1]
    assert any(m["role"] == "assistant" for m in last_call_messages)


# ---------------------------------------------------------------------------
# close_session / sweep_idle
# ---------------------------------------------------------------------------


def test_close_session_writes_ended_at(session):
    t = _persist_tracked(session, user_id=7)
    qa_service.open_session(session, user_id=7, tracked_post_id=t.id)
    qa_service.handle_message(
        session, user_id=7, text="一句話", chat=FakeChat()
    )
    out = qa_service.close_session(session, user_id=7, now=NOW)
    assert out.closed
    assert out.turns == 1
    row = session.get(QASession, out.qa_session_id)
    assert row.state == "ended"
    # SQLite 不保 tzinfo；和 NOW 比較時去掉 tz 再對齊
    assert row.ended_at is not None and row.ended_at.replace(tzinfo=timezone.utc) == NOW
    assert qa_service.get_active(7) is None


def test_close_session_not_in_session(session):
    out = qa_service.close_session(session, user_id=99)
    assert not out.closed
    assert out.not_in_session


def test_sweep_idle_closes_stale_only(session):
    t1 = _persist_tracked(session, user_id=1, rid="aaa")
    t2 = _persist_tracked(session, user_id=2, rid="bbb")
    qa_service.open_session(session, user_id=1, tracked_post_id=t1.id, now=NOW)
    qa_service.open_session(session, user_id=2, tracked_post_id=t2.id, now=NOW)

    # 把 user_id=1 的 last_active_at 拉到 10 分鐘前
    qa_service.get_active(1).last_active_at = NOW - timedelta(minutes=10)

    closed = qa_service.sweep_idle(session, ttl_seconds=300, now=NOW)
    assert closed == [1]
    assert qa_service.get_active(1) is None
    assert qa_service.get_active(2) is not None
    row = session.scalar(
        select(QASession).where(QASession.user_id == 1)
    )
    assert row.state == "ended_idle"
    assert row.ended_at is not None and row.ended_at.replace(tzinfo=timezone.utc) == NOW


def test_sweep_idle_empty_returns_empty(session):
    assert qa_service.sweep_idle(session, now=NOW) == []
