"""N2 tests: calendar window, reader-aware scouting, and diverse edition plans."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from reddit_tracker.models import CandidatePost, EditionItem, EditionItemSource
from reddit_tracker.newsroom.planning import (
    EditorialPlanningError,
    LearningAgent,
    ReaderProfileAgent,
    ScoutAgent,
    fetch_breaking_candidates,
    fetch_window_candidates,
    plan_edition,
    previous_calendar_day_window,
)
from reddit_tracker.newsroom.repository import create_reader_profile, get_or_create_edition, record_reader_feedback


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


def _seed_plan_candidates(
    session,
    *,
    limit: int | None = None,
    window=WINDOW,
) -> list[CandidatePost]:
    base = window.start_utc + timedelta(hours=4)
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


def test_scout_applies_keyword_priority_and_exclusion(session):
    reader, _ = _reader_and_edition(session)
    reader.included_keywords = ["ceramic mug"]
    reader.excluded_keywords = ["spoiler"]
    preferred = _candidate(
        session,
        rid="keywordpref",
        subreddit="casualconversation",
        title="My ceramic mug survived another busy workday",
        posted_at=WINDOW.start_utc + timedelta(hours=1),
    )
    _candidate(
        session,
        rid="keywordskip",
        subreddit="casualconversation",
        title="Ceramic mug spoiler discussion",
        posted_at=WINDOW.start_utc + timedelta(hours=2),
    )
    ordinary = _candidate(
        session,
        rid="keywordplain",
        subreddit="casualconversation",
        title="A small daily habit",
        posted_at=WINDOW.start_utc + timedelta(hours=3),
    )

    brief = ReaderProfileAgent().build(reader, edition_date=EDITION_DATE)
    scouted = ScoutAgent().scout(fetch_window_candidates(session, WINDOW), brief, reader)

    assert brief.priority_keywords == ["ceramic mug"]
    assert brief.excluded_keywords == ["spoiler"]
    assert scouted[0].candidate_ids == (preferred.id,)
    assert all(item.candidate_ids != (ordinary.id,) or item.relevance < scouted[0].relevance for item in scouted)
    assert all("spoiler" not in item.pitch.source_refs[0].original_title.casefold() for item in scouted)


def test_same_morning_high_activity_candidate_becomes_an_optional_early_brief(session):
    edition_date = date(2026, 9, 18)
    window = previous_calendar_day_window(edition_date)
    reader = create_reader_profile(
        session,
        telegram_chat_id=101,
        preference_prompt="多看台灣生活與人際故事。",
        included_topics=["taiwan_life", "relationships"],
    )
    edition = get_or_create_edition(
        session,
        reader=reader,
        edition_date=edition_date,
        window_start=window.start_utc,
        window_end=window.end_utc,
    ).edition
    _seed_plan_candidates(session, window=window)
    now = datetime(2026, 9, 17, 21, 30, tzinfo=UTC)  # 05:30 Asia/Taipei
    fast = _candidate(
        session,
        rid="fastbrief",
        subreddit="taiwan",
        title="A high-interest morning Taiwan discussion",
        posted_at=now - timedelta(hours=2),
    )
    fast.initial_score = 250
    fast.initial_num_comments = 40

    assert fetch_breaking_candidates(
        session,
        edition_date=edition_date,
        timezone_name="Asia/Taipei",
        now=now,
    ) == [fast]
    result = plan_edition(session, edition=edition, now=now)

    assert result.plan.breaking is not None
    assert result.plan.breaking.kind.value == "breaking"
    assert result.plan.breaking.source_refs[0].reddit_post_id == fast.reddit_post_id
    assignment = next(run for run in edition.agent_runs if run.stage == "assignment")
    assert assignment.artifacts[0].payload["breaking"]["kind"] == "breaking"


def test_historical_editions_do_not_insert_a_stale_early_brief(session):
    reader, _ = _reader_and_edition(session)
    candidate = _candidate(
        session,
        rid="oldbrief",
        subreddit="taiwan",
        title="Yesterday's high-interest discussion",
        posted_at=WINDOW.start_utc + timedelta(hours=2),
    )
    candidate.initial_score = 500
    candidate.initial_num_comments = 100

    assert fetch_breaking_candidates(
        session,
        edition_date=EDITION_DATE,
        timezone_name=reader.timezone,
        now=datetime(2026, 9, 18, 0, tzinfo=UTC),
    ) == []


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
    assert [run.stage for run in runs] == ["learning", "reader_profile", "scout", "assignment"]
    assert all(run.status == "succeeded" for run in runs)
    assert all(artifact.sources for run in runs[2:] for artifact in run.artifacts)


def test_planner_rejects_insufficient_candidates_without_a_fake_edition(session):
    _, edition = _reader_and_edition(session)
    _seed_plan_candidates(session, limit=7)

    with pytest.raises(EditorialPlanningError, match="insufficient"):
        plan_edition(session, edition=edition)

    assert edition.status == "planned"
    assert max(edition.agent_runs, key=lambda run: run.id).status == "failed"


def test_learning_needs_repeated_positive_feedback_before_adjusting_topics(session):
    reader, edition = _reader_and_edition(session)
    candidates = _seed_plan_candidates(session)
    for position, candidate in enumerate(candidates[:2], start=1):
        item = EditionItem(edition_id=edition.id, kind="brief", position=position)
        session.add(item)
        session.flush()
        session.add(EditionItemSource(edition_item_id=item.id, candidate_post_id=candidate.id))
        record_reader_feedback(session, reader=reader, edition_item=item, action="more")

    learning = LearningAgent().build(session, reader=reader)

    assert "relationships" in learning.priority_topics
    assert len(learning.source_candidate_ids) == 2
