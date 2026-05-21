"""MiniMax international scorer — Anthropic Haiku 的暫代實作。

走 OpenAI-compatible chat completion endpoint
(`/v1/text/chatcompletion_v2`)；輸出仍是 `HaikuVerdict`（五軸 + verdict），
與 `HaikuScorer` 互換。

用途：OAuth 等待期間 / 沒 ANTHROPIC_API_KEY 時，仍能在真實 LLM 上驗證 prompt。
"""

from __future__ import annotations

import logging
from decimal import Decimal

import requests

from ..config import get_settings
from ..models import CandidatePost
from .base import HaikuVerdict, LLMScorer
from .haiku import SYSTEM_PROMPT, build_user_prompt, parse_haiku_response, verdict_from_payload

logger = logging.getLogger(__name__)


# 對 MiniMax 國際定價（2024 Q4 公告，USD per 1M tokens）。實際比率仍以官方為準。
# 取保守估值便於 monthly cost 試算；M7 對帳會再用 invoice 校準。
MINIMAX_INPUT_PER_MTOK = Decimal("0.20")
MINIMAX_OUTPUT_PER_MTOK = Decimal("1.10")


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (
        Decimal(input_tokens) * MINIMAX_INPUT_PER_MTOK
        + Decimal(output_tokens) * MINIMAX_OUTPUT_PER_MTOK
    ) / Decimal(1_000_000)
    return float(cost.quantize(Decimal("0.000001")))


class MinimaxScorer(LLMScorer):
    """OpenAI-compatible chat completion 對接 MiniMax 國際 API。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int = 512,
        timeout: float = 60.0,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.minimax_api_key
        if not self.api_key:
            raise RuntimeError(
                "MINIMAX_API_KEY 未設定。寫進 .env 或改用 FakeScorer。"
            )
        self.base_url = (base_url or settings.minimax_base_url).rstrip("/")
        self.model = model or settings.minimax_model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def score(self, post: CandidatePost) -> HaikuVerdict:
        user_prompt = build_user_prompt(post)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.1,             # 評分要穩定
        }
        resp = self._session.post(
            f"{self.base_url}/text/chatcompletion_v2", json=body, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax error: {base_resp.get('status_code')} {base_resp.get('status_msg')}"
            )

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("MiniMax returned no choices")
        text = (choices[0].get("message") or {}).get("content", "")
        payload = parse_haiku_response(text)

        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        cost = (
            estimate_cost(input_tokens or 0, output_tokens or 0)
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return verdict_from_payload(
            payload,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

    def close(self) -> None:
        self._session.close()


__all__ = ["MINIMAX_INPUT_PER_MTOK", "MINIMAX_OUTPUT_PER_MTOK", "MinimaxScorer", "estimate_cost"]
