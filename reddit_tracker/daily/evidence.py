"""每則事件的證據包：給撰稿用的成員素材摘要，不含全文。

規則（手冊步驟 3 第 5、6 點）：
- 轉載只算一個來源（`mark_reprints`）：同一組轉載只放原稿一列，前台顯示「中央社（央廣轉載）」。
- 相關性過濾：每一篇都要和事件代表標題有共同實體（先用譯名表統一成中文，見
  `collection/entities.py`），沒有就剔除，並把「剔除：出處｜標題…，原因：無共同實體」寫進
  `review_notes`（E01、E05）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import zhconv
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collection.clustering import CNA_DOMAIN, TIER_RANK, WINDOW, domain_of, lang_group, mark_reprints, outlet_of
from ..collection.collector import as_utc
from ..collection.entities import EntityContext, EntityLexicon, load_lexicon
from ..models import SourceItem, StoryCluster

MAX_EVIDENCE_ITEMS = 6
EVIDENCE_SUMMARY_CHARS = 400
REJECTED_TITLE_CHARS = 24
TAIPEI = ZoneInfo("Asia/Taipei")
CNA_NAME = "中央社"


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
    # 轉載這篇的其他來源名稱（已併成這一列，不另算一家）
    reprinted_by: list[str] = field(default_factory=list)
    # source_items.id；快照凍結用。舊的呼叫端可以不填。
    item_id: int | None = None

    @property
    def display_name(self) -> str:
        """來源列顯示的名稱；轉載併成一列，例如「中央社（中央廣播電台轉載）」。"""
        if not self.reprinted_by:
            return self.source_name
        return f"{short_outlet(self.source_name)}（{'、'.join(map(short_outlet, self.reprinted_by))}轉載）"

    def as_source(self) -> dict:
        source = {
            "outlet": self.display_name,
            "source_id": self.source_id,
            "tier": self.tier,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
        }
        if self.reprinted_by:
            source["reprinted_by"] = list(self.reprinted_by)
        return source


@dataclass
class EvidencePack:
    items: list[EvidenceItem]
    # 寫進稿件 review_notes 的紀錄（例如相關性過濾剔除的來源）
    notes: list[str] = field(default_factory=list)


def short_outlet(name: str) -> str:
    """「中央社 政治」→「中央社」；英文名稱（BBC World）保留全名。"""
    head = name.split(" ")[0]
    return head if re.search(r"[一-鿿]", head) else name


def _to_traditional(text: str | None, lang: str | None) -> str:
    return zhconv.convert(text or "", "zh-tw") if lang == "zh" else (text or "")


def title_context(
    session: Session,
    now: datetime,
    lexicon: EntityLexicon,
    disabled_sources: frozenset[str] = frozenset(),
) -> EntityContext:
    """「當天素材」＝聚合時間窗內的素材標題（與聚合判斷共同實體用同一個定義）。"""
    rows = session.execute(
        select(SourceItem.title, SourceItem.lang).where(
            SourceItem.duplicate_of_id.is_(None),
            SourceItem.published_at >= now - WINDOW,
            SourceItem.published_at <= now + timedelta(hours=1),
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
    ).all()
    return EntityContext(lexicon.entities(title or "", lang_group(lang) == "zh") for title, lang in rows)


def _entities(lexicon: EntityLexicon, item: SourceItem):
    return lexicon.entities(item.title or "", lang_group(item.lang) == "zh")


def _display_source(member: SourceItem, source_names: dict[str, str]) -> tuple[str, list[str]]:
    """（來源名稱, 轉載者）；帶中央社電頭、但不是中央社網域的稿，顯示成「中央社（某某轉載）」。"""
    name = source_names.get(member.source_id, member.source_id)
    if outlet_of(member.canonical_url, member.title, member.summary) == CNA_DOMAIN and domain_of(
        member.canonical_url
    ) != CNA_DOMAIN:
        return CNA_NAME, [name]
    return name, []


def _assemble_evidence(
    members: list[SourceItem],
    source_names: dict[str, str],
    *,
    anchor: SourceItem | None,
    lexicon: EntityLexicon,
    context: EntityContext | None,
    notes: list[str] | None = None,
) -> EvidencePack:
    """同一批素材組證據包。`anchor` 是相關性過濾的代表稿；沒給就用排序後的第一篇。"""
    notes = list(notes or [])
    if not members:
        return EvidencePack([], notes)
    if context is None:
        context = EntityContext(_entities(lexicon, m) for m in members if m.duplicate_of_id is None)
    reprints = mark_reprints(members)
    by_id = {m.id: m for m in members}
    reprinted_by: dict[int, list[SourceItem]] = {}
    for copy_id, original_id in reprints.items():
        if original_id in by_id and copy_id in by_id:
            reprinted_by.setdefault(original_id, []).append(by_id[copy_id])
    originals = [m for m in members if m.id not in reprints]
    if not originals:
        return EvidencePack([], notes)
    if anchor is not None:
        anchor = by_id.get(reprints.get(anchor.id, anchor.id), anchor if anchor.id in by_id else None)
    ordered = sorted(originals, key=lambda m: (TIER_RANK.get(m.tier, 9), -as_utc(m.published_at).timestamp()))
    anchor = anchor or ordered[0]
    anchor_entities = _entities(lexicon, anchor)
    can_filter = bool(context.names(anchor_entities) or anchor_entities.trigrams)
    if not can_filter and len(ordered) > 1:
        notes.append(f"未做相關性過濾：代表標題抽不到實體（{(anchor.title or '')[:REJECTED_TITLE_CHARS]}）")

    chosen: dict[str, SourceItem] = {}
    for member in ordered:
        if (
            can_filter
            and member is not anchor
            and not lexicon.shared(_entities(lexicon, member), anchor_entities, context)
        ):
            name = source_names.get(member.source_id, member.source_id)
            title = member.title or ""
            short = title[:REJECTED_TITLE_CHARS] + ("…" if len(title) > REJECTED_TITLE_CHARS else "")
            notes.append(f"剔除：{name}｜{short}，原因：無共同實體")
            continue
        outlet = outlet_of(member.canonical_url, member.title, member.summary)
        chosen.setdefault(outlet, member)
    picked = list(chosen.items())[:MAX_EVIDENCE_ITEMS]
    if not any((m.lang or "").startswith("zh") for _, m in picked):
        first_zh = next(((o, m) for o, m in chosen.items() if (m.lang or "").startswith("zh")), None)
        if first_zh is not None:
            picked = picked[: MAX_EVIDENCE_ITEMS - 1] + [first_zh]
    evidence = []
    for outlet, member in picked:
        name, carriers = _display_source(member, source_names)
        for copy in sorted(reprinted_by.get(member.id, []), key=lambda m: (as_utc(m.published_at), m.id)):
            if domain_of(copy.canonical_url) == domain_of(member.canonical_url):
                continue
            carrier = source_names.get(copy.source_id, copy.source_id)
            if carrier not in carriers:
                carriers.append(carrier)
        evidence.append(
            EvidenceItem(
                outlet=outlet,
                source_id=member.source_id,
                source_name=name,
                tier=member.tier,
                lang=member.lang,
                title=_to_traditional(member.title, member.lang),
                summary=_to_traditional(member.summary, member.lang)[:EVIDENCE_SUMMARY_CHARS],
                url=member.url,
                published_at=as_utc(member.published_at).astimezone(TAIPEI).isoformat(timespec="minutes"),
                reprinted_by=carriers,
                item_id=member.id,
            )
        )
    return EvidencePack(evidence, notes)


def build_evidence(
    session: Session,
    cluster_ids: list[int],
    source_names: dict[str, str],
    disabled_sources: frozenset[str] = frozenset(),
    *,
    lexicon: EntityLexicon | None = None,
    context: EntityContext | None = None,
) -> EvidencePack:
    """不同出處優先、層級高優先，同一出處只取最新一篇；可跨多個已合併的事件。已停用來源不進證據包。

    `cluster_ids[0]` 是主事件，它的代表標題是相關性過濾的錨點。`context`：判斷中文片段是否
    少見的「當天素材」（`title_context`）；沒給就只用這幾個事件的素材，片段容易被當成常見。
    """
    lexicon = lexicon or load_lexicon()
    members = list(session.scalars(
        select(SourceItem).where(
            SourceItem.cluster_id.in_(cluster_ids),
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
    ).all())
    if not members:
        return EvidencePack([])
    primary = session.get(StoryCluster, cluster_ids[0])
    by_id = {m.id: m for m in members}
    anchor = by_id.get(primary.representative_item_id) if primary is not None and primary.representative_item_id else None
    return _assemble_evidence(members, source_names, anchor=anchor, lexicon=lexicon, context=context)


def build_evidence_from_ids(
    session: Session,
    item_ids: list[int],
    source_names: dict[str, str],
    *,
    anchor_item_id: int | None = None,
    lexicon: EntityLexicon | None = None,
    context: EntityContext | None = None,
    allowed_domains: frozenset[str] | None = None,
) -> EvidencePack:
    """用快照凍結的素材 id 組證據包，不看現在的 `source_items.cluster_id`。

    `allowed_domains` 有給時，網域不在登錄表的素材不進證據包（手冊 10.2 假來源）。
    流水線的 `build_evidence` 不套這道，避免改到既有回歸行為。
    """
    lexicon = lexicon or load_lexicon()
    if not item_ids:
        return EvidencePack([])
    members = list(session.scalars(select(SourceItem).where(SourceItem.id.in_(list(item_ids)))).all())
    notes: list[str] = []
    if allowed_domains is not None:
        kept = []
        for member in members:
            domain = domain_of(member.canonical_url)
            outlet = outlet_of(member.canonical_url, member.title, member.summary)
            if domain not in allowed_domains and outlet not in allowed_domains:
                title = member.title or ""
                short = title[:REJECTED_TITLE_CHARS] + ("…" if len(title) > REJECTED_TITLE_CHARS else "")
                name = source_names.get(member.source_id, member.source_id)
                notes.append(f"剔除：{name}｜{short}，原因：不在登錄表網域")
                continue
            kept.append(member)
        members = kept
    by_id = {m.id: m for m in members}
    anchor = by_id.get(anchor_item_id) if anchor_item_id else None
    return _assemble_evidence(members, source_names, anchor=anchor, lexicon=lexicon, context=context, notes=notes)
