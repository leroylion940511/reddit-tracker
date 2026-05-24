"""MiniMax 多輪 chat client — M6 問答層。

scoring 走 `MinimaxScorer`（單輪、強制 JSON 輸出），QA 走 `MinimaxChat`
（多輪、自然語言）；兩者共用 base_url / api_key / model 設定，但 message
結構與 response 處理不同，故分開實作。

對 `chatcompletion_v2` (OpenAI-compatible) POST。輸入：system + messages
（user/assistant 多輪）；回 `ChatResult`（content + usage + cost）。

`FakeChat` 給單元測試 / 沒 MINIMAX_API_KEY 的離線環境用，行為與 MinimaxChat
介面一致，可注入 `factory` 客製單輪回覆。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

import requests

from ..config import get_settings

logger = logging.getLogger(__name__)


# 同 minimax.py 用同一份保守估價（M7 對帳會以 invoice 校準）
MINIMAX_INPUT_PER_MTOK = Decimal("0.20")
MINIMAX_OUTPUT_PER_MTOK = Decimal("1.10")


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    cost = (
        Decimal(input_tokens) * MINIMAX_INPUT_PER_MTOK
        + Decimal(output_tokens) * MINIMAX_OUTPUT_PER_MTOK
    ) / Decimal(1_000_000)
    return float(cost.quantize(Decimal("0.000001")))


@dataclass(frozen=True)
class ChatResult:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None


class ChatClient:
    """多輪 chat client 抽象介面。實作見下方 MinimaxChat / FakeChat。"""

    provider: str = "abstract"
    model: str = "abstract"

    def complete(self, *, system: str, messages: list[dict]) -> ChatResult:
        raise NotImplementedError

    def close(self) -> None:  # noqa: D401
        """子類選擇性實作（http client cleanup）。"""


class MinimaxChat(ChatClient):
    provider = "minimax"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        timeout: float = 60.0,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.minimax_api_key
        if not self.api_key:
            raise RuntimeError("MINIMAX_API_KEY 未設定")
        self.base_url = (base_url or settings.minimax_base_url).rstrip("/")
        self.model = model or settings.minimax_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def complete(self, *, system: str, messages: list[dict]) -> ChatResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        resp = self._session.post(
            f"{self.base_url}/text/chatcompletion_v2", json=body, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax error: {base_resp.get('status_code')} "
                f"{base_resp.get('status_msg')}"
            )
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("MiniMax returned no choices")
        text = (choices[0].get("message") or {}).get("content", "") or ""

        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        cost = (
            estimate_cost(input_tokens or 0, output_tokens or 0)
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return ChatResult(
            content=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )

    def close(self) -> None:
        self._session.close()


class FakeChat(ChatClient):
    """In-memory 多輪 chat — 給 unit test 與離線 smoke 用。"""

    provider = "fake"
    model = "fake-chat"

    def __init__(
        self,
        *,
        factory: Callable[[str, list[dict]], str] | None = None,
        raise_exc: Exception | None = None,
        input_tokens: int = 1500,
        output_tokens: int = 80,
    ) -> None:
        self.factory = factory
        self.raise_exc = raise_exc
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, *, system: str, messages: list[dict]) -> ChatResult:
        self.calls.append((system, list(messages)))
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.factory is not None:
            content = self.factory(system, messages)
        else:
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                "",
            )
            content = f"(fake reply) 你問了：{last_user[:60]}"
        return ChatResult(
            content=content,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=estimate_cost(self.input_tokens, self.output_tokens),
        )


def build_chat() -> ChatClient:
    """Factory — 依設定吐 MinimaxChat / FakeChat。

    M6 預設走 MiniMax（即使 LLM_PROVIDER=anthropic 也走 MiniMax，因 Opus 改
    用 MiniMax 取代是專案決定）；缺 key 自動 fallback FakeChat 不阻塞 dev。
    """
    settings = get_settings()
    if not settings.minimax_api_key:
        logger.warning("MINIMAX_API_KEY 未設定 → QA 使用 FakeChat（不會真打 API）")
        return FakeChat()
    return MinimaxChat(
        api_key=settings.minimax_api_key,
        base_url=settings.minimax_base_url,
        model=settings.minimax_model,
    )


__all__ = [
    "MINIMAX_INPUT_PER_MTOK",
    "MINIMAX_OUTPUT_PER_MTOK",
    "ChatClient",
    "ChatResult",
    "FakeChat",
    "MinimaxChat",
    "build_chat",
    "estimate_cost",
]
