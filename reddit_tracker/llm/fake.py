"""可控的 fake scorer — 給 unit test / 在沒 ANTHROPIC_API_KEY 時 fallback。

行為：
- 預設給每個 candidate 一份「中等偏 track」的 verdict
- 可 inject 固定 verdict 或 callable，做精準斷言
- 支援模擬 invalid JSON / 例外（給 M3.8 failure path 測試）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import CandidatePost
from .base import HaikuVerdict, LLMScorer


def _default_verdict(post: CandidatePost) -> HaikuVerdict:
    """中庸基線：所有 axis 0.6、verdict=track。便於非 LLM 路徑也能跑完 final_score。"""
    return HaikuVerdict(
        story_potential=0.6,
        emotional_pull=0.6,
        grassroots=0.6,
        novelty=0.6,
        authenticity=0.7,
        verdict="track",
        reason=f"fake verdict for {post.reddit_post_id}",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )


@dataclass
class FakeScorer(LLMScorer):
    """可注入的 stub scorer。"""

    factory: Callable[[CandidatePost], HaikuVerdict] | None = None
    raise_exc: Exception | None = None
    call_count: int = 0

    def score(self, post: CandidatePost) -> HaikuVerdict:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.factory is not None:
            return self.factory(post)
        return _default_verdict(post)


__all__ = ["FakeScorer"]
