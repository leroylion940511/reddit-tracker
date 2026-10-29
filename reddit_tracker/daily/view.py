"""`EditionView`：排版只看資料，不看 DailyEdition。來源是最新的 page_plans。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentMessage, DailyEdition, PagePlan, Story, StoryVersion

FULL = "full"
LINK = "link"
BRIEF = "brief"


@dataclass
class ViewArticle:
    story_id: int | None
    section: str
    position: int
    is_front: bool
    front_role: str
    display: str
    kind: str
    headline: str
    deck: str
    body: str
    why_it_matters: str
    sources: list
    writer: str
    status: str
    link_label: str = ""
    withheld: bool = False


@dataclass
class EditionView:
    edition_date: date
    run_variant: str
    articles: list[ViewArticle] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    market: list | None = None
    stats: dict | None = None
    issue_number: int | None = None
    published_at: datetime | None = None
    plan_version: int | None = None


def _front_role(index: int, total: int) -> str:
    if index == 0:
        return "lead"
    if index >= 5:
        return "brief"
    return "second"


def view_from_edition(edition: DailyEdition, sections: dict[str, str]) -> EditionView:
    """測試與回歸集用：還沒有 page_plans 的 DailyEdition，編成跟流水線相同的版面。"""
    articles = list(edition.articles or [])
    front = sorted((a for a in articles if a.is_front), key=lambda a: a.position)
    view_articles = []
    for index, article in enumerate(front):
        role = _front_role(index, len(front))
        view_articles.append(_from_daily(article, is_front=True, front_role=role, display=BRIEF if role == "brief" else FULL))
    for key in sections:
        items = sorted((a for a in articles if a.section == key and not a.is_front), key=lambda a: a.position)
        for article in items:
            view_articles.append(_from_daily(article, is_front=False, front_role="", display=FULL))
    return EditionView(
        edition_date=edition.edition_date,
        run_variant="pipeline",
        articles=view_articles,
        sections=dict(sections),
        market=(edition.stats or {}).get("market"),
        stats=edition.stats,
        published_at=edition.published_at,
    )


def _from_daily(article, *, is_front: bool, front_role: str, display: str) -> ViewArticle:
    return ViewArticle(
        story_id=None,
        section=article.section,
        position=article.position,
        is_front=is_front,
        front_role=front_role,
        display=display,
        kind=article.kind,
        headline=article.headline,
        deck=article.deck or "",
        body="" if display == BRIEF else (article.body or ""),
        why_it_matters="" if display == BRIEF else (article.why_it_matters or ""),
        sources=list(article.sources or []),
        writer=article.writer,
        status="checked",
    )


def _accepted_plan(session: Session, edition_date: date, run_variant: str) -> PagePlan | None:
    plans = session.scalars(
        select(PagePlan)
        .where(PagePlan.edition_date == edition_date, PagePlan.run_variant == run_variant)
        .order_by(PagePlan.plan_version.desc())
    ).all()
    for plan in plans:
        if plan.decided_by_message_id is None:
            return plan
        message = session.get(AgentMessage, plan.decided_by_message_id)
        if message is None or message.status != "rejected":
            return plan
    return None


def build_edition_view(
    session: Session,
    edition_date: date,
    run_variant: str,
    sections: dict[str, str],
    *,
    market: list | None = None,
    stats: dict | None = None,
    issue_number: int | None = None,
    published_at: datetime | None = None,
    for_publish: bool = False,
) -> EditionView:
    """讀最新一份沒被拒絕的 page_plans，每個位置取稿的版本。

    M 組發行時只放已核准的全文；沒核准的位置改成標題短訊。P 組沒有核准關卡，照最新版排。
    """
    plan = _accepted_plan(session, edition_date, run_variant)
    if plan is None:
        raise LookupError(f"{edition_date} {run_variant} 沒有 page_plan")
    slots = plan.slots or {}
    articles: list[ViewArticle] = []
    front = slots.get("front") or {}
    lead = front.get("lead")
    ordered = [lead] if lead else []
    ordered += list(front.get("second") or [])
    brief_ids = set(front.get("briefs") or [])
    ordered += list(front.get("briefs") or [])
    for index, story_id in enumerate(ordered):
        if story_id is None:
            continue
        role = "brief" if story_id in brief_ids else _front_role(index, len(ordered))
        article = _view_story(
            session, story_id, section="front", position=index + 1, is_front=True, front_role=role,
            display=BRIEF if role == "brief" else FULL, run_variant=run_variant, for_publish=for_publish,
        )
        if article is not None:
            articles.append(article)
    for key in sections:
        for position, slot in enumerate(slots.get("sections", {}).get(key) or [], start=1):
            if isinstance(slot, int):
                slot = {"story_id": slot, "display": FULL}
            article = _view_story(
                session, slot["story_id"], section=key, position=position, is_front=False, front_role="",
                display=slot.get("display") or FULL, run_variant=run_variant, for_publish=for_publish,
                link_label=slot.get("label") or "",
            )
            if article is not None:
                articles.append(article)
    return EditionView(
        edition_date=edition_date,
        run_variant=run_variant,
        articles=articles,
        sections=dict(sections),
        market=market,
        stats=stats,
        issue_number=issue_number,
        published_at=published_at,
        plan_version=plan.plan_version,
    )


def _view_story(
    session: Session,
    story_id: int,
    *,
    section: str,
    position: int,
    is_front: bool,
    front_role: str,
    display: str,
    run_variant: str,
    for_publish: bool,
    link_label: str = "",
) -> ViewArticle | None:
    story = session.get(Story, story_id)
    if story is None:
        return None
    version = session.scalar(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version.desc())
    )
    if version is None:
        return None
    withheld = for_publish and run_variant == "mas" and version.status != "approved"
    show = BRIEF if display == BRIEF or withheld else (LINK if display == LINK else FULL)
    sources = _sources_for(session, story, version)
    return ViewArticle(
        story_id=story_id,
        section=story.section if section == "front" else section,
        position=position,
        is_front=is_front,
        front_role=front_role,
        display=show,
        kind=story.kind,
        headline=version.headline,
        deck="" if show != FULL else (version.deck or ""),
        body="" if show != FULL else version.body,
        why_it_matters="" if show != FULL else (version.why_it_matters or ""),
        sources=sources if show == FULL else sources[:1],
        writer="template" if version.sender == "human" else "codex",
        status="withheld" if withheld else version.status,
        link_label=link_label,
        withheld=withheld,
    )


def _sources_for(session: Session, story: Story, version: StoryVersion) -> list[dict]:
    """版本上記的素材 id 對回標題。沒有 id 時留空，渲染仍可出標題。"""
    from ..models import SourceItem

    ids = list(version.source_ids or [])
    if not ids:
        return []
    rows = session.scalars(select(SourceItem).where(SourceItem.id.in_(ids))).all()
    by_id = {row.id: row for row in rows}
    sources = []
    for item_id in ids:
        row = by_id.get(item_id)
        if row is None:
            continue
        sources.append({
            "outlet": row.source_id,
            "source_id": row.source_id,
            "title": row.title or "",
            "url": row.url,
            "published_at": "",
            "summary": row.summary or "",
        })
    return sources
