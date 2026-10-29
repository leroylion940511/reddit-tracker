"""Gemini Developer API provider with local free-tier guardrails.

The Gemini API's published free-tier request limits are project-specific.  This
module therefore applies conservative, cross-process local limits before a
request is made and retries temporary 429 responses.  The daily count is keyed
by model (shared with every purpose), and every HTTP attempt — retries included —
consumes one unit.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from ..config import get_settings
from .quota import ModelQuotaGuard, QuotaExhausted

logger = logging.getLogger(__name__)

_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiAPIError(RuntimeError):
    """A Gemini response that cannot be safely handled by this project."""


class GeminiQuotaExhausted(GeminiAPIError, QuotaExhausted):
    """The local guard or Gemini API reports a request/rate quota problem."""


@dataclass(frozen=True)
class GeminiResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


class GeminiQuotaGuard(ModelQuotaGuard):
    """Model-keyed daily quota (shared by every purpose) plus a per-minute request cap."""

    def __init__(self, *, state_path: str, daily_limit: int, requests_per_minute: int) -> None:
        super().__init__(state_path=state_path, daily_limit=daily_limit, requests_per_minute=requests_per_minute)

    def acquire(self, *, model: str, purpose: str) -> None:
        try:
            super().acquire(model=model, purpose=purpose)
        except QuotaExhausted as exc:
            if isinstance(exc, GeminiQuotaExhausted):
                raise
            raise GeminiQuotaExhausted(str(exc)) from exc


class GeminiClient:
    """Minimal REST client so the project does not need a second vendor SDK."""

    def __init__(
        self,
        *,
        purpose: str,
        api_key: str | None = None,
        model: str | None = None,
        daily_limit: int | None = None,
        requests_per_minute: int | None = None,
        state_path: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY 未設定")
        self.purpose = purpose
        self.model = model or settings.gemini_daily_model
        self.timeout = timeout if timeout is not None else settings.gemini_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.gemini_max_429_retries
        limit = daily_limit if daily_limit is not None else settings.llm_daily_limit
        self.guard = GeminiQuotaGuard(
            state_path=state_path or settings.llm_quota_state_path,
            daily_limit=limit,
            requests_per_minute=requests_per_minute or settings.gemini_requests_per_minute,
        )
        self._session = requests.Session()
        self._session.headers.update({
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        })

    @staticmethod
    def _contents(messages: list[dict]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": content}],
            })
        if not contents:
            raise ValueError("Gemini requires at least one user or assistant message")
        return contents

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After")
        try:
            return max(1.0, min(float(raw), 30.0)) if raw else min(2 ** attempt, 15.0)
        except ValueError:
            return min(2 ** attempt, 15.0)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        json_schema: dict | None = None,  # 介面與 CodexClient 一致；Gemini 只用 json_mode
    ) -> GeminiResult:
        generation_config: dict[str, Any] = {
            "maxOutputTokens": max_output_tokens,
            "temperature": temperature,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": self._contents(messages),
            "generationConfig": generation_config,
        }
        url = f"{_API_URL}/{self.model}:generateContent"

        for attempt in range(self.max_retries + 1):
            self.guard.acquire(model=self.model, purpose=self.purpose)
            try:
                response = self._session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                raise GeminiAPIError("Gemini API network request failed") from exc
            if response.status_code == 429:
                if attempt == self.max_retries:
                    raise GeminiQuotaExhausted("Gemini API returned 429 after retries")
                delay = self._retry_delay(response, attempt)
                logger.warning("Gemini API returned 429; retrying in %.1fs", delay)
                time.sleep(delay)
                continue
            if not response.ok:
                try:
                    error = (response.json().get("error") or {}).get("message", "")
                except ValueError:
                    error = ""
                detail = f": {str(error)[:300]}" if error else ""
                raise GeminiAPIError(f"Gemini API returned HTTP {response.status_code}{detail}")
            try:
                data = response.json()
            except ValueError as exc:
                raise GeminiAPIError("Gemini API returned invalid JSON") from exc
            candidates = data.get("candidates") or []
            parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
            text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
            if not text:
                reason = candidates[0].get("finishReason") if candidates else "no candidate"
                raise GeminiAPIError(f"Gemini API returned no usable text ({reason})")
            usage = data.get("usageMetadata") or {}
            return GeminiResult(
                content=text,
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                cached_tokens=usage.get("cachedContentTokenCount"),
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        self._session.close()


__all__ = [
    "GeminiAPIError",
    "GeminiClient",
    "GeminiQuotaExhausted",
    "GeminiQuotaGuard",
    "GeminiResult",
]
