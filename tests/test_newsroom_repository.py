"""N1 persistence tests for the AI newsroom ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from reddit_tracker.models import CandidatePost, EditionItem
from reddit_tracker.newsroom.repository import (
    complete_agent_run,
    create_reader_profile,
    get_or_create_edition,
    record_reader_feedback,
    start_agent_run,
)


NOW = datetime(2026, 9, 16, 0, 30, tzinfo=UTC)


def _candidate(session, rid: str = "candidate1") -> CandidatePost:
    candidate = CandidatePost(
        reddit_post_id=rid,
        subreddit="askreddit",
        title="Original Reddit title",
        selftext="A short but useful source post.",
        permalink=f"/r/askreddit/comments/{rid}/source/",
        author_username="source_author",
        posted_at=NOW - timedelta(hours=4),
    )
    session.add(candidate)
    session.flush()
    return candidate


def _edition(session, *, telegram_chat_id: int = 100):
    reader = create_reader_profile(
        session,
        telegram_chat_id=telegram_chat_id,
        preference_prompt="多看人際與日常，少看政治。",
        included_topics=["relationships", "daily_life"],
    )
    result = get_or_create_edition(
        session,
        reader=reader,
        edition_date=date(2026, 9, 16),
        window_start=NOW - timedelta(days=1, minutes=30),
        window_end=NOW - timedelta(minutes=30),
    )
    return reader, result.edition


def test_reader_profile_and_edition_are_idempotent(session):
    reader, edition = _edition(session)
    duplicate = get_or_create_edition(
        session,
        reader=reader,
        edition_date=edition.edition_date,
        window_start=edition.window_start,
        window_end=edition.window_end,
    )

    assert reader.timezone == "Asia/Taipei"
    assert reader.delivery_time == "08:30"
    assert reader.included_keywords == []
    assert reader.excluded_keywords == []
    assert duplicate.created is False
    assert duplicate.edition.id == edition.id


def test_reader_profile_persists_explicit_keyword_controls(session):
    reader = create_reader_profile(
        session,
        included_keywords=["remote work", "貓咪"],
        excluded_keywords=["劇透"],
    )

    assert reader.included_keywords == ["remote work", "貓咪"]
    assert reader.excluded_keywords == ["劇透"]


def test_edition_rejects_an_invalid_calendar_window(session):
    reader = create_reader_profile(session)
    with pytest.raises(ValueError, match="window_start"):
        get_or_create_edition(
            session,
            reader=reader,
            edition_date=date(2026, 9, 16),
            window_start=NOW,
            window_end=NOW,
        )


def test_agent_artifact_records_source_provenance_and_retry(session):
    _, edition = _edition(session)
    source = _candidate(session)
    first_run = start_agent_run(
        session,
        edition=edition,
        stage="scout",
        input_snapshot={"candidate_window": "2026-09-15"},
        now=NOW,
    )
    artifact = complete_agent_run(
        session,
        run=first_run,
        artifact_kind="story_pitch",
        summary="這個人際故事符合讀者偏好，且保留原始來源。",
        payload={"headline_zh": "一則值得聊的人際故事"},
        confidence="medium",
        source_candidate_ids=[source.id],
        now=NOW + timedelta(minutes=1),
    )
    retry = start_agent_run(session, edition=edition, stage="scout", now=NOW + timedelta(minutes=2))

    assert first_run.status == "succeeded"
    assert artifact.sources[0].candidate_post_id == source.id
    assert retry.attempt == 2


def test_agent_artifact_rejects_missing_candidate_source(session):
    _, edition = _edition(session)
    run = start_agent_run(session, edition=edition, stage="scout", now=NOW)

    with pytest.raises(ValueError, match="missing candidate"):
        complete_agent_run(
            session,
            run=run,
            artifact_kind="story_pitch",
            summary="不存在的來源不能出現在編輯室。",
            source_candidate_ids=[99999],
        )


def test_feedback_is_idempotent_and_cannot_cross_reader_boundary(session):
    reader, edition = _edition(session)
    item = EditionItem(edition_id=edition.id, kind="brief", position=1)
    session.add(item)
    session.flush()

    first = record_reader_feedback(session, reader=reader, edition_item=item, action="more")
    duplicate = record_reader_feedback(session, reader=reader, edition_item=item, action="more")
    other_reader = create_reader_profile(session, telegram_chat_id=101)
    unauthorized = record_reader_feedback(session, reader=other_reader, edition_item=item, action="follow")

    assert first.feedback is not None
    assert duplicate.duplicate is True
    assert unauthorized.item_not_owned is True
