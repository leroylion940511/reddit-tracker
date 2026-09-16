"""N3 tests for evidence boundaries, drafts, safety labels, and item sources."""

from __future__ import annotations

from datetime import date

from reddit_tracker.newsroom.planning import plan_edition, previous_calendar_day_window
from reddit_tracker.newsroom.repository import create_reader_profile, get_or_create_edition
from reddit_tracker.newsroom.writing import draft_edition
from tests.test_newsroom_planning import _seed_plan_candidates


def _planned_edition(session):
    edition_date = date(2026, 9, 17)
    window = previous_calendar_day_window(edition_date)
    reader = create_reader_profile(
        session,
        telegram_chat_id=100,
        preference_prompt="多看人際與台灣生活。",
        included_topics=["relationships", "taiwan_life"],
    )
    edition = get_or_create_edition(
        session,
        reader=reader,
        edition_date=edition_date,
        window_start=window.start_utc,
        window_end=window.end_utc,
    ).edition
    _seed_plan_candidates(session)
    return edition, plan_edition(session, edition=edition).plan


def test_drafting_creates_evidence_transparent_chinese_items_and_artifacts(session):
    edition, plan = _planned_edition(session)

    result = draft_edition(session, edition=edition, plan=plan)

    assert edition.status == "drafted"
    assert len(result.items) == 8
    assert len(result.evidence_briefs) == 8
    assert all("未經本系統獨立查證" in brief.uncertainty_notes[0] for brief in result.evidence_briefs)
    assert all(item.sources for item in result.items)
    assert all("原帖標題：" in draft.body_zh for draft in result.drafts)
    assert [run.stage for run in sorted(edition.agent_runs, key=lambda run: run.id)][-3:] == [
        "verification", "writing", "chief_editing",
    ]


def test_drafting_refuses_to_overwrite_an_existing_edition(session):
    edition, plan = _planned_edition(session)
    draft_edition(session, edition=edition, plan=plan)

    from reddit_tracker.newsroom.writing import NewsroomWritingError

    try:
        draft_edition(session, edition=edition, plan=plan)
    except NewsroomWritingError as exc:
        assert "already has drafted items" in str(exc)
    else:  # pragma: no cover - test guard
        raise AssertionError("expected NewsroomWritingError")
