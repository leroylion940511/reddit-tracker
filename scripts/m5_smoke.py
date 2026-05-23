"""M5.10 端到端 smoke — 不打真實網路、不送 Telegram。

流程：
  1. 建 1 篇 candidate + 用 promote_to_tracked 升格
  2. 用 RichFakeScraper 提供 user_submissions / comments / dups
  3. run_polling 抓 snapshot
  4. detect_for_tracked 跑四類偵測
  5. fetch_pending_milestones / build_daily_digest 驗 selection
  6. 印出 /saved + /timeline 的格式輸出（純文字驗收）

用：uv run python scripts/m5_smoke.py
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 確保不誤用環境裡的 DB
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine                       # noqa: E402
from sqlalchemy.orm import sessionmaker                    # noqa: E402

from reddit_tracker.bot import handlers as bot_handlers    # noqa: E402
from reddit_tracker.models import Base, CandidatePost      # noqa: E402
from reddit_tracker.scrapers.base import CommentNode, PostPayload  # noqa: E402
from reddit_tracker.scrapers.fake import FakeScraper       # noqa: E402
from reddit_tracker.services.detection import detect_for_tracked  # noqa: E402
from reddit_tracker.services.notification import (         # noqa: E402
    build_daily_digest,
    fetch_pending_milestones,
)
from reddit_tracker.services.polling import run_polling   # noqa: E402
from reddit_tracker.services.promotion import promote_to_tracked  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("m5_smoke")

NOW = datetime.now(timezone.utc)


def _payload(rid, *, sub="Taiwan", title="x", author="alice", score=10,
             hours_ago=2.0) -> PostPayload:
    return PostPayload(
        reddit_post_id=rid, subreddit=sub, title=title, selftext="...",
        author=author, author_karma=500, score=score, upvote_ratio=0.9,
        num_comments=12, created_utc=NOW - timedelta(hours=hours_ago),
        permalink=f"/r/{sub}/comments/{rid}/x/",
        url=f"https://www.reddit.com/r/{sub}/comments/{rid}/x/",
        is_self=True, is_deleted=False, over_18=False, stickied=False,
    )


def _comment(cid, *, author="bob", body="...", score=5, is_op=False,
             hours_ago=1.0) -> CommentNode:
    return CommentNode(
        comment_id=cid, parent_id="t3_orig", author=author, body=body,
        score=score, created_utc=NOW - timedelta(hours=hours_ago),
        depth=0, is_submitter=is_op,
    )


class RichFakeScraper(FakeScraper):
    """提供 detection 各 endpoint 的客製化資料。"""

    def __init__(self, *, post_payload, submissions, comments, dups):
        super().__init__(corpus=[post_payload])
        self._post = post_payload
        self._subs = submissions
        self._comments = comments
        self._dups = dups

    def fetch_post(self, post_id):
        return self._post if post_id == self._post.reddit_post_id else None

    def fetch_user_submissions(self, username, limit=20):
        return self._subs

    def fetch_comment_tree(self, post_id, *, limit=500, depth=10):
        return self._comments

    def fetch_duplicates(self, post_id):
        return self._dups


def run() -> int:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # M5 step 1 — candidate + tracked
    with Session() as s:
        c = CandidatePost(
            reddit_post_id="orig", subreddit="Taiwan",
            title="颱風天買到的便當", selftext="...",
            permalink="/r/Taiwan/comments/orig/typhoon/",
            author_username="alice",
            posted_at=NOW - timedelta(hours=8),
            initial_score=85, initial_num_comments=10,
            upvote_ratio=0.94, lang="zh",
        )
        s.add(c)
        s.flush()
        outcome = promote_to_tracked(s, user_id=42, candidate_post_id=c.id)
        s.commit()
        tracked_id = outcome.tracked_post_id
        log.info("promoted candidate=%d → tracked=%d", c.id, tracked_id)

    scraper = RichFakeScraper(
        post_payload=_payload("orig", title="颱風天買到的便當", score=520, hours_ago=8.0),
        submissions=[
            _payload("p2", title="颱風天買到的便當續集", score=180, hours_ago=1.0),
            _payload("p3", title="完全不相關 random", score=20, sub="other",
                     hours_ago=0.5),
        ],
        comments=[
            _comment("c1", author="alice", body="補充：是滷雞腿便當", is_op=True,
                     score=35, hours_ago=4.0),
            _comment("c2", author="bob", body="好香喔好想吃", score=280, hours_ago=3.0),
            _comment("c3", author="carol", body="路人留言", score=8, hours_ago=2.0),
        ],
        dups=[
            _payload("xp1", sub="OffMyChest", title="copy of typhoon meal",
                     score=140, hours_ago=2.0),
        ],
    )

    # M5 step 2 — polling
    with Session() as s:
        stat = run_polling(s, scraper, now=NOW + timedelta(minutes=1))
        s.commit()
        log.info("polling: %s", stat)

    # M5 step 3 — detection
    with Session() as s:
        from reddit_tracker.models import TrackedPost
        tp = s.get(TrackedPost, tracked_id)
        stat = detect_for_tracked(s, scraper, tp, now=NOW + timedelta(minutes=2))
        s.commit()
        log.info("detection: inserted=%d milestones=%d errors=%d",
                 stat.inserted, stat.milestones, len(stat.errors))
        log.info("  by type: %s", stat.findings_by_type)

    # M5 step 4 — notification selection
    with Session() as s:
        pending = fetch_pending_milestones(s)
        log.info("pending milestones: %d", len(pending))
        for p in pending:
            log.info("  ★ %s — %s", p.related.relation_type, (p.related.content or "")[:60])
        digest = build_daily_digest(s, now=NOW + timedelta(minutes=2))
        log.info("digest entries: trackeds=%d, total_related=%d",
                 len(digest), sum(len(e.related) for e in digest))

    # M5 step 5 — /saved + /timeline
    import contextlib

    @contextlib.contextmanager
    def _scope_factory():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    bot_handlers.session_scope = _scope_factory   # type: ignore[assignment]
    log.info("\n--- /saved ---\n%s", bot_handlers._saved_list_sync(user_id=42))
    log.info("\n--- /timeline %d ---\n%s",
             tracked_id, bot_handlers._timeline_sync(user_id=42, tracked_id=tracked_id))

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
