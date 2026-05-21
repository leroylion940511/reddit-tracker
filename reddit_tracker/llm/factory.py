"""LLM scorer factory — 依環境變數切實作。

預設邏輯：
- `LLM_PROVIDER=anthropic` (default) + 有 `ANTHROPIC_API_KEY` → `HaikuScorer`
- `LLM_PROVIDER=fake`，或沒 key → `FakeScorer`（log warning）

不要在 module-import 時建 client，因 test 也會 import 這支。
"""

from __future__ import annotations

import logging

from ..config import get_settings
from .base import LLMScorer
from .fake import FakeScorer
from .haiku import HaikuScorer
from .minimax import MinimaxScorer

logger = logging.getLogger(__name__)


def build_scorer() -> LLMScorer:
    settings = get_settings()
    provider = (settings.llm_provider or "anthropic").lower()

    if provider == "fake":
        logger.info("LLM_PROVIDER=fake → 使用 FakeScorer")
        return FakeScorer()

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            logger.warning(
                "ANTHROPIC_API_KEY 未設定 → fallback 到 FakeScorer（不會真打 API）"
            )
            return FakeScorer()
        return HaikuScorer(api_key=settings.anthropic_api_key)

    if provider == "minimax":
        if not settings.minimax_api_key:
            logger.warning(
                "MINIMAX_API_KEY 未設定 → fallback 到 FakeScorer（不會真打 API）"
            )
            return FakeScorer()
        return MinimaxScorer(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
            model=settings.minimax_model,
        )

    raise ValueError(f"unknown LLM_PROVIDER: {provider}")


__all__ = ["build_scorer"]
