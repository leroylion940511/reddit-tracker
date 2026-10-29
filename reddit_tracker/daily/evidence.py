"""每則事件的證據包：給撰稿用的成員素材摘要，不含全文。"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import zhconv
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collection.clustering import TIER_RANK, outlet_of
from ..collection.collector import as_utc
from ..models import SourceItem

MAX_EVIDENCE_ITEMS = 6
EVIDENCE_SUMMARY_CHARS = 400
TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass
class EvidenceItem:
    outlet: str
    source_id: str
    source_name: str
    tier: str
    lang: str | None
    title: str
    summary: str
    url: str
    published_at: str

    def as_source(self) -> dict:
        return {
            "outlet": self.source_name,
            "source_id": self.source_id,
            "tier": self.tier,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
        }


def _to_traditional(text: str | None, lang: str | None) -> str:
    return zhconv.convert(text or "", "zh-tw") if lang == "zh" else (text or "")


def build_evidence(
    session: Session,
    cluster_ids: list[int],
    source_names: dict[str, str],
    disabled_sources: frozenset[str] = frozenset(),
) -> list[EvidenceItem]:
    """不同出處優先、層級高優先，同一出處只取最新一篇；可跨多個已合併的事件。已停用來源不進證據包。"""
    members = session.scalars(
        select(SourceItem).where(
            SourceItem.cluster_id.in_(cluster_ids),
            SourceItem.duplicate_of_id.is_(None),
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
    ).all()
    ordered = sorted(members, key=lambda m: (TIER_RANK.get(m.tier, 9), -as_utc(m.published_at).timestamp()))
    chosen: dict[str, SourceItem] = {}
    for member in ordered:
        outlet = outlet_of(member.canonical_url, member.title, member.summary)
        chosen.setdefault(outlet, member)
    picked = list(chosen.items())[:MAX_EVIDENCE_ITEMS]
    # 合併後的中英文事件，中文來源可能被層級與時間排序擠出前 6 篇；至少保留一篇中文。
    if not any((m.lang or "").startswith("zh") for _, m in picked):
        first_zh = next(((o, m) for o, m in chosen.items() if (m.lang or "").startswith("zh")), None)
        if first_zh is not None:
            picked = picked[: MAX_EVIDENCE_ITEMS - 1] + [first_zh]
    evidence = []
    for outlet, member in picked:
        evidence.append(
            EvidenceItem(
                outlet=outlet,
                source_id=member.source_id,
                source_name=source_names.get(member.source_id, member.source_id),
                tier=member.tier,
                lang=member.lang,
                title=_to_traditional(member.title, member.lang),
                summary=_to_traditional(member.summary, member.lang)[:EVIDENCE_SUMMARY_CHARS],
                url=member.url,
                published_at=as_utc(member.published_at).astimezone(TAIPEI).isoformat(timespec="minutes"),
            )
        )
    return evidence
