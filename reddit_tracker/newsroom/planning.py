"""N2 reader-aware editorial planning for one daily newsroom edition.

The first planner is deliberately deterministic: it proves calendar windows,
preference filtering, source provenance, and edition diversity before an LLM is
allowed to write or judge stories in N3.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CandidatePost, NewsroomEdition, ReaderProfile
from .contracts import (
    AgentStage,
    Confidence,
    EditionPlan,
    ReaderBrief,
    SourceRef,
    StoryKind,
    StoryPitch,
)
from .repository import complete_agent_run, fail_agent_run, start_agent_run


class EditorialPlanningError(ValueError):
    """Raised when a valid 8–10 item newspaper cannot be planned."""


@dataclass(frozen=True)
class CandidateWindow:
    """The UTC bounds for an edition's previous local calendar day."""

    edition_date: date
    source_date: date
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True)
class ScoutedPitch:
    pitch: StoryPitch
    candidate_ids: tuple[int, ...]
    relevance: float


@dataclass(frozen=True)
class PlanningResult:
    reader_brief: ReaderBrief
    plan: EditionPlan
    candidate_count: int


BEAT_LABELS = {
    "relationships": "人際與情感",
    "daily_life": "職場與日常",
    "internet_culture": "網路現象",
    "taiwan_life": "台灣與華語生活",
    "human_interest": "人物故事",
}

RELATIONSHIP_SUBREDDITS = {
    "relationship_advice",
    "relationships",
    "amitheasshole",
    "offmychest",
    "trueoffmychest",
}
TAIWAN_SUBREDDITS = {"taiwan", "taipei", "hongkong", "chinatime"}
DAILY_SUBREDDITS = {"careerguidance", "jobs", "work", "family", "parenting"}


def previous_calendar_day_window(
    edition_date: date,
    *,
    timezone_name: str = "Asia/Taipei",
) -> CandidateWindow:
    """Return yesterday 00:00–24:00 in reader time, represented in UTC."""
    try:
        local_timezone = ZoneInfo(timezone_name)
    except Exception as exc:  # pragma: no cover - platform zoneinfo detail
        raise EditorialPlanningError(f"unknown reader timezone: {timezone_name}") from exc
    source_date = edition_date - timedelta(days=1)
    local_start = datetime.combine(source_date, time.min, tzinfo=local_timezone)
    local_end = local_start + timedelta(days=1)
    return CandidateWindow(
        edition_date=edition_date,
        source_date=source_date,
        start_utc=local_start.astimezone(UTC),
        end_utc=local_end.astimezone(UTC),
    )


def fetch_window_candidates(session: Session, window: CandidateWindow) -> list[CandidatePost]:
    """Load source candidates in the edition window, newest first.

    RSS data occasionally lacks `posted_at`; `discovered_at` is the explicit
    fallback so every selected story has a stable temporal provenance.
    """
    reference_time = func.coalesce(CandidatePost.posted_at, CandidatePost.discovered_at)
    statement = (
        select(CandidatePost)
        .where(reference_time >= window.start_utc, reference_time < window.end_utc)
        .order_by(reference_time.desc(), CandidatePost.id.desc())
    )
    return list(session.scalars(statement).all())


