"""v5 newsroom contract tests — no live Reddit, Telegram, or LLM calls."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from reddit_tracker.newsroom.contracts import (
    AgentArtifact,
    AgentStage,
    Confidence,
    EditionPlan,
    SourceRef,
    StoryKind,
    StoryPitch,
)


def _source(n: int) -> SourceRef:
    return SourceRef(
        reddit_post_id=f"post{n}",
        subreddit="askreddit",
        original_title=f"Original title {n}",
        permalink=f"https://www.reddit.com/r/askreddit/comments/post{n}/",
        language="en",
        posted_at=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )


def _pitch(kind: StoryKind, n: int, *, source_count: int = 1) -> StoryPitch:
    return StoryPitch(
        kind=kind,
        beat="relationships",
        headline_zh=f"中文標題 {n}",
        angle="這是一個有來源、有脈絡的選題角度。",
        why_for_reader="符合讀者想看人際與日常故事的偏好。",
        source_refs=[_source(n * 10 + i) for i in range(source_count)],
        confidence=Confidence.MEDIUM,
    )


def test_feature_pitch_requires_two_sources():
    with pytest.raises(ValidationError, match="at least two Reddit sources"):
        _pitch(StoryKind.FEATURE, 1)


def test_edition_plan_accepts_the_confirmed_newspaper_shape():
    plan = EditionPlan(
        edition_date=date(2026, 9, 16),
        reader_id=1,
        briefs=[_pitch(StoryKind.BRIEF, n) for n in range(6)],
        features=[_pitch(StoryKind.FEATURE, 10, source_count=2), _pitch(StoryKind.FEATURE, 11, source_count=2)],
        editor_summary="人際故事與網路現象各有一篇主題專題，版面沒有重複。",
    )

    assert len(plan.briefs) + len(plan.features) == 8


def test_edition_plan_allows_one_source_backed_early_brief():
    plan = EditionPlan(
        edition_date=date(2026, 9, 16),
        reader_id=1,
        briefs=[_pitch(StoryKind.BRIEF, n) for n in range(6)],
        features=[_pitch(StoryKind.FEATURE, 10, source_count=2), _pitch(StoryKind.FEATURE, 11, source_count=2)],
        breaking=_pitch(StoryKind.BREAKING, 20),
        editor_summary="保留固定版面，另附一則來源可追溯的早報快訊。",
    )

    assert plan.breaking is not None
    assert plan.breaking.kind is StoryKind.BREAKING


def test_edition_plan_rejects_wrong_section_kind():
    with pytest.raises(ValidationError, match="briefs must contain only brief pitches"):
        EditionPlan(
            edition_date=date(2026, 9, 16),
            reader_id=1,
            briefs=[_pitch(StoryKind.FEATURE, n, source_count=2) for n in range(6)],
            features=[_pitch(StoryKind.FEATURE, 10, source_count=2), _pitch(StoryKind.FEATURE, 11, source_count=2)],
            editor_summary="這份錯誤版面必須被拒絕。",
        )


def test_agent_artifact_contains_only_inspectable_editorial_fields():
    artifact = AgentArtifact(
        stage=AgentStage.SCOUT,
        agent_name="採訪 agent",
        edition_date=date(2026, 9, 16),
        summary="挑出三個與讀者偏好最相關的候選故事。",
        source_refs=[_source(1)],
        reason_codes=["reader_topic_match"],
        confidence=Confidence.MEDIUM,
    )

    dumped = artifact.model_dump()
    assert "private_reasoning" not in dumped
    assert dumped["source_refs"][0]["reddit_post_id"] == "post1"
