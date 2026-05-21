"""Claude Haiku 4.5 評分實作。

對應 SCHEDULE.md M3.2 + M3.3。Prompt 設計：

- 五軸 + verdict + reason，全部回 strict JSON
- 中英文混餵；prompt 明寫「英文輸入請用同樣標準評分」
- grassroots 改以 karma 衡量（v3 是 Threads follower）
- 容忍 ```json ... ``` fence（v3 也吃過這坑）
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

from ..config import get_settings
from ..models import CandidatePost
from .base import HaikuVerdict, LLMScorer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一個 Reddit 素人爆文評分助手。

任務：對一篇 Reddit 貼文做五軸量化評分（0.0–1.0），並決定是否值得追蹤（track / skip）。

五軸定義：
- story_potential：是否具備「事件能繼續展開」的潛力（後續更新、結局揭曉、第三方介入等）
- emotional_pull：情緒拉力。共鳴 / 反差 / 反諷 / 道德張力都算
- grassroots：素人輪廓符合度。以作者 karma 為主訊號：< 1000 接近 1.0、5000 ≈ 0.5、> 10000 接近 0.0
- novelty：題材新穎度 / 跳脫日常程度
- authenticity：真實性。明顯像廣告 / 釣魚 / 連環 karma farming → 接近 0.0

verdict 判準：
- track：五軸平均 ≥ 0.55，且 story_potential ≥ 0.5，且 authenticity ≥ 0.4
- skip：上述任一不達標

重要：
1. 英文輸入請用同樣標準評分，不因平台或語言而放寬或從嚴
2. 一律輸出 strict JSON，不要加 markdown 包裝或前後說明
3. reason 用 1–2 句中文簡述判斷依據（即使原文是英文）

輸出 JSON schema：
{
  "story_potential": float,
  "emotional_pull": float,
  "grassroots": float,
  "novelty": float,
  "authenticity": float,
  "verdict": "track" | "skip",
  "reason": str
}
"""


def build_user_prompt(post: CandidatePost) -> str:
    """組裝使用者訊息。欄位齊全度依 scraper 而異，None 用 'unknown' 替代。"""
    karma = post.author_karma if post.author_karma is not None else "unknown"
    ratio = f"{post.upvote_ratio:.2f}" if post.upvote_ratio is not None else "unknown"
    return (
        f"Subreddit: r/{post.subreddit}\n"
        f"Author: u/{post.author_username or 'unknown'} (karma: {karma})\n"
        f"Upvote ratio: {ratio}\n"
        f"Score / Comments: {post.initial_score} / {post.initial_num_comments}\n"
        f"\n"
        f"Title: {post.title or ''}\n"
        f"\n"
        f"Body:\n{post.selftext or '(no selftext / link post)'}\n"
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_haiku_response(text: str) -> dict[str, Any]:
    """容忍 ```json fence``` / 純 JSON / 兩端有閒聊文字三種情境。"""
    text = text.strip()
    m = _JSON_FENCE_RE.search(text)
    payload = m.group(1) if m else None
    if payload is None:
        m2 = _JSON_OBJECT_RE.search(text)
        payload = m2.group(0) if m2 else text
    return json.loads(payload)


def _coerce_axis(raw: Any, name: str) -> float:
    if not isinstance(raw, (int, float)):
        raise ValueError(f"axis {name} not number: {raw!r}")
    val = float(raw)
    if not 0.0 <= val <= 1.0:
        raise ValueError(f"axis {name} out of range [0,1]: {val}")
    return val


def verdict_from_payload(
    data: dict[str, Any],
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> HaikuVerdict:
    verdict = str(data.get("verdict", "")).lower().strip()
    if verdict not in ("track", "skip"):
        raise ValueError(f"invalid verdict: {data.get('verdict')!r}")
    return HaikuVerdict(
        story_potential=_coerce_axis(data["story_potential"], "story_potential"),
        emotional_pull=_coerce_axis(data["emotional_pull"], "emotional_pull"),
        grassroots=_coerce_axis(data["grassroots"], "grassroots"),
        novelty=_coerce_axis(data["novelty"], "novelty"),
        authenticity=_coerce_axis(data["authenticity"], "authenticity"),
        verdict=verdict,
        reason=str(data.get("reason", ""))[:500],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# Pricing — Claude Haiku 4.5（2025-10 公告）
# ---------------------------------------------------------------------------

# Anthropic 公開定價：Haiku 4.5 input $1 / MTok、output $5 / MTok
HAIKU_INPUT_PER_MTOK = Decimal("1.00")
HAIKU_OUTPUT_PER_MTOK = Decimal("5.00")


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (
        Decimal(input_tokens) * HAIKU_INPUT_PER_MTOK
        + Decimal(output_tokens) * HAIKU_OUTPUT_PER_MTOK
    ) / Decimal(1_000_000)
    return float(cost.quantize(Decimal("0.000001")))


# ---------------------------------------------------------------------------
# Real scorer
# ---------------------------------------------------------------------------


DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class HaikuScorer(LLMScorer):
    """Anthropic SDK 包一層。call site 統一從 factory 拿，避免散落 init。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 512,
    ):
        try:
            from anthropic import Anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK 未安裝。執行 `uv add anthropic`，或設 "
                "LLM_PROVIDER=fake / REDDIT_TRACKER_LLM=fake 使用 stub。"
            ) from e

        key = api_key or get_settings().anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 未設定。寫進 .env 或改用 FakeScorer。"
            )
        self._client = Anthropic(api_key=key)
        self.model = model
        self.max_tokens = max_tokens

    def score(self, post: CandidatePost) -> HaikuVerdict:
        user_prompt = build_user_prompt(post)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # 取第一個 text block
        text = next(
            (b.text for b in resp.content if getattr(b, "type", None) == "text"),
            "",
        )
        data = parse_haiku_response(text)

        usage = getattr(resp, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        cost = (
            estimate_cost(input_tokens or 0, output_tokens or 0)
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return verdict_from_payload(
            data,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )


__all__ = [
    "DEFAULT_MODEL",
    "HAIKU_INPUT_PER_MTOK",
    "HAIKU_OUTPUT_PER_MTOK",
    "HaikuScorer",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "estimate_cost",
    "parse_haiku_response",
    "verdict_from_payload",
]
