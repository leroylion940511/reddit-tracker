"""Persistence helpers for the v5 newsroom ledger.

These functions contain no LLM, Reddit, or Telegram side effects. They make
edition creation and agent stage records idempotent and testable before the
orchestrator is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AgentArtifactRecord,
    AgentArtifactSource,
    AgentRun,
    CandidatePost,
    EditionItem,
    NewsroomEdition,
    ReaderFeedback,
    ReaderProfile,
)


VALID_FEEDBACK_ACTIONS = {"more", "less", "follow"}


@dataclass(frozen=True)
class EditionOutcome:
    edition: NewsroomEdition
    created: bool


@dataclass(frozen=True)
class FeedbackOutcome:
    feedback: ReaderFeedback | None
    duplicate: bool = False
    invalid_action: bool = False
    item_not_owned: bool = False


def create_reader_profile(
    session: Session,
    *,
    telegram_chat_id: int | None = None,
    preference_prompt: str | None = None,
    included_topics: list[str] | None = None,
    excluded_topics: list[str] | None = None,
    included_subreddits: list[str] | None = None,
    excluded_subreddits: list[str] | None = None,
    timezone_name: str = "Asia/Taipei",
    delivery_time: str = "08:30",
) -> ReaderProfile:
    """Create a reader profile; caller owns the transaction."""
    profile = ReaderProfile(
        telegram_chat_id=telegram_chat_id,
        preference_prompt=preference_prompt,
        included_topics=included_topics or [],
        excluded_topics=excluded_topics or [],
        included_subreddits=included_subreddits or [],
        excluded_subreddits=excluded_subreddits or [],
        timezone=timezone_name,
        delivery_time=delivery_time,
    )
    session.add(profile)
    session.flush()
    return profile


def get_or_create_edition(
    session: Session,
    *,
    reader: ReaderProfile,
    edition_date: date,
    window_start: datetime,
    window_end: datetime,
) -> EditionOutcome:
    """Return the unique edition for a reader/date without creating a duplicate."""
    if window_start >= window_end:
        raise ValueError("edition window_start must be before window_end")

    existing = session.scalar(
        select(NewsroomEdition).where(
            NewsroomEdition.reader_profile_id == reader.id,
            NewsroomEdition.edition_date == edition_date,
        )
    )
    if existing is not None:
        return EditionOutcome(edition=existing, created=False)

    edition = NewsroomEdition(
        reader_profile_id=reader.id,
        edition_date=edition_date,
        window_start=window_start,
        window_end=window_end,
    )
    session.add(edition)
    session.flush()
    return EditionOutcome(edition=edition, created=True)


def start_agent_run(
    session: Session,
    *,
    edition: NewsroomEdition,
    stage: str,
    input_snapshot: dict | None = None,
    now: datetime | None = None,
) -> AgentRun:
    """Start the next numbered attempt for an edition stage."""
    next_attempt = (session.scalar(
        select(func.max(AgentRun.attempt)).where(
            AgentRun.edition_id == edition.id,
            AgentRun.stage == stage,
        )
    ) or 0) + 1
    run = AgentRun(
        edition_id=edition.id,
        stage=stage,
        attempt=int(next_attempt),
        input_snapshot=input_snapshot,
        started_at=now or datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    return run


def complete_agent_run(
    session: Session,
    *,
    run: AgentRun,
    artifact_kind: str,
    summary: str,
    payload: dict | None = None,
    confidence: str | None = None,
    warnings: list[str] | None = None,
    source_candidate_ids: list[int] | None = None,
    now: datetime | None = None,
) -> AgentArtifactRecord:
    """Persist an inspectable artifact and mark its run succeeded.

    Source ids are resolved before writing so an artifact cannot claim a
    candidate that is absent from the local Reddit cache.
    """
    if run.status != "running":
        raise ValueError("only a running agent run can be completed")
    source_ids = list(dict.fromkeys(source_candidate_ids or []))
    candidates = []
    if source_ids:
        candidates = list(session.scalars(
            select(CandidatePost).where(CandidatePost.id.in_(source_ids))
        ).all())
        found_ids = {candidate.id for candidate in candidates}
        missing = [candidate_id for candidate_id in source_ids if candidate_id not in found_ids]
        if missing:
            raise ValueError(f"artifact sources missing candidate ids: {missing}")

    artifact = AgentArtifactRecord(
        agent_run_id=run.id,
        artifact_kind=artifact_kind,
        summary=summary,
        payload=payload,
        confidence=confidence,
        warnings=warnings or [],
    )
    session.add(artifact)
    session.flush()
    by_id = {candidate.id: candidate for candidate in candidates}
    for source_order, candidate_id in enumerate(source_ids, start=1):
        session.add(AgentArtifactSource(
            agent_artifact_id=artifact.id,
            candidate_post_id=by_id[candidate_id].id,
            source_order=source_order,
        ))
    run.status = "succeeded"
    run.completed_at = now or datetime.now(timezone.utc)
    session.flush()
    return artifact


def fail_agent_run(
    session: Session,
    *,
    run: AgentRun,
    error_message: str,
    now: datetime | None = None,
) -> AgentRun:
    """Record a failed stage explicitly instead of silently returning no output."""
    if run.status != "running":
        raise ValueError("only a running agent run can be failed")
    run.status = "failed"
    run.error_message = error_message[:2_000]
    run.completed_at = now or datetime.now(timezone.utc)
    session.flush()
    return run


def record_reader_feedback(
    session: Session,
    *,
    reader: ReaderProfile,
    edition_item: EditionItem,
    action: str,
) -> FeedbackOutcome:
    """Record one idempotent Telegram feedback action for a reader's own item."""
    if action not in VALID_FEEDBACK_ACTIONS:
        return FeedbackOutcome(feedback=None, invalid_action=True)
    if edition_item.edition.reader_profile_id != reader.id:
        return FeedbackOutcome(feedback=None, item_not_owned=True)
    existing = session.scalar(
        select(ReaderFeedback).where(
            ReaderFeedback.reader_profile_id == reader.id,
            ReaderFeedback.edition_item_id == edition_item.id,
            ReaderFeedback.action == action,
        )
    )
    if existing is not None:
        return FeedbackOutcome(feedback=existing, duplicate=True)
    feedback = ReaderFeedback(
        reader_profile_id=reader.id,
        edition_item_id=edition_item.id,
        action=action,
    )
    session.add(feedback)
    session.flush()
    return FeedbackOutcome(feedback=feedback)


__all__ = [
    "EditionOutcome",
    "FeedbackOutcome",
    "VALID_FEEDBACK_ACTIONS",
    "complete_agent_run",
    "create_reader_profile",
    "fail_agent_run",
    "get_or_create_edition",
    "record_reader_feedback",
    "start_agent_run",
]
