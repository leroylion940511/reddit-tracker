"""併版（手冊步驟 4）：十版縮成台灣、國際、科技三個內版，其他版只出頭版標題短訊。

在 `score_candidates` 之後、編輯會議之前呼叫 `rewrite_sections`，把兩岸、財經，以及生活版
的教育／社會類事件改寫到三個內版（只改配額不改分版的話，兩岸、財經稿會整篇消失）。
規則全部由程式判斷，詞表在 `seeds/section_rules.yaml`：

- `cross_strait` → `taiwan`（與台灣直接相關：標題有台灣詞，或有台灣官方 T1 來源）；否則 `world`。
- `finance` → 依序：台灣詞或台灣官方來源 → `taiwan`；科技詞或有科技版來源 → `tech`；
  素材全是繁體中文（台灣媒體）且沒有國際詞 → `taiwan`；其餘 → `world`。
- `life_env`（`society_sections`）的教育、社會類（E14）：社會詞＋（台灣詞、台灣官方來源或全是繁中）→ `taiwan`。
- 其他版（科學、生活、文化、體育）不改，只由 `select_briefs` 挑去頭版當標題短訊，不呼叫 LLM。

改過的事件在 `signals` 記 `original_section` 與 `section_rule`（命中的規則與詞）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
import zhconv
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collection.normalize import strip_title_labels
from ..models import SourceItem
from ..seeds.news_sources import SourceRegistry
from .evidence import EvidenceItem, short_outlet
from .scoring import SECTION_QUOTAS, ScoredCluster, Selection
from .writer import story_label

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "seeds" / "section_rules.yaml"
INNER_SECTIONS = tuple(SECTION_QUOTAS)  # taiwan, world, tech
REWRITE_SECTIONS = ("cross_strait", "finance")
# 只出頭版標題短訊的版（社群版的來源已全部停用）
BRIEF_SECTIONS = ("science_health", "life_env", "culture", "sports")
BRIEFS_PER_SECTION = 2
BRIEF_KINDS = ("report", "single_source")
TRADITIONAL_LANG = "zh-Hant"


@dataclass(frozen=True)
class Terms:
    zh: tuple[str, ...]
    en: re.Pattern | None

    @classmethod
    def build(cls, raw: dict | None) -> Terms:
        raw = raw or {}
        en = [str(t) for t in raw.get("en", [])]
        pattern = None
        if en:
            alternatives = "|".join(re.escape(t) for t in sorted(en, key=len, reverse=True))
            pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{alternatives})(?![A-Za-z0-9])", re.IGNORECASE)
        return cls(tuple(str(t) for t in raw.get("zh", [])), pattern)

    def hits(self, texts: list[str]) -> list[str]:
        found = []
        for text in texts:
            found += [t for t in self.zh if t in text]
            if self.en is not None:
                found += [m.group(0) for m in self.en.finditer(text)]
        return list(dict.fromkeys(found))


@dataclass(frozen=True)
class SectionRules:
    taiwan: Terms
    tech: Terms
    world_finance: Terms
    society: Terms
    tech_source_sections: frozenset[str]
    society_sections: frozenset[str]


@lru_cache(maxsize=4)
def load_section_rules(path: str | Path = DEFAULT_RULES_PATH) -> SectionRules:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return SectionRules(
        taiwan=Terms.build(data.get("taiwan_terms")),
        tech=Terms.build(data.get("tech_terms")),
        world_finance=Terms.build(data.get("world_finance_terms")),
        society=Terms.build(data.get("society_terms")),
        tech_source_sections=frozenset(data.get("tech_source_sections", [])),
        society_sections=frozenset(data.get("society_sections", [])),
    )


@dataclass(frozen=True)
class Members:
    """一個事件判斷分版要看的東西（已停用來源的素材不算）。"""

    titles: list[str]
    langs: frozenset[str]
    source_sections: frozenset[str]  # 素材來源在登錄表上的板塊
    taiwan_official: bool  # 有台灣官方 T1 來源（登錄表 taiwan 版的 T1）


def classify(section: str, members: Members, rules: SectionRules) -> tuple[str, str | None]:
    """回傳（新板塊, 規則說明）；不改就回傳原板塊與 None。"""
    taiwan_hits = rules.taiwan.hits(members.titles)
    taiwan = bool(taiwan_hits) or members.taiwan_official
    taiwan_why = f"台灣詞 {'、'.join(taiwan_hits[:3])}" if taiwan_hits else "台灣官方來源"
    domestic = bool(members.langs) and members.langs <= {TRADITIONAL_LANG}
    if section == "cross_strait":
        return ("taiwan", f"兩岸→台灣：{taiwan_why}") if taiwan else ("world", "兩岸→國際：與台灣無直接關係")
    if section == "finance":
        if taiwan:
            return "taiwan", f"財經→台灣：{taiwan_why}"
        tech_hits = rules.tech.hits(members.titles)
        if tech_hits:
            return "tech", f"財經→科技：科技詞 {'、'.join(tech_hits[:3])}"
        if members.source_sections & rules.tech_source_sections:
            return "tech", "財經→科技：有科技版來源"
        world_hits = rules.world_finance.hits(members.titles)
        if domestic and not world_hits:
            return "taiwan", "財經→台灣：台灣媒體的中文財經稿、沒有國際詞"
        return "world", f"財經→國際：{'國際詞 ' + '、'.join(world_hits[:3]) if world_hits else '外文來源'}"
    if section in rules.society_sections:
        society_hits = rules.society.hits(members.titles)
        if society_hits and (taiwan or domestic):
            return "taiwan", f"教育／社會→台灣：{'、'.join(society_hits[:3])}"
    return section, None


def _members(
    session: Session, cluster_ids: list[int], registry: SourceRegistry, disabled_sources: frozenset[str]
) -> dict[int, Members]:
    by_id = {s.id: s for s in registry.sources}
    raw: dict[int, dict] = {}
    rows = session.execute(
        select(SourceItem.cluster_id, SourceItem.source_id, SourceItem.title, SourceItem.lang, SourceItem.tier).where(
            SourceItem.cluster_id.in_(cluster_ids)
        )
    )
    for cluster_id, source_id, title, lang, tier in rows:
        if source_id in disabled_sources:
            continue
        entry = raw.setdefault(cluster_id, {"titles": [], "langs": set(), "sections": set(), "official": False})
        entry["titles"].append(zhconv.convert(strip_title_labels(title), "zh-tw"))
        entry["langs"].add(lang or "")
        source = by_id.get(source_id)
        if source is not None:
            entry["sections"].add(source.section)
            entry["official"] |= tier == "T1" and source.section == "taiwan"
    return {
        cid: Members(e["titles"], frozenset(e["langs"]), frozenset(e["sections"]), e["official"])
        for cid, e in raw.items()
    }


def rewrite_sections(
    session: Session,
    scored: list[ScoredCluster],
    *,
    registry: SourceRegistry,
    rules: SectionRules | None = None,
) -> list[ScoredCluster]:
    """就地改寫 `scored` 的板塊並回傳同一個 list。"""
    rules = rules or load_section_rules()
    targets = [s for s in scored if s.section in REWRITE_SECTIONS or s.section in rules.society_sections]
    if not targets:
        return scored
    members = _members(session, [s.cluster_id for s in targets], registry, registry.disabled_source_ids())
    for s in targets:
        info = members.get(s.cluster_id)
        if info is None:
            continue
        section, why = classify(s.section, info, rules)
        if section != s.section:
            s.signals["original_section"] = s.section
            s.signals["section_rule"] = why
            s.section = section
    return scored


def rewrite_summary(scored: list[ScoredCluster]) -> dict[str, int]:
    """改寫分版的統計，例如 {"cross_strait→world": 12}；寫進 stats["section_rewrites"]。"""
    counts: dict[str, int] = {}
    for s in scored:
        original = s.signals.get("original_section")
        if original:
            key = f"{original}→{s.section}"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def select_briefs(
    scored: list[ScoredCluster],
    selections: list[Selection],
    evidence_for: Callable[[ScoredCluster], list[EvidenceItem]],
    *,
    sections: tuple[str, ...] = BRIEF_SECTIONS,
    per_section: int = BRIEFS_PER_SECTION,
) -> list[dict]:
    """其他版的事件只出頭版標題短訊：標題取證據包裡的中文來源（沒有就第一篇），不呼叫 LLM。"""
    chosen = {cid for sel in selections for cid in sel.cluster.all_ids}
    kind_rank = {kind: i for i, kind in enumerate(BRIEF_KINDS)}
    briefs = []
    for section in sections:
        candidates = sorted(
            (s for s in scored if s.section == section and s.kind in BRIEF_KINDS and s.cluster_id not in chosen),
            key=lambda s: (kind_rank[s.kind], -s.score, s.cluster_id),
        )
        taken = 0
        for s in candidates:
            if taken == per_section:
                break
            evidence = evidence_for(s)
            if not evidence:
                continue
            lead = next((e for e in evidence if (e.lang or "").startswith("zh")), evidence[0])
            briefs.append(
                {
                    "cluster_id": s.cluster_id,
                    "section": section,
                    "kind": s.kind,
                    "label": story_label(evidence, s.kind),
                    "headline": strip_title_labels(lead.title),
                    "outlet": short_outlet(lead.source_name),
                    "url": lead.url,
                    "outlet_count": s.signals.get("outlet_count"),
                    "score": s.score,
                }
            )
            taken += 1
    return briefs
