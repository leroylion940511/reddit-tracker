"""comment_tree service + scrapers/json_public 的 flatten 邏輯測試。"""

from __future__ import annotations

from datetime import datetime, timezone

from reddit_tracker.scrapers.base import CommentNode
from reddit_tracker.scrapers.json_public import _flatten_comments
from reddit_tracker.services.comment_tree import (
    author_replies,
    estimate_tokens,
    hot_replies,
    stats,
    to_prompt_text,
    top_n_by_score,
)


def _cn(
    cid: str,
    *,
    body: str = "x",
    score: int = 0,
    depth: int = 0,
    is_submitter: bool = False,
    author: str | None = "alice",
    more: bool = False,
    omitted: int = 0,
) -> CommentNode:
    return CommentNode(
        comment_id=cid,
        parent_id="t3_abc",
        author=author,
        body=body,
        score=score,
        created_utc=datetime(2026, 5, 22, tzinfo=timezone.utc),
        depth=depth,
        is_submitter=is_submitter,
        is_more_placeholder=more,
        omitted_count=omitted,
    )


# ---------------------------------------------------------------------------
# _flatten_comments：模擬 Reddit JSON 結構
# ---------------------------------------------------------------------------


def _make_reddit_comment(cid: str, *, author: str, body: str, score: int,
                        replies: list | None = None) -> dict:
    """模擬 Reddit /comments/<id>.json children 結構。"""
    return {
        "kind": "t1",
        "data": {
            "id": cid,
            "author": author,
            "body": body,
            "score": score,
            "created_utc": 1_700_000_000.0,
            "replies": (
                {"kind": "Listing", "data": {"children": replies}}
                if replies else ""
            ),
        },
    }


def test_flatten_simple_tree():
    children = [
        _make_reddit_comment("a", author="op_user", body="OP self-reply", score=5),
        _make_reddit_comment("b", author="other", body="external", score=12, replies=[
            _make_reddit_comment("b1", author="op_user", body="OP nested", score=3),
        ]),
    ]
    out: list[CommentNode] = []
    _flatten_comments(children, parent_id="t3_post1", submitter="op_user",
                       depth=0, out=out)
    assert [c.comment_id for c in out] == ["a", "b", "b1"]
    assert [c.depth for c in out] == [0, 0, 1]
    assert [c.is_submitter for c in out] == [True, False, True]
    assert [c.parent_id for c in out] == ["t3_post1", "t3_post1", "t1_b"]


def test_flatten_handles_more_placeholder():
    children = [
        _make_reddit_comment("a", author="x", body="t", score=1),
        {"kind": "more", "data": {"id": "_more", "count": 42}},
    ]
    out: list[CommentNode] = []
    _flatten_comments(children, parent_id="t3_p", submitter=None, depth=0, out=out)
    assert len(out) == 2
    assert out[1].is_more_placeholder is True
    assert out[1].omitted_count == 42


def test_flatten_handles_deleted_author():
    children = [_make_reddit_comment("a", author="[deleted]", body="t", score=1)]
    out: list[CommentNode] = []
    _flatten_comments(children, parent_id="t3_p", submitter=None, depth=0, out=out)
    assert out[0].author is None


# ---------------------------------------------------------------------------
# 查詢 helpers
# ---------------------------------------------------------------------------


def test_hot_replies_top_level_only():
    nodes = [
        _cn("a", score=100, depth=0),
        _cn("b", score=30, depth=0),                  # 低於 50
        _cn("c", score=200, depth=1),                 # 深層即使分數高也不算 hot_reply
        _cn("d", score=80, depth=0, more=True),       # placeholder
    ]
    hot = hot_replies(nodes)
    assert [c.comment_id for c in hot] == ["a"]


def test_hot_replies_with_lower_threshold():
    nodes = [_cn("a", score=20, depth=0), _cn("b", score=80, depth=0)]
    assert {c.comment_id for c in hot_replies(nodes, min_score=10)} == {"a", "b"}


def test_author_replies_filters_op_only():
    nodes = [
        _cn("a", is_submitter=True),
        _cn("b", is_submitter=False),
        _cn("c", is_submitter=True, more=True),       # placeholder 不算
    ]
    assert [c.comment_id for c in author_replies(nodes)] == ["a"]


def test_top_n_by_score_ignores_placeholder():
    nodes = [
        _cn("a", score=10), _cn("b", score=100, more=True), _cn("c", score=50),
    ]
    top = top_n_by_score(nodes, n=2)
    assert [c.comment_id for c in top] == ["c", "a"]


# ---------------------------------------------------------------------------
# 呈現
# ---------------------------------------------------------------------------


def test_to_prompt_text_indents_and_marks_op():
    nodes = [
        _cn("a", body="hello", score=5, depth=0, is_submitter=True),
        _cn("b", body="reply", score=2, depth=1, is_submitter=False),
        _cn("c", body="", depth=2, more=True, omitted=20),
    ]
    text = to_prompt_text(nodes, indent="--", show_score=False)
    lines = text.splitlines()
    assert lines[0].startswith("- alice [OP]: hello")
    assert lines[1].startswith("--- alice: reply")
    assert "20 more comments omitted" in lines[2]


def test_to_prompt_text_truncates_long_body():
    long_body = "x" * 600
    nodes = [_cn("a", body=long_body)]
    text = to_prompt_text(nodes, truncate_body=100)
    assert "…" in text
    # 截斷後的 line 應該短得多
    assert len(text) < 200


def test_stats_counts_correctly():
    nodes = [
        _cn("a", depth=0), _cn("b", depth=0), _cn("c", depth=2),
        _cn("d", more=True, omitted=15),
    ]
    s = stats(nodes)
    assert s.total == 3
    assert s.top_level == 2
    assert s.max_depth == 2
    assert s.omitted_more == 1
    assert s.omitted_count_estimate == 15


def test_estimate_tokens_returns_positive():
    assert estimate_tokens("") == 1
    # 中英混合粗估 2.5 char/token
    assert 80 <= estimate_tokens("a" * 200) <= 100
