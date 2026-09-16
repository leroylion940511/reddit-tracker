"""One-request Gemini writer for a source-bounded newsroom edition.

The model may improve Chinese prose only.  Our application owns article order,
story kind, confidence, warnings, source titles, and Reddit links.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings
from ..llm.gemini import GeminiClient, GeminiResult
from .contracts import EvidenceBrief, StoryDraft, StoryPitch


class _CompletionClient(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> GeminiResult: ...


class GeminiWriterError(ValueError):
    """The external writer returned an unusable edition; it is safe to fallback."""


class _GeneratedStory(BaseModel):
    position: int = Field(ge=1)
    headline_zh: str = Field(min_length=4, max_length=120)
    deck_zh: str = Field(min_length=8, max_length=300)
    body_zh: str = Field(min_length=40, max_length=900)
    why_it_matters_zh: str = Field(min_length=8, max_length=500)


class _GeneratedEdition(BaseModel):
    stories: list[_GeneratedStory] = Field(min_length=8, max_length=10)


SYSTEM_PROMPT = """你是台灣讀者版的謹慎新聞編輯。把提供的 Reddit 公開貼文脈絡寫成繁體中文短報。
只可改寫資料中明示的原作者自述，不可補造外部事實、人物身分、留言共識或因果。匿名社群內容必須保留不確定性。
每篇正文 100 到 180 個繁中文字，語氣自然、克制、可讀。輸出純 JSON，絕不輸出 Markdown 或額外文字。"""


class GeminiNewsroomWriter:
    """Batch all stories into one guarded Gemini request per edition."""

    name = "gemini_batch"

    def __init__(self, *, client: _CompletionClient | None = None) -> None:
        self.client = client or GeminiClient(
            purpose="newsroom",
            model=get_settings().gemini_newsroom_model,
        )

    def draft_many(
        self, pairs: list[tuple[StoryPitch, EvidenceBrief]]
    ) -> list[StoryDraft]:
        if not 8 <= len(pairs) <= 10:
            raise GeminiWriterError("Gemini writer requires a complete 8–10 item edition")
        request_items = []
        for position, (pitch, evidence) in enumerate(pairs, start=1):
            request_items.append({
                "position": position,
                "kind": pitch.kind.value,
                "beat": pitch.beat,
                "reader_angle": pitch.why_for_reader,
                "source_titles": [source.original_title for source in pitch.source_refs],
                "author_statements": [claim.statement_zh for claim in evidence.claims],
                "uncertainty": evidence.uncertainty_notes,
                "warnings": evidence.content_warnings,
            })
        prompt = (
            "請替以下版面寫稿。每個 position 必須恰好出現一次。回傳結構："
            '{"stories":[{"position":1,"headline_zh":"...","deck_zh":"...",'
            '"body_zh":"...","why_it_matters_zh":"..."}]}。\n\n'
            + json.dumps({"stories": request_items}, ensure_ascii=False, separators=(",", ":"))
        )
        try:
            result = self.client.complete(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_output_tokens=6_000,
                temperature=0.35,
                json_mode=True,
            )
            generated = _GeneratedEdition.model_validate_json(result.content)
        except (ValidationError, ValueError, TypeError) as exc:
            raise GeminiWriterError(f"Gemini JSON failed validation: {exc}") from exc
        except Exception as exc:
            raise GeminiWriterError(f"Gemini request failed: {exc}") from exc

        by_position = {story.position: story for story in generated.stories}
        expected = set(range(1, len(pairs) + 1))
        if set(by_position) != expected or len(by_position) != len(generated.stories):
            raise GeminiWriterError("Gemini response must contain each requested position exactly once")
        return [
            StoryDraft(
                kind=pitch.kind,
                headline_zh=by_position[position].headline_zh,
                deck_zh=by_position[position].deck_zh,
                body_zh=by_position[position].body_zh,
                why_it_matters_zh=by_position[position].why_it_matters_zh,
                source_refs=pitch.source_refs,
                confidence=evidence.confidence,
                content_warnings=evidence.content_warnings,
            )
            for position, (pitch, evidence) in enumerate(pairs, start=1)
        ]


__all__ = ["GeminiNewsroomWriter", "GeminiWriterError"]
