"""Validated, source-first contracts shared by every v5 newsroom agent.

These Pydantic models are deliberately limited to inspectable artifacts. They
model editorial outputs and provenance, not a model's private reasoning.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, model_validator


class AgentStage(StrEnum):
    """Ordered, visible stages in one edition's editorial ledger."""

    READER_PROFILE = "reader_profile"
    SCOUT = "scout"
    ASSIGNMENT = "assignment"
    VERIFICATION = "verification"
    WRITING = "writing"
    CHIEF_EDITING = "chief_editing"
    LEARNING = "learning"


class StoryKind(StrEnum):
    BRIEF = "brief"
    FEATURE = "feature"
    BREAKING = "breaking"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceKind(StrEnum):
    AUTHOR_STATEMENT = "author_statement"
    COMMUNITY_RESPONSE = "community_response"
    EDITORIAL_CONTEXT = "editorial_context"


class SourceRef(BaseModel):
    """A public Reddit source required for every pitch and published item."""

    reddit_post_id: str = Field(min_length=1, max_length=16)
    subreddit: str = Field(min_length=1, max_length=64)
    original_title: str = Field(min_length=1, max_length=500)
    permalink: HttpUrl
    language: str = Field(min_length=2, max_length=8)
    posted_at: datetime


class ReaderBrief(BaseModel):
    """Inspectable interpretation of a reader's current preferences."""

    reader_id: int = Field(gt=0)
    edition_date: date
    priority_topics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    priority_subreddits: list[str] = Field(default_factory=list)
    excluded_subreddits: list[str] = Field(default_factory=list)
    priority_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=500)


class StoryPitch(BaseModel):
    """A source-backed candidate pitch produced by the scout agent."""

    kind: StoryKind
    beat: str = Field(min_length=1, max_length=64)
    headline_zh: str = Field(min_length=1, max_length=120)
    angle: str = Field(min_length=1, max_length=500)
    why_for_reader: str = Field(min_length=1, max_length=500)
    source_refs: list[SourceRef] = Field(min_length=1)
    confidence: Confidence
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def feature_needs_multiple_sources(self) -> "StoryPitch":
        if self.kind is StoryKind.FEATURE and len(self.source_refs) < 2:
            raise ValueError("feature pitches require at least two Reddit sources")
        return self


class EditionPlan(BaseModel):
    """The publishable shape of one daily edition before drafting begins."""

    edition_date: date
    reader_id: int = Field(gt=0)
    briefs: list[StoryPitch] = Field(min_length=6, max_length=8)
    features: list[StoryPitch] = Field(min_length=1, max_length=2)
    breaking: StoryPitch | None = None
    editor_summary: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_newspaper_shape(self) -> "EditionPlan":
        if any(pitch.kind is not StoryKind.BRIEF for pitch in self.briefs):
            raise ValueError("briefs must contain only brief pitches")
        if any(pitch.kind is not StoryKind.FEATURE for pitch in self.features):
            raise ValueError("features must contain only feature pitches")
        if self.breaking is not None and self.breaking.kind is not StoryKind.BREAKING:
            raise ValueError("breaking item must use kind=breaking")
        if not 8 <= len(self.briefs) + len(self.features) <= 10:
            raise ValueError("an edition requires 8–10 regular items")
        return self


class AgentArtifact(BaseModel):
    """A public, auditable ledger entry for one agent stage run."""

    stage: AgentStage
    agent_name: str = Field(min_length=1, max_length=80)
    edition_date: date
    summary: str = Field(min_length=1, max_length=1_000)
    source_refs: list[SourceRef] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    confidence: Confidence | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceClaim(BaseModel):
    """A source-attributed statement visible in the newsroom evidence card."""

    kind: EvidenceKind
    statement_zh: str = Field(min_length=1, max_length=1_000)
    source_post_ids: list[str] = Field(min_length=1)


class EvidenceBrief(BaseModel):
    """The verification agent's bounded, source-first brief for one pitch."""

    headline_zh: str = Field(min_length=1, max_length=120)
    claims: list[EvidenceClaim] = Field(min_length=1)
    uncertainty_notes: list[str] = Field(min_length=1)
    content_warnings: list[str] = Field(default_factory=list)
    confidence: Confidence


class StoryDraft(BaseModel):
    """A ready-to-publish Chinese draft; source refs remain mandatory."""

    kind: StoryKind
    headline_zh: str = Field(min_length=1, max_length=120)
    deck_zh: str = Field(min_length=1, max_length=300)
    body_zh: str = Field(min_length=1, max_length=3_000)
    why_it_matters_zh: str = Field(min_length=1, max_length=500)
    source_refs: list[SourceRef] = Field(min_length=1)
    confidence: Confidence
    content_warnings: list[str] = Field(default_factory=list)
