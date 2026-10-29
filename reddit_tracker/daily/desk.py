"""編輯會議的跨語言合併（手冊步驟 3 第 4 點）：線上用「譯名表＋共同實體」，LLM 只當第二意見。

- 程式合併：中文事件與外文事件，只要某一對成員標題（譯名表統一成中文後）有
  ≥ `cross_lang_min_entities` 個共同實體，就視為同一事件。
- 第二意見：`find_same_events`（LLM）說要合併的組，程式逐對確認共同實體
  ≥ `llm_merge_min_entities`，沒有共同實體的邊剔除（E01：美式足球稿不會再被併進塞爾維亞）。

兩個事件的共同實體＝兩邊成員標題兩兩比對時，共同實體最多的那一對。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collection.clustering import lang_group
from ..collection.entities import EntityContext, EntityLexicon, MergeRules, TitleEntities
from ..models import SourceItem
from .scoring import ScoredCluster


@dataclass
class ClusterTitles:
    cluster_id: int
    lang: str  # 事件的語言群組（成員多數）
    titles: list[str]
    entities: list[TitleEntities]
    names: frozenset[str]  # 所有成員名字的聯集（快速排除不可能的配對）


@dataclass
class DeskMerges:
    """編輯會議的合併結果；`rejected` 是 LLM 說合併但程式找不到共同實體的配對。"""

    groups: list[list[int]] = field(default_factory=list)
    entity_groups: list[list[int]] = field(default_factory=list)
    llm_groups: list[list[int]] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


def load_cluster_titles(
    session: Session,
    cluster_ids: list[int],
    lexicon: EntityLexicon,
    disabled_sources: frozenset[str] = frozenset(),
) -> dict[int, ClusterTitles]:
    rows = session.execute(
        select(SourceItem.cluster_id, SourceItem.title, SourceItem.lang).where(
            SourceItem.cluster_id.in_(cluster_ids),
            SourceItem.duplicate_of_id.is_(None),
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
    ).all()
    grouped: dict[int, list[tuple[str, str]]] = {}
    for cluster_id, title, lang in rows:
        grouped.setdefault(cluster_id, []).append((title or "", lang_group(lang)))
    result = {}
    for cluster_id, members in grouped.items():
        titles = list(dict.fromkeys(title for title, _ in members))
        langs = [lang for _, lang in members]
        lang = max(set(langs), key=lambda g: (langs.count(g), g))
        lang_of = dict(members)
        entities = [lexicon.entities(t, lang_of[t] == "zh") for t in titles]
        names = frozenset().union(*(e.names | e.leads for e in entities))
        result[cluster_id] = ClusterTitles(cluster_id, lang, titles, entities, names)
    return result


def best_shared(
    a: ClusterTitles, b: ClusterTitles, lexicon: EntityLexicon, context: EntityContext
) -> tuple[set[str], str, str]:
    """兩個事件共同實體最多的一對成員標題：（共同實體, a 標題, b 標題）。"""
    best: tuple[set[str], str, str] = (set(), a.titles[0] if a.titles else "", b.titles[0] if b.titles else "")
    for ta, ea in zip(a.titles, a.entities):
        for tb, eb in zip(b.titles, b.entities):
            shared = lexicon.shared(ea, eb, context)
            if len(shared) > len(best[0]):
                best = (shared, ta, tb)
    return best


def _components(edges: list[tuple[int, int]], order: list[int]) -> list[list[int]]:
    parent = {i: i for i in order}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in edges:
        parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in order:
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) >= 2]


def cross_language_groups(
    pool: list[ScoredCluster],
    titles: dict[int, ClusterTitles],
    lexicon: EntityLexicon,
    context: EntityContext,
    min_entities: int,
) -> list[list[int]]:
    """中文事件 × 外文事件，有足夠共同實體就合併（依池內順序，連通的併成一組）。"""
    order = [s.cluster_id for s in pool if s.cluster_id in titles]
    zh = [titles[i] for i in order if titles[i].lang == "zh"]
    other = [titles[i] for i in order if titles[i].lang != "zh"]
    edges = []
    for a in zh:
        for b in other:
            if len(a.names & b.names) < min_entities:
                continue  # 名字聯集都不夠，不可能有一對成員夠
            shared, _, _ = best_shared(a, b, lexicon, context)
            if len(shared) >= min_entities:
                edges.append((a.cluster_id, b.cluster_id))
    return _components(edges, order)


def confirm_groups(
    groups: list[list[int]],
    titles: dict[int, ClusterTitles],
    lexicon: EntityLexicon,
    context: EntityContext,
    min_entities: int,
) -> tuple[list[list[int]], list[dict]]:
    """LLM 回的每一組，只保留有共同實體連起來的部分；被剔除的配對附上理由。"""
    confirmed, rejected = [], []
    for group in groups:
        members = [i for i in dict.fromkeys(group) if i in titles]
        edges = []
        for x, a in enumerate(members):
            for b in members[x + 1 :]:
                shared, ta, tb = best_shared(titles[a], titles[b], lexicon, context)
                if len(shared) >= min_entities:
                    edges.append((a, b))
        kept = _components(edges, members)
        confirmed += kept
        joined = {i for g in kept for i in g}
        for cluster_id in members:
            if cluster_id in joined:
                continue
            partner = next(i for i in members if i != cluster_id)
            _, ta, tb = best_shared(titles[cluster_id], titles[partner], lexicon, context)
            rejected.append(
                {
                    "group": members,
                    "cluster_id": cluster_id,
                    "title": ta,
                    "reason": f"無共同實體（對照 {partner}：{tb}）",
                }
            )
    return confirmed, rejected


def desk_merges(
    session: Session,
    pool: list[ScoredCluster],
    llm_groups: list[list[int]] | None,
    *,
    lexicon: EntityLexicon,
    rules: MergeRules,
    disabled_sources: frozenset[str] = frozenset(),
    context_cluster_ids: list[int] | None = None,
) -> DeskMerges:
    """程式跨語言合併＋確認過的 LLM 第二意見。`context_cluster_ids`：算片段少見度的「當天素材」範圍。"""
    pool_ids = [s.cluster_id for s in pool]
    llm_ids = [i for g in llm_groups or [] for i in g]
    wanted = list(dict.fromkeys([*pool_ids, *llm_ids, *(context_cluster_ids or [])]))
    titles = load_cluster_titles(session, wanted, lexicon, disabled_sources)
    context = EntityContext(e for t in titles.values() for e in t.entities)
    result = DeskMerges(llm_groups=[list(g) for g in llm_groups or []])
    result.entity_groups = cross_language_groups(
        pool, titles, lexicon, context, rules.cross_lang_min_entities
    )
    confirmed, result.rejected = confirm_groups(
        result.llm_groups, titles, lexicon, context, rules.llm_merge_min_entities
    )
    result.groups = result.entity_groups + confirmed
    return result
