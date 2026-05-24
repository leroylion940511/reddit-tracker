"""M6.x 端到端 smoke — QA 問答層。

流程：
  1. 建 1 篇 candidate + promote_to_tracked
  2. 寫一筆 snapshot + 兩筆 related event 模擬 M5 偵測結果
  3. 用 RichFakeScraper 提供 comment tree
  4. open_session 組重量 system prompt（印出長度 / 行數）
  5. FakeChat 跑 2 輪對話，驗 history + qa_messages + llm_records 寫入
  6. sweep_idle 強制收掉（or close_session 手動）→ 驗 ended_at + state

不打真實網路、不送 Telegram、不需要 MINIMAX_API_KEY。

用：uv run python scripts/m6_smoke.py
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select               # noqa: E402
from sqlalchemy.orm import sessionmaker                    # noqa: E402

from reddit_tracker.llm.minimax_chat import FakeChat       # noqa: E402
from reddit_tracker.models import (                        # noqa: E402
    Base,
    CandidatePost,
    LLMRecord,
    PostSnapshot,
    QAMessage,
    QASession,
    RelatedPost,
)
from reddit_tracker.scrapers.base import CommentNode       # noqa: E402
from reddit_tracker.scrapers.fake import FakeScraper       # noqa: E402
from reddit_tracker.services import qa as qa_service       # noqa: E402
from reddit_tracker.services.promotion import promote_to_tracked  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("m6_smoke")

NOW = datetime.now(timezone.utc)


def _comment(cid, *, author="bob", body="...", score=5, is_op=False, hours_ago=1.0,
             depth=0):
    return CommentNode(
        comment_id=cid, parent_id="t3_orig", author=author, body=body,
        score=score, created_utc=NOW - timedelta(hours=hours_ago),
        depth=depth, is_submitter=is_op,
    )


class TreeFakeScraper(FakeScraper):
    def __init__(self, *, comments):
        super().__init__(corpus=[])
        self._comments = comments

    def fetch_comment_tree(self, post_id, *, limit=500, depth=10):
        return self._comments


def run() -> int:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # Step 1 — candidate + tracked
    with Session() as s:
        c = CandidatePost(
            reddit_post_id="orig",
            subreddit="Taiwan",
            title="颱風天買到的便當",
            selftext="店家還開著，老闆說滷雞腿做了一整鍋。",
            permalink="/r/Taiwan/comments/orig/typhoon/",
            author_username="alice",
            author_karma=350,
            posted_at=NOW - timedelta(hours=8),
            initial_score=85,
            initial_num_comments=10,
            upvote_ratio=0.94,
            lang="zh",
        )
        s.add(c)
        s.flush()
        out = promote_to_tracked(s, user_id=42, candidate_post_id=c.id)
        tracked_id = out.tracked_post_id
        # 模擬 M5 polling 一筆 snapshot
        s.add(PostSnapshot(
            tracked_post_id=tracked_id, score=190, num_comments=22, upvote_ratio=0.95,
        ))
        # 模擬 M5 detection 兩筆 related
        s.add(RelatedPost(
            tracked_post_id=tracked_id,
            relation_type="hot_reply",
            reddit_post_id="c_hot1",
            relevance_score=280.0,
            is_milestone=True,
            content="[hot reply, score=280] 好香喔好想吃",
        ))
        s.add(RelatedPost(
            tracked_post_id=tracked_id,
            relation_type="crosspost",
            reddit_post_id="xp1",
            relevance_score=140.0,
            is_milestone=True,
            content="[crosspost r/OffMyChest score=140] copy of typhoon meal",
        ))
        s.commit()
        log.info("seeded candidate=%d tracked=%d + 1 snapshot + 2 related",
                 c.id, tracked_id)

    # Step 2 — open session
    scraper = TreeFakeScraper(comments=[
        _comment("c1", author="alice", body="補充：是滷雞腿便當", is_op=True,
                 score=35, hours_ago=4.0),
        _comment("c2", author="bob", body="好香喔好想吃", score=280, hours_ago=3.0),
        _comment("c3", author="carol", body="r/我也買到了", score=22, hours_ago=2.0),
    ])

    with Session() as s:
        outcome = qa_service.open_session(
            s, user_id=42, tracked_post_id=tracked_id, scraper=scraper
        )
        s.commit()
        assert outcome.state is not None, "open_session should succeed"
        state = outcome.state
        log.info(
            "opened session=%d system_tokens~%d (prompt %d chars / %d lines)",
            state.qa_session_id,
            state.system_tokens_estimate,
            len(state.system_prompt),
            state.system_prompt.count("\n") + 1,
        )

    # Step 3 — 2 輪對話（FakeChat — 不打網路）
    chat = FakeChat(
        factory=lambda sys, msgs: f"(fake) 收到 {len(msgs)} 輪歷史，最新提問解析中…",
    )
    with Session() as s:
        out1 = qa_service.handle_message(
            s, user_id=42, text="這篇為什麼會爆？", chat=chat
        )
        out2 = qa_service.handle_message(
            s, user_id=42, text="作者後來還有發類似的貼文嗎？", chat=chat
        )
        s.commit()
        log.info("turn1 reply=%s cost=%s", out1.reply, out1.cost_usd)
        log.info("turn2 reply=%s cost=%s", out2.reply, out2.cost_usd)

    # Step 4 — DB 寫入驗證
    with Session() as s:
        qa_msgs = s.scalars(
            select(QAMessage).order_by(QAMessage.id.asc())
        ).all()
        log.info("qa_messages: %d (user + assistant 各 2)", len(qa_msgs))
        assert len(qa_msgs) == 4
        llm_rows = s.scalars(select(LLMRecord)).all()
        log.info("llm_records: %d (purpose=qa)", len(llm_rows))
        assert len(llm_rows) == 2
        assert all(r.purpose == "qa" for r in llm_rows)
        assert all(r.provider == "fake" for r in llm_rows)

    # Step 5 — idle sweep（把 last_active_at 拉舊 10 分鐘，模擬 5 分鐘 timeout）
    qa_service.get_active(42).last_active_at = NOW - timedelta(minutes=10)
    with Session() as s:
        closed = qa_service.sweep_idle(
            s, ttl_seconds=qa_service.IDLE_TTL_SECONDS, now=NOW
        )
        s.commit()
        log.info("sweep_idle closed users=%s", closed)
        assert closed == [42]
        row = s.scalar(
            select(QASession).where(QASession.user_id == 42)
        )
        log.info(
            "QASession state=%s ended_at=%s",
            row.state, row.ended_at,
        )
        assert row.state == qa_service.STATE_ENDED_IDLE
        assert row.ended_at is not None

    # 再開一個 session 並手動 /exit
    with Session() as s:
        out = qa_service.open_session(
            s, user_id=42, tracked_post_id=tracked_id, scraper=None
        )
        s.commit()
        assert out.state is not None
        log.info("re-opened session=%d", out.state.qa_session_id)

    with Session() as s:
        close = qa_service.close_session(s, user_id=42)
        s.commit()
        log.info("manual close: %s", close)
        assert close.closed

    log.info("✅ M6 smoke ok — open + multi-turn + sweep_idle + manual close")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
