"""快照、稿件版本、版面計畫的寫入。P 與 M 用 run_variant 分開，不共用 daily_editions。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import AgentMessage, DailySnapshot, PagePlan, SourceItem, Story, StoryCluster, StoryVersion

PIPELINE = "pipeline"
MAS = "mas"
AGENT_ROLES = frozenset({
    "eic", "section_editor", "reporter", "fact_checker", "copy_editor", "layout_editor", "system",
})


class VersionConflict(RuntimeError):
    """要寫的版本不是目前最新版的下一版（手冊 6.4 第 1 條）。"""


def freeze_candidates(session: Session, scored, disabled_sources: frozenset[str]) -> list[dict]:
    """把評分後的候選凍結成快照 JSON。證據用當時的素材 id，不記 cluster 的當下歸屬以外的東西。"""
    cluster_ids = [cid for item in scored for cid in item.all_ids] or [0]
    reps = dict(
        session.execute(
            select(StoryCluster.id, StoryCluster.representative_item_id).where(StoryCluster.id.in_(cluster_ids))
        ).all()
    )
    rows = session.execute(
        select(SourceItem.cluster_id, SourceItem.id)
        .where(
            SourceItem.cluster_id.in_(cluster_ids),
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
        .order_by(SourceItem.id)
    ).all()
    by_cluster: dict[int, list[int]] = {}
    for cluster_id, item_id in rows:
        by_cluster.setdefault(cluster_id, []).append(item_id)
    payload = []
    for item in scored:
        evidence_ids: list[int] = []
        for cluster_id in item.all_ids:
            evidence_ids.extend(by_cluster.get(cluster_id, []))
        payload.append({
            "keeper_cluster_id": item.cluster_id,
            "merged_cluster_ids": list(item.merged_ids),
            "section": item.section,
            "kind": item.kind,
            "score": item.score,
            "signals": item.signals,
            "anchor_item_id": reps.get(item.cluster_id),
            "evidence_item_ids": evidence_ids,
        })
    return payload


def upsert_snapshot(session: Session, edition_date: date, candidates: list[dict], now: datetime) -> DailySnapshot:
    row = session.scalar(select(DailySnapshot).where(DailySnapshot.edition_date == edition_date))
    if row is None:
        row = DailySnapshot(edition_date=edition_date, created_at=now, candidates=candidates)
        session.add(row)
    else:
        row.candidates = candidates
        row.created_at = now
    session.flush()
    return row


def clear_variant(session: Session, edition_date: date, run_variant: str) -> None:
    ids = list(session.scalars(
        select(Story.id).where(Story.edition_date == edition_date, Story.run_variant == run_variant)
    ).all())
    if ids:
        session.execute(delete(StoryVersion).where(StoryVersion.story_id.in_(ids)))
    session.execute(delete(AgentMessage).where(
        AgentMessage.edition_date == edition_date, AgentMessage.run_variant == run_variant
    ))
    session.execute(delete(PagePlan).where(
        PagePlan.edition_date == edition_date, PagePlan.run_variant == run_variant
    ))
    if ids:
        session.execute(delete(Story).where(Story.id.in_(ids)))
    session.flush()


def add_story(session: Session, *, edition_date: date, run_variant: str, spec: dict) -> Story:
    story = Story(
        edition_date=edition_date,
        run_variant=run_variant,
        keeper_cluster_id=spec["keeper_cluster_id"],
        merged_cluster_ids=list(spec.get("merged_cluster_ids") or []),
        section=spec["section"],
        kind=spec["kind"],
        score=spec.get("score") or 0,
    )
    session.add(story)
    session.flush()
    return story


def latest_version(session: Session, story_id: int) -> StoryVersion | None:
    return session.scalar(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version.desc())
    )


def write_story_version(
    session: Session,
    *,
    story_id: int,
    run_variant: str,
    expected_latest: int,
    headline: str,
    body: str,
    now: datetime,
    deck: str = "",
    why_it_matters: str = "",
    source_ids: list | None = None,
    status: str = "draft",
    caused_by_message_id: int | None = None,
    sender: str = "agent",
) -> StoryVersion:
    """寫下一版。`expected_latest` 必須等於目前最大版號（0 代表還沒有稿）。"""
    current = session.scalar(
        select(func.max(StoryVersion.version)).where(
            StoryVersion.story_id == story_id, StoryVersion.run_variant == run_variant
        )
    ) or 0
    if current != expected_latest:
        raise VersionConflict(f"story {story_id} 最新是 v{current}，不能當成 v{expected_latest} 來寫下一版")
    row = StoryVersion(
        story_id=story_id,
        version=current + 1,
        run_variant=run_variant,
        headline=headline,
        deck=deck,
        body=body,
        why_it_matters=why_it_matters,
        source_ids=list(source_ids or []),
        status=status,
        caused_by_message_id=caused_by_message_id,
        sender=sender,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def set_status(session: Session, story_id: int, status: str) -> StoryVersion | None:
    row = latest_version(session, story_id)
    if row is not None:
        row.status = status
        session.flush()
    return row


def add_page_plan(
    session: Session,
    *,
    edition_date: date,
    run_variant: str,
    slots: dict,
    now: datetime,
    decided_by_message_id: int | None = None,
) -> PagePlan:
    current = session.scalar(
        select(func.max(PagePlan.plan_version)).where(
            PagePlan.edition_date == edition_date, PagePlan.run_variant == run_variant
        )
    ) or 0
    row = PagePlan(
        edition_date=edition_date,
        plan_version=current + 1,
        run_variant=run_variant,
        slots=slots,
        decided_by_message_id=decided_by_message_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def approve_story(session: Session, story_id: int, *, by: str, now: datetime) -> StoryVersion:
    """只有真人可以核准。Agent 角色的名字會被拒絕。"""
    if not by or by in AGENT_ROLES:
        raise PermissionError("只有真人可以核准稿件")
    row = latest_version(session, story_id)
    if row is None:
        raise LookupError(f"story {story_id} 沒有稿")
    row.status = "approved"
    row.approved_by = by
    row.approved_at = now
    session.flush()
    return row


def hold_story(session: Session, story_id: int) -> StoryVersion:
    row = latest_version(session, story_id)
    if row is None:
        raise LookupError(f"story {story_id} 沒有稿")
    row.status = "hold"
    row.approved_by = None
    row.approved_at = None
    session.flush()
    return row
