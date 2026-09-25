"""N3 evidence, safety, and Chinese drafting stages for a newsroom edition.

`TemplateDraftingAgent` is a deterministic demo-safe writer. The data contract
lets a future Gemini adapter replace only the prose generation, while evidence,
sources, warnings, and the editor ledger stay stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CandidatePost,
    EditionItem,
    EditionItemSource,
    NewsroomEdition,
)
from .contracts import (
    AgentStage,
    Confidence,
    EditionPlan,
    EvidenceBrief,
    EvidenceClaim,
    EvidenceKind,
    StoryDraft,
    StoryKind,
    StoryPitch,
)
from .repository import complete_agent_run, fail_agent_run, start_agent_run


class NewsroomWritingError(ValueError):
    """Raised when a plan cannot safely become a source-backed edition."""


class DraftingAgent(Protocol):
    """A bounded prose writer. Evidence and source references stay in our code."""

    name: str

    def draft_many(
        self, pairs: list[tuple[StoryPitch, EvidenceBrief]]
    ) -> list[StoryDraft]: ...


@dataclass(frozen=True)
class DraftingResult:
    evidence_briefs: list[EvidenceBrief]
    drafts: list[StoryDraft]
    items: list[EditionItem]


SENSITIVE_TERMS: dict[str, tuple[str, ...]] = {
    "自傷／心理困擾": ("suicide", "self harm", "self-harm", "自殺", "自傷"),
    "暴力內容": ("murder", "assault", "violence", "謀殺", "暴力", "攻擊"),
    "成人或性相關內容": ("sexual", "sex", "nsfw", "色情", "性侵"),
}

FALLBACK_BEAT_LABELS = {
    "relationships": "人際與情感",
    "daily_life": "職場與日常",
    "internet_culture": "網路現象",
    "taiwan_life": "台灣與華語生活",
    "human_interest": "人物故事",
}


def _compact(text: str | None, *, limit: int) -> str:
    compacted = re.sub(r"\s+", " ", text or "").strip()
    if not compacted:
        return "原帖未提供更多正文內容。"
    return compacted[:limit].rstrip("，。；： ")


def _candidate_ids_for_pitch(candidates_by_reddit_id: dict[str, CandidatePost], pitch: StoryPitch) -> list[int]:
    ids: list[int] = []
    for source in pitch.source_refs:
        candidate = candidates_by_reddit_id.get(source.reddit_post_id)
        if candidate is None:
            raise NewsroomWritingError(
                f"pitch source is absent from candidate cache: {source.reddit_post_id}"
            )
        ids.append(candidate.id)
    return ids


class ContentSafetyGate:
    """Small, deterministic labeler; it flags but does not silently drop stories."""

    def warnings_for(self, candidates: list[CandidatePost]) -> list[str]:
        text = " ".join(filter(None, [
            candidate.title for candidate in candidates
        ] + [candidate.selftext for candidate in candidates])).lower()
        return [
            label for label, terms in SENSITIVE_TERMS.items()
            if any(term in text for term in terms)
        ]


class EvidenceAgent:
    """Separates author statements from editorial context and uncertainty."""

    def build(self, pitch: StoryPitch, candidates: list[CandidatePost]) -> EvidenceBrief:
        claims = [
            EvidenceClaim(
                kind=EvidenceKind.AUTHOR_STATEMENT,
                statement_zh=(
                    f"原作者在 r/{candidate.subreddit} 發表〈{candidate.title}〉，"
                    f"並描述：{_compact(candidate.selftext, limit=260)}"
                ),
                source_post_ids=[candidate.reddit_post_id],
            )
            for candidate in candidates
        ]
        return EvidenceBrief(
            headline_zh=pitch.headline_zh,
            claims=claims,
            uncertainty_notes=[
                "本文素材來自公開 Reddit 討論；原作者說法未經本系統獨立查證。",
                "留言反應與外部事實須在後續查核取得來源前分開處理。",
            ],
            content_warnings=ContentSafetyGate().warnings_for(candidates),
            confidence=Confidence.LOW,
        )


class TemplateDraftingAgent:
    """Compose transparent Chinese demo drafts without an external LLM call."""

    name = "template"

    def draft(self, pitch: StoryPitch, evidence: EvidenceBrief) -> StoryDraft:
        source_names = "、".join(f"r/{source.subreddit}" for source in pitch.source_refs)
        original_titles = "；".join(source.original_title for source in pitch.source_refs)
        beat_label = FALLBACK_BEAT_LABELS.get(pitch.beat, "日常生活")
        if pitch.kind is StoryKind.FEATURE:
            deck = f"從 {len(pitch.source_refs)} 則公開討論整理出的觀察，不把匿名經驗當成定論。"
            body = (
                f"這篇專題從 {source_names} 的公開討論切入，觀察 {beat_label} 的不同提問與經驗。\n\n"
                f"原帖標題：{original_titles}\n\n"
                "這些貼文呈現的是匿名使用者各自的處境，而非可推論到所有人的結論。"
                "完整自述與脈絡請直接閱讀原帖；本文不將其延伸為已證實的外部事實。"
            )
        elif pitch.kind is StoryKind.BREAKING:
            deck = "同日早晨出現明確互動訊號的公開討論；先看來源，再決定是否追讀。"
            body = (
                f"這則早報快訊來自 {source_names}，在清晨已出現較高互動。\n\n"
                f"原帖標題：{original_titles}\n\n"
                "互動數字只能反映當時的 Reddit 討論熱度，不代表內容已獲外部證實。"
                "完整脈絡請直接閱讀原帖。"
            )
        else:
            deck = "一則值得聊的公開討論，保留來源與不確定性讓讀者自行判斷。"
            body = (
                f"這則公開討論來自 {source_names}，聚焦在 {beat_label} 的一個日常提問或經驗。\n\n"
                f"原帖標題：{original_titles}\n\n"
                "目前可確認的是原作者在 Reddit 提出的匿名自述。完整內容請見原帖；"
                "本文不把它延伸為已證實的外部事實，也不替讀者作出單一結論。"
            )
        return StoryDraft(
            kind=pitch.kind,
            headline_zh=pitch.headline_zh,
            deck_zh=deck,
            body_zh=body,
            why_it_matters_zh=pitch.why_for_reader,
            source_refs=pitch.source_refs,
            confidence=evidence.confidence,
            content_warnings=evidence.content_warnings,
        )

    def draft_many(
        self, pairs: list[tuple[StoryPitch, EvidenceBrief]]
    ) -> list[StoryDraft]:
        return [self.draft(pitch, evidence) for pitch, evidence in pairs]


def draft_edition(
    session: Session,
    *,
    edition: NewsroomEdition,
    plan: EditionPlan,
    drafting_agent: DraftingAgent | None = None,
) -> DraftingResult:
    """Persist N3 verification, writing, and chief-editing artifacts for a plan."""
    existing_item_id = session.scalar(
        select(EditionItem.id).where(EditionItem.edition_id == edition.id).limit(1)
    )
    if existing_item_id is not None:
        raise NewsroomWritingError("edition already has drafted items")
    pitches = [*plan.briefs, *plan.features, *([plan.breaking] if plan.breaking else [])]
    reddit_ids = [source.reddit_post_id for pitch in pitches for source in pitch.source_refs]
    candidates = list(session.scalars(
        select(CandidatePost).where(CandidatePost.reddit_post_id.in_(reddit_ids))
    ).all())
    candidates_by_reddit_id = {candidate.reddit_post_id: candidate for candidate in candidates}

    verification_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.VERIFICATION.value,
        input_snapshot={"pitch_count": len(pitches)},
    )
    evidence_agent = EvidenceAgent()
    try:
        evidence_pairs = [
            (
                pitch,
                evidence_agent.build(
                    pitch,
                    [
                        candidates_by_reddit_id[source.reddit_post_id]
                        for source in pitch.source_refs
                    ],
                ),
            )
            for pitch in pitches
        ]
    except KeyError as exc:
        fail_agent_run(session, run=verification_run, error_message=f"missing source: {exc}")
        raise NewsroomWritingError(f"missing source while building evidence: {exc}") from exc
    source_candidate_ids = [
        candidate_id
        for pitch in pitches
        for candidate_id in _candidate_ids_for_pitch(candidates_by_reddit_id, pitch)
    ]
    complete_agent_run(
        session,
        run=verification_run,
        artifact_kind="evidence_briefs",
        summary=f"完成 {len(evidence_pairs)} 則來源標註與不確定性說明。",
        payload={"evidence": [brief.model_dump(mode="json") for _, brief in evidence_pairs]},
        source_candidate_ids=source_candidate_ids,
    )

    writer = drafting_agent or TemplateDraftingAgent()
    writing_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.WRITING.value,
        input_snapshot={"evidence_count": len(evidence_pairs), "writer": writer.name},
    )
    try:
        drafts = writer.draft_many(evidence_pairs)
    except Exception as exc:
        fail_agent_run(session, run=writing_run, error_message=str(exc))
        raise NewsroomWritingError(f"writer {writer.name} failed: {exc}") from exc
    if len(drafts) != len(evidence_pairs):
        fail_agent_run(
            session,
            run=writing_run,
            error_message=f"writer returned {len(drafts)} drafts for {len(evidence_pairs)} pitches",
        )
        raise NewsroomWritingError("writer returned an incomplete edition")
    for draft, (pitch, _) in zip(drafts, evidence_pairs, strict=True):
        if draft.kind is not pitch.kind or draft.source_refs != pitch.source_refs:
            fail_agent_run(session, run=writing_run, error_message="writer changed bounded source contract")
            raise NewsroomWritingError("writer changed bounded source contract")
    items: list[EditionItem] = []
    for position, (pitch, draft) in enumerate(zip(pitches, drafts, strict=True), start=1):
        item = EditionItem(
            edition_id=edition.id,
            kind=draft.kind.value,
            position=position,
            status="drafted",
            headline_zh=draft.headline_zh,
            body_zh=draft.body_zh,
            why_it_matters=draft.why_it_matters_zh,
            confidence=draft.confidence.value,
            warnings=draft.content_warnings,
        )
        session.add(item)
        session.flush()
        for source_order, candidate_id in enumerate(
            _candidate_ids_for_pitch(candidates_by_reddit_id, pitch), start=1
        ):
            session.add(EditionItemSource(
                edition_item_id=item.id,
                candidate_post_id=candidate_id,
                source_order=source_order,
                source_role="primary" if source_order == 1 else "supporting",
            ))
        items.append(item)
    session.flush()
    complete_agent_run(
        session,
        run=writing_run,
        artifact_kind="story_drafts",
        summary=(
            f"完成 {len(drafts)} 則繁中示範稿；所有稿件保留原帖來源與資訊邊界。"
            + (
                f"第 {', '.join(map(str, writer.fallback_positions))} 則缺少模型欄位，"
                "已以來源透明模板補齊。"
                if getattr(writer, "fallback_positions", ())
                else ""
            )
        ),
        payload={
            "drafts": [draft.model_dump(mode="json") for draft in drafts],
            "template_fallback_positions": list(getattr(writer, "fallback_positions", ())),
        },
        source_candidate_ids=source_candidate_ids,
    )

    chief_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.CHIEF_EDITING.value,
        input_snapshot={"draft_count": len(drafts)},
    )
    edition.status = "drafted"
    complete_agent_run(
        session,
        run=chief_run,
        artifact_kind="edition_draft",
        summary=f"本期已完成 {len(items)} 則草稿，等待發行或 preview。",
        payload={"edition_item_ids": [item.id for item in items], "status": edition.status},
        source_candidate_ids=source_candidate_ids,
    )
    session.flush()
    return DraftingResult(
        evidence_briefs=[brief for _, brief in evidence_pairs],
        drafts=drafts,
        items=items,
    )


def refresh_draft_edition(
    session: Session,
    *,
    edition: NewsroomEdition,
    plan: EditionPlan,
    drafting_agent: DraftingAgent,
) -> DraftingResult:
    """Replace only prose of an unpublished edition after a writer recovery.

    Existing item/source bridges are retained. The retry is explicit in the
    ledger; it is useful when a temporary provider error produced a safe
    fallback preview before the scheduled delivery.
    """
    if edition.status == "published":
        raise NewsroomWritingError("published editions cannot be rewritten")
    pitches = [*plan.briefs, *plan.features, *([plan.breaking] if plan.breaking else [])]
    items = list(session.scalars(
        select(EditionItem)
        .where(EditionItem.edition_id == edition.id)
        .order_by(EditionItem.position.asc())
    ).all())
    if len(items) != len(pitches):
        raise NewsroomWritingError("edition items do not match the saved plan")
    reddit_ids = [source.reddit_post_id for pitch in pitches for source in pitch.source_refs]
    candidates = list(session.scalars(
        select(CandidatePost).where(CandidatePost.reddit_post_id.in_(reddit_ids))
    ).all())
    candidates_by_reddit_id = {candidate.reddit_post_id: candidate for candidate in candidates}
    try:
        evidence_pairs = [
            (pitch, EvidenceAgent().build(
                pitch,
                [candidates_by_reddit_id[source.reddit_post_id] for source in pitch.source_refs],
            ))
            for pitch in pitches
        ]
    except KeyError as exc:
        raise NewsroomWritingError(f"missing source while refreshing draft: {exc}") from exc
    source_candidate_ids = [
        candidate_id
        for pitch in pitches
        for candidate_id in _candidate_ids_for_pitch(candidates_by_reddit_id, pitch)
    ]
    writing_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.WRITING.value,
        input_snapshot={"evidence_count": len(evidence_pairs), "writer": drafting_agent.name, "mode": "refresh"},
    )
    try:
        drafts = drafting_agent.draft_many(evidence_pairs)
    except Exception as exc:
        fail_agent_run(session, run=writing_run, error_message=str(exc))
        raise NewsroomWritingError(f"writer {drafting_agent.name} failed: {exc}") from exc
    if len(drafts) != len(items):
        fail_agent_run(session, run=writing_run, error_message="writer returned an incomplete refresh")
        raise NewsroomWritingError("writer returned an incomplete refresh")
    for item, draft, (pitch, _) in zip(items, drafts, evidence_pairs, strict=True):
        if draft.kind is not pitch.kind or draft.source_refs != pitch.source_refs:
            fail_agent_run(session, run=writing_run, error_message="writer changed bounded source contract")
            raise NewsroomWritingError("writer changed bounded source contract")
        item.kind = draft.kind.value
        item.status = "drafted"
        item.headline_zh = draft.headline_zh
        item.body_zh = draft.body_zh
        item.why_it_matters = draft.why_it_matters_zh
        item.confidence = draft.confidence.value
        item.warnings = draft.content_warnings
    complete_agent_run(
        session,
        run=writing_run,
        artifact_kind="story_drafts",
        summary=f"以 {drafting_agent.name} 完成 {len(drafts)} 則稿件重寫；來源 bridge 未變更。",
        payload={"drafts": [draft.model_dump(mode="json") for draft in drafts], "mode": "refresh"},
        source_candidate_ids=source_candidate_ids,
    )
    chief_run = start_agent_run(
        session,
        edition=edition,
        stage=AgentStage.CHIEF_EDITING.value,
        input_snapshot={"draft_count": len(drafts), "mode": "refresh"},
    )
    edition.status = "drafted"
    complete_agent_run(
        session,
        run=chief_run,
        artifact_kind="edition_draft",
        summary=f"重寫版已完成 {len(items)} 則草稿，等待發行。",
        payload={"edition_item_ids": [item.id for item in items], "status": edition.status, "mode": "refresh"},
        source_candidate_ids=source_candidate_ids,
    )
    session.flush()
    return DraftingResult(evidence_briefs=[brief for _, brief in evidence_pairs], drafts=drafts, items=items)


__all__ = [
    "ContentSafetyGate",
    "DraftingResult",
    "EvidenceAgent",
    "DraftingAgent",
    "NewsroomWritingError",
    "refresh_draft_edition",
    "TemplateDraftingAgent",
    "draft_edition",
]
