"""SCHEDULE.md M5.3–5.7 — related-post detection。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from reddit_tracker.models import CandidatePost, RelatedPost, TrackedPost
from reddit_tracker.scrapers.base import CommentNode, PostPayload
from reddit_tracker.scrapers.fake import FakeScraper
from reddit_tracker.services.detection import (
    HOT_REPLY_ABS_SCORE,
    MILESTONE_THRESHOLDS,
    RELATION_AUTHOR_FOLLOWUP,
    RELATION_AUTHOR_REPLY,
    RELATION_CROSSPOST,
    RELATION_HOT_REPLY,
    RelatedFinding,
    detect_author_followup,
    detect_author_reply,
    detect_crossposts,
    detect_for_tracked,
    detect_hot_reply,
    evaluate_milestone,
    persist_findings,
    title_similarity,
)


NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


def _make_tracked(session, *, rid: str = "p1", title: str = "原貼標題", sub: str = "Taiwan",
                  posted_hours_ago: float = 8.0, author: str = "alice") -> TrackedPost:
    c = CandidatePost(
        reddit_post_id=rid,
        subreddit=sub,
        title=title,
        selftext="x" * 100,
        permalink=f"/r/{sub}/comments/{rid}/x/",
        author_username=author,
        posted_at=NOW - timedelta(hours=posted_hours_ago),
        initial_score=50,
        initial_num_comments=5,
    )
    session.add(c)
    session.flush()
    tp = TrackedPost(
        candidate_post_id=c.id,
        user_id=1,
        polling_tier="hot",
        status="active",
    )
    session.add(tp)
    session.flush()
    return tp


def _make_payload(rid, *, sub="Taiwan", title="x", author="alice", score=10,
                  posted_hours_ago=2.0) -> PostPayload:
    return PostPayload(
        reddit_post_id=rid, subreddit=sub, title=title, selftext="x",
        author=author, author_karma=500, score=score, upvote_ratio=0.9,
        num_comments=5, created_utc=NOW - timedelta(hours=posted_hours_ago),
        permalink=f"/r/{sub}/comments/{rid}/x/",
        url=f"https://www.reddit.com/r/{sub}/comments/{rid}/x/",
        is_self=True, is_deleted=False, over_18=False, stickied=False,
    )


def _make_comment(cid, *, parent="t3_p1", author="bob", body="hi", score=5,
                  is_op=False, hours_ago=1.0, depth=0) -> CommentNode:
    return CommentNode(
        comment_id=cid, parent_id=parent, author=author, body=body,
        score=score, created_utc=NOW - timedelta(hours=hours_ago),
        depth=depth, is_submitter=is_op,
    )


# ---------------------------------------------------------------------------
# title_similarity / evaluate_milestone
# ---------------------------------------------------------------------------


def test_title_similarity_same_sub_bonus():
    s_same = title_similarity("颱風天買到的便當", "Taiwan", "颱風天買到的便當續集", "Taiwan")
    s_diff = title_similarity("颱風天買到的便當", "Taiwan", "颱風天買到的便當續集", "Other")
    assert s_same > s_diff


def test_title_similarity_low_for_unrelated():
    score = title_similarity("颱風天買到的便當", "Taiwan", "TIFU something else", "tifu")
    assert score < 0.3


def test_evaluate_milestone_thresholds():
    f_low = RelatedFinding(relation_type=RELATION_HOT_REPLY, reddit_post_id="c1",
                           posted_at=NOW, content="x", relevance_score=50.0)
    f_high = RelatedFinding(relation_type=RELATION_HOT_REPLY, reddit_post_id="c2",
                            posted_at=NOW, content="x", relevance_score=250.0)
    assert evaluate_milestone(f_low) is False
    assert evaluate_milestone(f_high) is True


def test_evaluate_milestone_followup_uses_relevance():
    f = RelatedFinding(relation_type=RELATION_AUTHOR_FOLLOWUP, reddit_post_id="p2",
                       posted_at=NOW, content="x", relevance_score=0.8)
    assert evaluate_milestone(f) is True
    f2 = RelatedFinding(relation_type=RELATION_AUTHOR_FOLLOWUP, reddit_post_id="p2",
                        posted_at=NOW, content="x", relevance_score=0.5)
    assert evaluate_milestone(f2) is False


def test_evaluate_milestone_none_score():
    f = RelatedFinding(relation_type=RELATION_HOT_REPLY, reddit_post_id="c", posted_at=NOW,
                       content="x", relevance_score=None)
    assert evaluate_milestone(f) is False


# ---------------------------------------------------------------------------
# detect_author_followup
# ---------------------------------------------------------------------------


def test_author_followup_filters_old_and_self(session):
    tp = _make_tracked(session, rid="p1", title="颱風天買到的便當", sub="Taiwan")
    submissions = [
        _make_payload("p1", title="同一篇 self", posted_hours_ago=8.0),       # 同 rid 排除
        _make_payload("p0", title="比原文更早", posted_hours_ago=24.0),       # 早於原文
        _make_payload("p2", title="颱風天買到的便當續集", posted_hours_ago=2.0),  # ✅
        _make_payload("p3", title="完全無關 something", sub="tifu", posted_hours_ago=1.0),  # ✅ 但低 relevance
    ]
    findings = detect_author_followup(tp, submissions, now=NOW)
    rids = {f.reddit_post_id for f in findings}
    assert rids == {"p2", "p3"}
    # 同 sub + 標題重疊 → 較高相關性
    by_rid = {f.reddit_post_id: f for f in findings}
    assert by_rid["p2"].relevance_score > by_rid["p3"].relevance_score


def test_author_followup_empty_submissions(session):
    tp = _make_tracked(session)
    assert detect_author_followup(tp, [], now=NOW) == []


# ---------------------------------------------------------------------------
# detect_author_reply / detect_hot_reply
# ---------------------------------------------------------------------------


def test_author_reply_filters_is_submitter(session):
    tp = _make_tracked(session)
    comments = [
        _make_comment("c1", author="alice", body="OP 補充", is_op=True, score=15),
        _make_comment("c2", author="bob", body="路人留言", is_op=False, score=80),
    ]
    findings = detect_author_reply(tp, comments)
    assert len(findings) == 1
    assert findings[0].reddit_post_id == "c1"
    assert "OP 補充" in findings[0].content


def test_hot_reply_abs_threshold(session):
    tp = _make_tracked(session)
    comments = [
        _make_comment("c1", score=80),                  # 過絕對閾值（50）
        _make_comment("c2", score=10),
        _make_comment("c3", score=5),
    ]
    findings = detect_hot_reply(tp, comments)
    rids = {f.reddit_post_id for f in findings}
    assert "c1" in rids
    assert "c2" not in rids


def test_hot_reply_relative_margin(session):
    tp = _make_tracked(session)
    # 都低於 abs_threshold (50)，但 top 比第二名高 30%+
    comments = [
        _make_comment("top", score=40),
        _make_comment("second", score=20),    # top > 1.3 × second (26)
        _make_comment("third", score=15),
    ]
    findings = detect_hot_reply(tp, comments)
    rids = {f.reddit_post_id for f in findings}
    assert "top" in rids
    assert "second" not in rids


def test_hot_reply_skips_more_placeholder(session):
    tp = _make_tracked(session)
    placeholder = CommentNode(
        comment_id="m1", parent_id="t3_p1", author=None, body="", score=0,
        created_utc=NOW, depth=0, is_submitter=False,
        is_more_placeholder=True, omitted_count=10,
    )
    comments = [placeholder, _make_comment("c1", score=HOT_REPLY_ABS_SCORE + 1)]
    findings = detect_hot_reply(tp, comments)
    assert {f.reddit_post_id for f in findings} == {"c1"}


# ---------------------------------------------------------------------------
# detect_crossposts
# ---------------------------------------------------------------------------


def test_crossposts_basic(session):
    tp = _make_tracked(session, rid="orig")
    dups = [
        _make_payload("xp1", sub="OffMyChest", score=120),
        _make_payload("orig", sub="Taiwan", score=999),    # 原文，排除
    ]
    findings = detect_crossposts(tp, dups)
    assert len(findings) == 1
    assert findings[0].reddit_post_id == "xp1"
    assert findings[0].relevance_score == 120.0


# ---------------------------------------------------------------------------
# persist_findings — dedup + milestone flag
# ---------------------------------------------------------------------------


def test_persist_findings_dedups_against_db_and_batch(session):
    tp = _make_tracked(session)
    f1 = RelatedFinding(relation_type=RELATION_CROSSPOST, reddit_post_id="xp1",
                        posted_at=NOW, content="x", relevance_score=200.0)
    f2 = RelatedFinding(relation_type=RELATION_CROSSPOST, reddit_post_id="xp1",
                        posted_at=NOW, content="x", relevance_score=200.0)  # 同 batch 重複
    f3 = RelatedFinding(relation_type=RELATION_CROSSPOST, reddit_post_id="xp2",
                        posted_at=NOW, content="x", relevance_score=50.0)

    inserted, dupe, ms = persist_findings(session, tp.id, [f1, f2, f3])
    assert inserted == 2
    assert dupe == 1
    assert ms == 1                       # 只有 xp1 (score=200) 是 milestone

    # 第二次 persist 同樣的 → 全部 dupe
    inserted2, dupe2, _ = persist_findings(session, tp.id, [f1, f3])
    assert inserted2 == 0
    assert dupe2 == 2


def test_persist_findings_marks_milestone(session):
    tp = _make_tracked(session)
    f = RelatedFinding(
        relation_type=RELATION_AUTHOR_REPLY, reddit_post_id="c1",
        posted_at=NOW, content="x",
        relevance_score=MILESTONE_THRESHOLDS[RELATION_AUTHOR_REPLY] + 1,
    )
    persist_findings(session, tp.id, [f])
    row = session.scalar(select(RelatedPost).where(RelatedPost.reddit_post_id == "c1"))
    assert row is not None
    assert row.is_milestone is True


# ---------------------------------------------------------------------------
# detect_for_tracked — end-to-end orchestration
# ---------------------------------------------------------------------------


class _RichFakeScraper(FakeScraper):
    """覆寫所有 endpoint 直接餵測試 fixture，避免依賴預設 50 筆 corpus。"""

    def __init__(self, *, submissions, comments, dups):
        super().__init__(corpus=[])
        self._subs = submissions
        self._comments = comments
        self._dups = dups
        self.fetch_calls = {"submissions": 0, "comments": 0, "duplicates": 0}

    def fetch_user_submissions(self, username, limit=20):
        self.fetch_calls["submissions"] += 1
        return self._subs

    def fetch_comment_tree(self, post_id, *, limit=500, depth=10):
        self.fetch_calls["comments"] += 1
        return self._comments

    def fetch_duplicates(self, post_id):
        self.fetch_calls["duplicates"] += 1
        return self._dups


def test_detect_for_tracked_fetches_all_three_endpoints(session):
    tp = _make_tracked(session)
    scraper = _RichFakeScraper(
        submissions=[_make_payload("p2", title="續集", posted_hours_ago=1.0)],
        comments=[
            _make_comment("c1", author="alice", body="OP", is_op=True, score=30),
            _make_comment("c2", author="bob", body="hot", score=300),
        ],
        dups=[_make_payload("xp1", sub="other", score=150)],
    )
    stat = detect_for_tracked(session, scraper, tp, now=NOW)
    assert scraper.fetch_calls == {"submissions": 1, "comments": 1, "duplicates": 1}
    # 4 findings: 1 followup + 1 OP reply + 1 hot reply + 1 crosspost
    assert stat.inserted == 4
    # milestones: c2 (300 > 200) + xp1 (150 > 100) + maybe c1 OP reply (30 > 20)
    # = 3 milestones
    assert stat.milestones == 3
    assert not stat.errors


def test_detect_for_tracked_continues_on_partial_failure(session):
    """fetch_user_submissions raise 不影響 comments + dups 流程。"""
    tp = _make_tracked(session)

    class _PartialScraper(_RichFakeScraper):
        def fetch_user_submissions(self, username, limit=20):
            raise RuntimeError("about-403")

    scraper = _PartialScraper(
        submissions=[],
        comments=[_make_comment("c1", score=60)],   # 過 abs threshold
        dups=[_make_payload("xp1", sub="other", score=50)],
    )
    stat = detect_for_tracked(session, scraper, tp, now=NOW)
    assert any("author_followup" in e for e in stat.errors)
    assert stat.inserted == 2     # hot_reply c1 + crosspost xp1
    assert stat.milestones == 0   # 都低於各自 threshold


def test_detect_for_tracked_idempotent(session):
    tp = _make_tracked(session)
    scraper = _RichFakeScraper(
        submissions=[_make_payload("p2", title="續集", posted_hours_ago=1.0)],
        comments=[_make_comment("c2", score=80)],
        dups=[],
    )
    s1 = detect_for_tracked(session, scraper, tp, now=NOW)
    s2 = detect_for_tracked(session, scraper, tp, now=NOW)
    assert s1.inserted >= 1
    assert s2.inserted == 0                 # 全部 dupe
    assert s2.skipped_dupe == s1.inserted
