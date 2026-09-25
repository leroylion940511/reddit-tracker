"""Contract tests for the one-request Gemini newsroom adapter."""

from __future__ import annotations

import json

import pytest

from reddit_tracker.llm.gemini import GeminiResult
from reddit_tracker.newsroom.gemini_writer import GeminiNewsroomWriter, GeminiWriterError
from tests.test_newsroom_writing import _planned_edition
from reddit_tracker.newsroom.writing import EvidenceAgent


class _FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, **kwargs) -> GeminiResult:
        self.calls += 1
        assert kwargs["json_mode"] is True
        return GeminiResult(content=self.response, input_tokens=10, output_tokens=20, cached_tokens=None)


def _pairs(session):
    edition, plan = _planned_edition(session)
    pitches = [*plan.briefs, *plan.features]
    from reddit_tracker.models import CandidatePost
    candidates = {candidate.reddit_post_id: candidate for candidate in session.query(CandidatePost).all()}
    return [
        (pitch, EvidenceAgent().build(pitch, [candidates[source.reddit_post_id] for source in pitch.source_refs]))
        for pitch in pitches
    ]


def test_gemini_writer_keeps_application_owned_sources_and_kinds(session):
    pairs = _pairs(session)
    response = json.dumps({"stories": [
        {
            "position": position,
            "headline_zh": f"第 {position} 則繁中標題",
            "deck_zh": "這是一段清楚的短導言，保留匿名社群內容的邊界。",
            "body_zh": "這是一段足夠長的繁中短報內容，僅整理原作者的公開自述，也提醒讀者這不是獨立查證後的外部事實。",
            "why_it_matters_zh": "它呈現一個值得讀者自行判斷的日常議題。",
        }
        for position in range(1, 9)
    ]}, ensure_ascii=False)
    client = _FakeClient(response)

    drafts = GeminiNewsroomWriter(client=client).draft_many(pairs)

    assert client.calls == 1
    assert [draft.kind for draft in drafts] == [pitch.kind for pitch, _ in pairs]
    assert [draft.source_refs for draft in drafts] == [pitch.source_refs for pitch, _ in pairs]


def test_gemini_writer_rejects_missing_article_position(session):
    pairs = _pairs(session)
    response = json.dumps({"stories": [
        {
            "position": position,
            "headline_zh": f"第 {position} 則繁中標題",
            "deck_zh": "這是一段清楚的短導言，保留匿名社群內容的邊界。",
            "body_zh": "這是一段足夠長的繁中短報內容，僅整理原作者的公開自述，也提醒讀者這不是獨立查證後的外部事實。",
            "why_it_matters_zh": "它呈現一個值得讀者自行判斷的日常議題。",
        }
        for position in range(1, 8)
    ]}, ensure_ascii=False)

    with pytest.raises(GeminiWriterError, match="validation"):
        GeminiNewsroomWriter(client=_FakeClient(response)).draft_many(pairs)


def test_gemini_writer_fills_only_missing_model_fields_from_safe_template(session):
    pairs = _pairs(session)
    response = json.dumps({"stories": [
        {
            "position": position,
            "headline_zh": f"第 {position} 則繁中標題",
            "deck_zh": "這是一段清楚的短導言，保留匿名社群內容的邊界。",
            "body_zh": "這是一段足夠長的繁中短報內容，僅整理原作者的公開自述，也提醒讀者這不是獨立查證後的外部事實。",
            **({} if position == 5 else {"why_it_matters_zh": "它呈現一個值得讀者自行判斷的日常議題。"}),
        }
        for position in range(1, 9)
    ]}, ensure_ascii=False)
    writer = GeminiNewsroomWriter(client=_FakeClient(response))

    drafts = writer.draft_many(pairs)

    assert writer.fallback_positions == (5,)
    assert drafts[4].headline_zh == "第 5 則繁中標題"
    assert drafts[4].why_it_matters_zh == pairs[4][0].why_for_reader


def test_gemini_writer_ignores_uncontracted_extra_model_fields(session):
    pairs = _pairs(session)
    response = json.dumps({"stories": [
        {
            "position": position,
            "headline_zh": f"第 {position} 則繁中標題",
            "deck_zh": "這是一段清楚的短導言，保留匿名社群內容的邊界。",
            "body_zh": "這是一段足夠長的繁中短報內容，僅整理原作者的公開自述，也提醒讀者這不是獨立查證後的外部事實。",
            "why_it_matters_zh": "它呈現一個值得讀者自行判斷的日常議題。",
            **({"debt_zh": "模型額外產生的欄位不會進入刊物。"} if position == 6 else {}),
        }
        for position in range(1, 9)
    ]}, ensure_ascii=False)
    writer = GeminiNewsroomWriter(client=_FakeClient(response))

    drafts = writer.draft_many(pairs)

    assert len(drafts) == 8
    assert writer.fallback_positions == ()
