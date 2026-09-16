"""N2 tests: calendar window, reader-aware scouting, and diverse edition plans."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from reddit_tracker.models import CandidatePost
from reddit_tracker.newsroom.planning import (
    EditorialPlanningError,
    ReaderProfileAgent,
    ScoutAgent,
    fetch_window_candidates,
    plan_edition,
    previous_calendar_day_window,
)
from reddit_tracker.newsroom.repository import create_reader_profile, get_or_create_edition


EDITION_DATE = date(2026, 9, 17)
WINDOW = previous_calendar_day_window(EDITION_DATE)


def _candidate(session, *, rid: str, subreddit: str, title: str, posted_at: datetime) -> CandidatePost:
    candidate = CandidatePost(
        reddit_post_id=rid,
        subreddit=subreddit,
        title=title,
        selftext="A source-backed discussion for the daily newspaper.",
        permalink=f"/r/{subreddit}/comments/{rid}/source/",
        author_username="source_author",
        posted_at=posted_at,
        lang="en",
        initial_num_comments=10,
    )
    session.add(candidate)
    session.flush()
    return candidate


def _reader_and_edition(session):
    reader = create_reader_profile(
        session,
        telegram_chat_id=100,
        preference_prompt="我想多看台灣生活和人際故事，少看政治。",
        included_topics=["taiwan_life", "relationships"],
        excluded_subreddits=["politics"],
    )
    edition = get_or_create_edition(
        session,
        reader=reader,
        edition_date=EDITION_DATE,
        window_start=WINDOW.start_utc,
        window_end=WINDOW.end_utc,
    ).edition
    return reader, edition


def _seed_plan_candidates(session, *, limit: int | None = None) -> list[CandidatePost]:
    base = WINDOW.start_utc + timedelta(hours=4)
    specs = [
        ("r1", "relationship_advice", "My partner and I disagree about boundaries"),
        ("r2", "offmychest", "A friendship changed after a difficult conversation"),
        ("t1", "taiwan", "A small Taiwan daily life surprise"),
        ("t2", "taipei", "What makes a neighborhood feel like home"),
        ("a1", "askreddit", "What small habit changed your day"),
        ("a2", "askreddit", "What online opinion surprised you most"),
        ("w1", "careerguidance", "How I handled an awkward job conversation"),
        ("w2", "jobs", "A lesson from my first week at work"),
        ("h1", "todayilearned", "An unexpectedly kind thing a stranger did"),
        ("h2", "casualconversation", "A small story that made people smile"),
    ]
    selected_specs = specs if limit is None else specs[:limit]
    return [
        _candidate(
            session,
            rid=rid,
            subreddit=subreddit,
            title=title,
            posted_at=base + timedelta(minutes=index),
        )
        for index, (rid, subreddit, title) in enumerate(selected_specs)
    ]


def test_previous_calendar_window_uses_taiwan_day_boundaries():
    assert WINDOW.source_date == date(2026, 9, 16)
    assert WINDOW.start_utc == datetime(2026, 9, 15, 16, tzinfo=UTC)
    assert WINDOW.end_utc == datetime(2026, 9, 16, 16, tzinfo=UTC)


def test_fetch_window_candidates_excludes_posts_outside_previous_day(session):
    inside = _candidate(
        session,
        rid="inside",
        subreddit="taiwan",
        title="Inside the window",
        posted_at=WINDOW.start_utc + timedelta(minutes=1),
    )
    _candidate(
        session,
        rid="before",
        subreddit="taiwan",
        title="Before the window",
        posted_at=WINDOW.start_utc - timedelta(seconds=1),
    )
    _candidate(
        session,
        rid="after",
        subreddit="taiwan",
        title="After the window",
        posted_at=WINDOW.end_utc,
    )

    assert [candidate.id for candidate in fetch_window_candidates(session, WINDOW)] == [inside.id]


def test_scout_respects_subreddit_exclusions_and_reader_priority(session):
    reader, _ = _reader_and_edition(session)
    taiwan = _candidate(
        session,
        rid="tw",
        subreddit="taiwan",
        title="A Taiwan life story",
        posted_at=WINDOW.start_utc + timedelta(hours=1),
    )
    _candidate(
        session,
        rid="politics",
        subreddit="politics",
        title="A political thread",
        posted_at=WINDOW.start_utc + timedelta(hours=2),
    )
    brief = ReaderProfileAgent().build(reader, edition_date=EDITION_DATE)
    scouted = ScoutAgent().scout(fetch_window_candidates(session, WINDOW), brief, reader)

    assert scouted[0].candidate_ids == (taiwan.id,)
    assert all("politics" not in pitch.pitch.source_refs[0].subreddit for pitch in scouted)
    assert scouted[0].pitch.source_refs[0].permalink.host == "www.reddit.com"


def test_planner_persists_three_visible_agent_stages_and_an_eight_item_plan(session):
    _, edition = _reader_and_edition(session)
    _seed_plan_candidates(session)

    result = plan_edition(session, edition=edition)

    assert result.candidate_count == 10
    assert len(result.plan.briefs) == 6
    assert len(result.plan.features) == 2
    assert all(len(pitch.source_refs) == 1 for pitch in result.plan.briefs)
    assert all(len(pitch.source_refs) == 2 for pitch in result.plan.features)
    runs = sorted(edition.agent_runs, key=lambda run: run.id)
    assert [run.stage for run in runs] == ["reader_profile", "scout", "assignment"]
    assert all(run.status == "succeeded" for run in runs)
    assert all(artifact.sources for run in runs[1:] for artifact in run.artifacts)


def test_planner_rejects_insufficient_candidates_without_a_fake_edition(session):
    _, edition = _reader_and_edition(session)
    _seed_plan_candidates(session, limit=7)

    with pytest.raises(EditorialPlanningError, match="insufficient"):
        plan_edition(session, edition=edition)

    assert edition.status == "planned"
    assert max(edition.agent_runs, key=lambda run: run.id).status == "failed"
