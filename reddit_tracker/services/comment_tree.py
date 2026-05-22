"""Comment tree 查詢輔助 — M5 後續事件偵測與 M6 問答 context 都用。

Scraper 層只負責「抓並 flatten 成 CommentNode list」（深 / 淺、樹形不重組）。
這層提供 M5/M6 高頻使用的查詢：
- hot_replies(): top-level 留言中分數 > 閾值 / 比第二名高 X% 的，給 M5 hot_reply 偵測
- author_replies(): is_submitter=True 的，給 M5 author_reply 偵測
- to_prompt_text(): 樹狀縮排呈現給 Opus 重量 context 用
- estimate_tokens(): 粗估這份 context 進 Opus 的 input token 量（M6 預算控制）

刻意不引 SQLAlchemy / 任何 DB 依賴 — 純函式對 CommentNode list 操作。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..scrapers.base import CommentNode

# 粗估 token：英文 ~4 char/token、中文 ~1.5 char/token。混合內容取中間值 2.5。
# 用於 M6 budget 估算，誤差 ~30% 內可接受；正確 token 數要靠 Opus 回的 usage。
CHARS_PER_TOKEN_ESTIMATE = 2.5


# ---------------------------------------------------------------------------
# 查詢
# ---------------------------------------------------------------------------


def hot_replies(
    comments: list[CommentNode],
    *,
    min_score: int = 50,
    top_level_only: bool = True,
) -> list[CommentNode]:
    """挑「分數 ≥ min_score」的留言。對應 M5 hot_reply 偵測。

    `top_level_only=True` 等同企劃書 §4.5 規格（depth=0 才算 hot_reply，
    巢狀深處的 reply 視為更接近 thread 內部討論）。
    """
    pool = [c for c in comments if not c.is_more_placeholder]
    if top_level_only:
        pool = [c for c in pool if c.depth == 0]
    return [c for c in pool if c.score >= min_score]


def author_replies(comments: list[CommentNode]) -> list[CommentNode]:
    """原 PO 在自己貼文下的留言。M5 author_reply 偵測用。"""
    return [c for c in comments if c.is_submitter and not c.is_more_placeholder]


def top_n_by_score(
    comments: list[CommentNode], n: int = 30
) -> list[CommentNode]:
    """依分數排序取前 N — M6 中量 context fallback 用。"""
    pool = [c for c in comments if not c.is_more_placeholder]
    return sorted(pool, key=lambda c: c.score, reverse=True)[:n]


# ---------------------------------------------------------------------------
# Prompt 用呈現
# ---------------------------------------------------------------------------


@dataclass
class CommentTreeStats:
    total: int
    top_level: int
    max_depth: int
    omitted_more: int                 # MoreComments placeholder 數
    omitted_count_estimate: int       # placeholder 上 reddit 估計的 omitted 留言總和


def stats(comments: list[CommentNode]) -> CommentTreeStats:
    real = [c for c in comments if not c.is_more_placeholder]
    placeholders = [c for c in comments if c.is_more_placeholder]
    return CommentTreeStats(
        total=len(real),
        top_level=sum(1 for c in real if c.depth == 0),
        max_depth=max((c.depth for c in real), default=0),
        omitted_more=len(placeholders),
        omitted_count_estimate=sum(c.omitted_count for c in placeholders),
    )


def to_prompt_text(
    comments: list[CommentNode],
    *,
    indent: str = "  ",
    show_score: bool = True,
    truncate_body: int | None = 400,
) -> str:
    """把扁平 CommentNode list 還原成 indented 文字 — 給 Opus 重量 context 用。

    `truncate_body` 對單則留言內文 cap 字數（中英混合 400 char ≈ 160 token）；
    M6 token budget 緊時可調低，但會犧牲深度語意。
    """
    lines: list[str] = []
    for c in comments:
        prefix = indent * c.depth
        if c.is_more_placeholder:
            lines.append(
                f"{prefix}... ({c.omitted_count} more comments omitted; "
                f"OAuth-only API needed to expand)"
            )
            continue
        author = c.author or "[deleted]"
        marker = " [OP]" if c.is_submitter else ""
        body = c.body
        if truncate_body and len(body) > truncate_body:
            body = body[:truncate_body] + " …"
        score_part = f" · {c.score}↑" if show_score else ""
        # 留言內換行縮排對齊以保留可讀性
        body_lines = body.split("\n")
        first = body_lines[0]
        lines.append(f"{prefix}- {author}{marker}{score_part}: {first}")
        for extra in body_lines[1:]:
            lines.append(f"{prefix}  {extra}")
    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """粗估 Opus 4.7 input tokens — 中英混合用 2.5 char/token。"""
    return max(1, int(len(text) / CHARS_PER_TOKEN_ESTIMATE))