def _normalise_topic(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _profile_tokens(profile: ReaderProfile) -> set[str]:
    values = list(profile.included_topics or [])
    values.extend(re.findall(r"[\w\u4e00-\u9fff-]+", profile.preference_prompt or ""))
    return {_normalise_topic(value) for value in values if value.strip()}


def _classify_beat(candidate: CandidatePost) -> str:
    subreddit = candidate.subreddit.lower()
    text = " ".join(filter(None, [candidate.title, candidate.selftext])).lower()
    if subreddit in TAIWAN_SUBREDDITS:
        return "taiwan_life"
    if subreddit in RELATIONSHIP_SUBREDDITS or any(
        word in text for word in ("relationship", "partner", "dating", "marriage", "friendship")
    ):
        return "relationships"
    if subreddit in DAILY_SUBREDDITS or any(
        word in text for word in ("work", "job", "family", "parent", "school")
    ):
        return "daily_life"
    if subreddit in {"askreddit", "outoftheloop", "nostupidquestions"}:
        return "internet_culture"
    return "human_interest"


def _absolute_permalink(permalink: str | None, *, subreddit: str, reddit_post_id: str) -> str:
    if permalink and permalink.startswith(("https://", "http://")):
        return permalink
    path = permalink or f"/r/{subreddit}/comments/{reddit_post_id}/"
    return f"https://www.reddit.com/{path.lstrip('/')}"


def _source_ref(candidate: CandidatePost) -> SourceRef:
    timestamp = candidate.posted_at or candidate.discovered_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return SourceRef(
        reddit_post_id=candidate.reddit_post_id,
        subreddit=candidate.subreddit,
        original_title=candidate.title or "（原帖未提供標題）",
        permalink=_absolute_permalink(
            candidate.permalink,
            subreddit=candidate.subreddit,
            reddit_post_id=candidate.reddit_post_id,
        ),
        language=candidate.lang or "und",
        posted_at=timestamp,
    )


class ReaderProfileAgent:
    """Turns explicit profile settings into an inspectable daily brief."""

    def build(self, profile: ReaderProfile, *, edition_date: date) -> ReaderBrief:
        priority_topics = [_normalise_topic(topic) for topic in profile.included_topics or []]
        excluded_topics = [_normalise_topic(topic) for topic in profile.excluded_topics or []]
        prompt = profile.preference_prompt or "尚未設定自然語言偏好。"
        return ReaderBrief(
            reader_id=profile.id,
            edition_date=edition_date,
            priority_topics=priority_topics,
            excluded_topics=excluded_topics,
            summary=(
                f"本期優先主題：{', '.join(priority_topics) or '依預設綜合版面'}；"
                f"排除：{', '.join(excluded_topics) or '無'}。讀者設定：{prompt}"
            )[:500],
        )


class ScoutAgent:
    """Ranks source-backed Reddit candidates without generating final prose."""

    def scout(self, candidates: list[CandidatePost], brief: ReaderBrief, profile: ReaderProfile) -> list[ScoutedPitch]:
        excluded_topics = set(brief.excluded_topics)
        excluded_subreddits = {
            subreddit.lower() for subreddit in (profile.excluded_subreddits or [])
        }
        preference_tokens = _profile_tokens(profile)
        scouted: list[ScoutedPitch] = []
        for candidate in candidates:
            if not candidate.title or candidate.subreddit.lower() in excluded_subreddits:
                continue
            beat = _classify_beat(candidate)
            if beat in excluded_topics:
                continue
            relevance = self._relevance(candidate, beat, brief, preference_tokens)
            headline_zh = self._headline_zh(candidate, beat)
            pitch = StoryPitch(
                kind=StoryKind.BRIEF,
                beat=beat,
                headline_zh=headline_zh,
                angle=f"從 r/{candidate.subreddit} 的一則公開討論切入 {BEAT_LABELS[beat]}。",
                why_for_reader=(
                    f"符合本期 {BEAT_LABELS[beat]} 採訪線，並保留原帖讓讀者自行判斷。"
                ),
                source_refs=[_source_ref(candidate)],
                confidence=Confidence.LOW,
                warnings=[],
            )
            scouted.append(ScoutedPitch(
                pitch=pitch,
                candidate_ids=(candidate.id,),
                relevance=relevance,
            ))
        return sorted(
            scouted,
            key=lambda item: (item.relevance, item.candidate_ids[0]),
            reverse=True,
        )

    @staticmethod
    def _headline_zh(candidate: CandidatePost, beat: str) -> str:
        metadata = candidate.meta_json or {}
        translated = metadata.get("headline_zh") if isinstance(metadata, dict) else None
        if isinstance(translated, str) and translated.strip():
            return translated.strip()[:120]
        return f"{BEAT_LABELS[beat]}｜一則值得留意的公開討論"

    @staticmethod
    def _relevance(
        candidate: CandidatePost,
        beat: str,
        brief: ReaderBrief,
        preference_tokens: set[str],
    ) -> float:
        score = 1.0
        if beat in brief.priority_topics:
            score += 100.0
        searchable = " ".join(filter(None, [candidate.subreddit, candidate.title, candidate.selftext])).lower()
        score += sum(5.0 for token in preference_tokens if len(token) > 1 and token in searchable)
        score += min(float(candidate.initial_num_comments or 0), 50.0) / 100.0
        return score


class AssignmentEditorAgent:
    """Builds the required mixed newspaper shape with source diversity."""

    def create_plan(self, *, reader: ReaderProfile, edition_date: date, scouted: list[ScoutedPitch]) -> EditionPlan:
        by_beat: dict[str, list[ScoutedPitch]] = defaultdict(list)
        for item in scouted:
            by_beat[item.pitch.beat].append(item)
        for pitches in by_beat.values():
            pitches.sort(key=lambda item: item.relevance, reverse=True)

        features, used_candidate_ids = self._select_features(by_beat)
        remaining = [
            item for item in scouted
            if not set(item.candidate_ids).intersection(used_candidate_ids)
        ]
        brief_count = 8 - len(features)
        if len(features) < 1 or brief_count < 6 or len(remaining) < brief_count:
            raise EditorialPlanningError(
                "insufficient diverse candidates for 6–8 briefs and 1–2 features"
            )
        briefs = self._select_diverse_briefs(remaining, count=brief_count)
        if len(briefs) != brief_count:
            raise EditorialPlanningError("not enough source-backed briefs after feature selection")
        return EditionPlan(
            edition_date=edition_date,
            reader_id=reader.id,
            briefs=[item.pitch for item in briefs],
            features=features,
            editor_summary=(
                f"本期以 {len(briefs)} 則短報和 {len(features)} 篇專題組成；"
                f"優先照顧 {', '.join(reader.included_topics or []) or '綜合'} 偏好並避免重複來源。"
            )[:500],
        )

    @staticmethod
    def _select_features(by_beat: dict[str, list[ScoutedPitch]]) -> tuple[list[StoryPitch], set[int]]:
        groups = sorted(
            (
                (beat, pitches)
                for beat, pitches in by_beat.items()
                if len(pitches) >= 2
            ),
            key=lambda group: sum(item.relevance for item in group[1][:2]),
            reverse=True,
        )
        features: list[StoryPitch] = []
        used_candidate_ids: set[int] = set()
        total_candidates = sum(len(pitches) for pitches in by_beat.values())
        for beat, pitches in groups:
            sources = [item for item in pitches if item.candidate_ids[0] not in used_candidate_ids][:2]
            if len(sources) < 2:
                continue
            if total_candidates - len(used_candidate_ids) - 2 < 6:
                continue
            source_refs = [source.pitch.source_refs[0] for source in sources]
            features.append(StoryPitch(
                kind=StoryKind.FEATURE,
                beat=beat,
                headline_zh=f"{BEAT_LABELS[beat]}專題｜昨天 Reddit 的共同訊號",
                angle=(
                    f"比較 {len(source_refs)} 則 r/{source_refs[0].subreddit} 等公開討論，"
                    f"整理 {BEAT_LABELS[beat]} 的共同脈絡。"
                ),
                why_for_reader=f"用多則來源補足單一匿名貼文的侷限，呈現 {BEAT_LABELS[beat]} 的討論面向。",
                source_refs=source_refs,
                confidence=Confidence.LOW,
                warnings=["專題仍以 Reddit 公開討論為來源，非獨立事實查證。"],
            ))
            used_candidate_ids.update(source.candidate_ids[0] for source in sources)
            if len(features) == 2:
                break
        return features, used_candidate_ids

    @staticmethod
    def _select_diverse_briefs(candidates: list[ScoutedPitch], *, count: int) -> list[ScoutedPitch]:
        by_beat: dict[str, list[ScoutedPitch]] = defaultdict(list)
        for candidate in candidates:
            by_beat[candidate.pitch.beat].append(candidate)
        for pitches in by_beat.values():
            pitches.sort(key=lambda item: item.relevance, reverse=True)

        selected: list[ScoutedPitch] = []
        while len(selected) < count:
            available = [
                (beat, pitches[0]) for beat, pitches in by_beat.items() if pitches
            ]
            if not available:
                break
            for beat, _ in sorted(available, key=lambda item: item[1].relevance, reverse=True):
                if len(selected) == count:
                    break
                selected.append(by_beat[beat].pop(0))
        return selected


def plan_edition(session: Session, *, edition: NewsroomEdition) -> PlanningResult:
    """Run N2's three visible planning stages and persist their artifacts."""
    reader = edition.reader
    window = previous_calendar_day_window(edition.edition_date, timezone_name=reader.timezone)

    profile_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.READER_PROFILE.value,
        input_snapshot={"reader_profile_id": reader.id},
    )
    reader_brief = ReaderProfileAgent().build(reader, edition_date=edition.edition_date)
    complete_agent_run(
        session,
        run=profile_run,
        artifact_kind="reader_brief",
        summary=reader_brief.summary,
        payload=reader_brief.model_dump(mode="json"),
    )

    candidates = fetch_window_candidates(session, window)
    scout_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.SCOUT.value,
        input_snapshot={
            "window_start": window.start_utc.isoformat(),
            "window_end": window.end_utc.isoformat(),
            "candidate_count": len(candidates),
        },
    )
    scouted = ScoutAgent().scout(candidates, reader_brief, reader)
    complete_agent_run(
        session,
        run=scout_run,
        artifact_kind="story_pitches",
        summary=f"從 {len(candidates)} 則候選產生 {len(scouted)} 個可追溯選題。",
        payload={"pitches": [item.pitch.model_dump(mode="json") for item in scouted]},
        source_candidate_ids=[candidate_id for item in scouted for candidate_id in item.candidate_ids],
    )
    assignment_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.ASSIGNMENT.value,
        input_snapshot={"pitch_count": len(scouted)},
    )
    try:
        plan = AssignmentEditorAgent().create_plan(
            reader=reader,
            edition_date=edition.edition_date,
            scouted=scouted,
        )
    except EditorialPlanningError as exc:
        fail_agent_run(session, run=assignment_run, error_message=str(exc))
        raise

    source_ids = [
        source_candidate_id
        for pitch in [*plan.briefs, *plan.features]
        for source_candidate_id in _candidate_ids_for_pitch(scouted, pitch)
    ]
    complete_agent_run(
        session,
        run=assignment_run,
        artifact_kind="edition_plan",
        summary=plan.editor_summary,
        payload=plan.model_dump(mode="json"),
        source_candidate_ids=source_ids,
    )
    edition.status = "planned"
    edition.editor_summary = plan.editor_summary
    session.flush()
    return PlanningResult(
        reader_brief=reader_brief,
        plan=plan,
        candidate_count=len(candidates),
    )


def _candidate_ids_for_pitch(scouted: list[ScoutedPitch], pitch: StoryPitch) -> tuple[int, ...]:
    source_post_ids = {source.reddit_post_id for source in pitch.source_refs}
    return tuple(
        candidate_id
        for item in scouted
        for candidate_id, source_ref in zip(item.candidate_ids, item.pitch.source_refs, strict=True)
        if source_ref.reddit_post_id in source_post_ids
    )


__all__ = [
    "AssignmentEditorAgent",
    "CandidateWindow",
    "EditorialPlanningError",
    "PlanningResult",
    "ReaderProfileAgent",
    "ScoutAgent",
    "fetch_window_candidates",
    "plan_edition",
    "previous_calendar_day_window",
]
