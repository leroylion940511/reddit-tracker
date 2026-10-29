"""事件評分與各版選題；全部由程式計算，LLM 不參與。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..collection.collector import as_utc
from ..models import DailyArticle, DailyEdition, SourceItem, StoryCluster

TAIPEI = ZoneInfo("Asia/Taipei")
WINDOW_LEAD = timedelta(hours=6)
VELOCITY_WINDOW = timedelta(hours=12)
MAX_AGE_PENALTY = 8.0
FRONT_PAGE_SIZE = 6
FRONT_PAGE_PER_SECTION = 2
DESK_POOL_PER_SECTION = 2  # 每版送編輯會議的候選數＝配額 × 2
SECTION_QUOTAS = {
    "taiwan": 5,
    "world": 5,
    "cross_strait": 3,
    "finance": 4,
    "tech": 4,
    "science_health": 3,
    "life_env": 3,
    "culture": 3,
    "sports": 3,
    "social": 3,
}
SECTION_KINDS = {section: ("report", "single_source") for section in SECTION_QUOTAS}
SECTION_KINDS["social"] = ("social",)


@dataclass
class ScoredCluster:
    cluster_id: int
    section: str
    kind: str
    score: float
    signals: dict = field(default_factory=dict)
    # 編輯會議判定為同一事件（通常是中英文各一）而併入的其他事件
    merged_ids: list[int] = field(default_factory=list)

    @property
    def all_ids(self) -> list[int]:
        return [self.cluster_id, *self.merged_ids]


@dataclass
class Selection:
    cluster: ScoredCluster
    section: str
    position: int
    is_front: bool


def window_start_for(edition_date: date) -> datetime:
    """報紙日期前一天 00:00（台北）再往前 6 小時，接住前一晚的後續報導。"""
    day_before = datetime.combine(edition_date - timedelta(days=1), time.min, TAIPEI)
    return (day_before - WINDOW_LEAD).astimezone(timezone.utc)


def kind_for(cluster: StoryCluster) -> str:
    if cluster.outlet_count >= 2 or cluster.t1_count > 0:
        return "report"
    if cluster.outlet_count == 1:
        return "single_source"
    return "social"


def score_cluster(cluster: StoryCluster, *, recent_items: int, now: datetime) -> tuple[float, dict]:
    age_hours = max(0.0, (now - as_utc(cluster.last_published_at)).total_seconds() / 3600)
    velocity = recent_items / cluster.item_count if cluster.item_count >= 3 else 0.0
    parts = {
        "outlets": 10 * math.log2(1 + cluster.outlet_count),
        "official": 6.0 if cluster.t1_count > 0 else 0.0,
        "volume": 2 * math.log2(1 + cluster.item_count),
        "velocity": 4 * velocity,
        "age_penalty": -min(MAX_AGE_PENALTY, age_hours / 6),
    }
    signals = {
        **{k: round(v, 2) for k, v in parts.items()},
        "outlet_count": cluster.outlet_count,
        "item_count": cluster.item_count,
        "t1_count": cluster.t1_count,
        "t2_count": cluster.t2_count,
        "t4_count": cluster.t4_count,
        "age_hours": round(age_hours, 1),
    }
    return round(sum(parts.values()), 2), signals


def _vote_sections(
    session: Session, cluster_ids: list[int], general_sources: frozenset[str], disabled_sources: frozenset[str]
) -> dict[int, str]:
    """依目前登錄表重新決定板塊：T1／T2 非綜合 feed 的成員投票，聚合當時存的板塊只是後備。"""
    votes: dict[int, Counter] = defaultdict(Counter)
    fallback: dict[int, Counter] = defaultdict(Counter)
    rows = session.execute(
        select(SourceItem.cluster_id, SourceItem.source_id, SourceItem.section, SourceItem.tier).where(
            SourceItem.cluster_id.in_(cluster_ids)
        )
    )
    for cluster_id, source_id, section, tier in rows:
        if source_id in general_sources or source_id in disabled_sources:
            continue
        fallback[cluster_id][section] += 1
        if tier in ("T1", "T2"):
            votes[cluster_id][section] += 1
    return {
        cluster_id: (votes.get(cluster_id) or fallback[cluster_id]).most_common(1)[0][0]
        for cluster_id in set(votes) | set(fallback)
    }


def score_candidates(
    session: Session,
    *,
    edition_date: date,
    now: datetime,
    general_sources: frozenset[str] = frozenset(),
    disabled_sources: frozenset[str] = frozenset(),
) -> list[ScoredCluster]:
    """`disabled_sources`：已停用來源的素材不算數；只由這些素材組成的事件不進選題。"""
    start = window_start_for(edition_date)
    published_before: set[int] = set()
    earlier = (
        select(DailyArticle.cluster_id, DailyArticle.signals)
        .join(DailyEdition, DailyArticle.edition_id == DailyEdition.id)
        .where(DailyEdition.edition_date < edition_date)
    )
    for cluster_id, signals in session.execute(earlier):
        published_before.add(cluster_id)
        published_before.update((signals or {}).get("merged_cluster_ids", []))
    clusters = [
        c
        for c in session.scalars(
            select(StoryCluster).where(
                StoryCluster.last_published_at >= start,
                StoryCluster.last_published_at <= now,
            )
        )
        if c.id not in published_before
    ]
    if clusters and disabled_sources:
        alive = set(
            session.scalars(
                select(SourceItem.cluster_id).where(
                    SourceItem.cluster_id.in_([c.id for c in clusters]),
                    SourceItem.source_id.not_in(sorted(disabled_sources)),
                )
            )
        )
        clusters = [c for c in clusters if c.id in alive]
    if not clusters:
        return []
    recent = dict(
        session.execute(
            select(SourceItem.cluster_id, func.count())
            .where(
                SourceItem.cluster_id.in_([c.id for c in clusters]),
                SourceItem.first_seen_at >= now - VELOCITY_WINDOW,
                SourceItem.source_id.not_in(sorted(disabled_sources)),
            )
            .group_by(SourceItem.cluster_id)
        ).all()
    )
    sections = _vote_sections(session, [c.id for c in clusters], general_sources, disabled_sources)
    scored = []
    for cluster in clusters:
        score, signals = score_cluster(cluster, recent_items=recent.get(cluster.id, 0), now=now)
        section = sections.get(cluster.id, cluster.section)
        scored.append(ScoredCluster(cluster.id, section, kind_for(cluster), score, signals))
    return sorted(scored, key=lambda s: (-s.score, s.cluster_id))


def desk_pool(scored: list[ScoredCluster]) -> list[ScoredCluster]:
    """送編輯會議比對的候選：各版依選題順序取配額的兩倍。"""
    kind_rank = {"report": 0, "single_source": 1, "social": 2}
    pool = []
    for section, quota in SECTION_QUOTAS.items():
        pool += sorted(
            (s for s in scored if s.section == section and s.kind in SECTION_KINDS[section]),
            key=lambda s: (kind_rank[s.kind], -s.score, s.cluster_id),
        )[: quota * DESK_POOL_PER_SECTION]
    return pool


def apply_merges(scored: list[ScoredCluster], groups: list[list[int]]) -> list[ScoredCluster]:
    """把同一事件的多個 cluster 併成一則：保留分數最高者，其餘列入 merged_ids。"""
    by_id = {s.cluster_id: s for s in scored}
    absorbed: set[int] = set()
    owner: dict[int, int] = {}
    for group in groups:
        # 已被吸收的事件改指向吸收它的那一則
        members = list({id(m): m for m in (by_id[owner.get(i, i)] for i in group if i in by_id)}.values())
        if len(members) < 2:
            continue
        keeper = max(members, key=lambda s: (s.score, -s.cluster_id))
        for other in members:
            if other is keeper:
                continue
            # 重疊的組（A＋B、B＋C）：被吸收的一方之前併入的事件要一起帶過來，不能遺失。
            keeper.merged_ids += [other.cluster_id, *other.merged_ids]
            for moved in (other.cluster_id, *other.merged_ids):
                owner[moved] = keeper.cluster_id
            other.merged_ids = []
            absorbed.add(other.cluster_id)
            if other.kind == "report":
                keeper.kind = "report"
        keeper.signals["merged_cluster_ids"] = list(keeper.merged_ids)
    return [s for s in scored if s.cluster_id not in absorbed]


def select_articles(scored: list[ScoredCluster]) -> list[Selection]:
    """頭版取分數最高的 report（每版最多 2 則）；各版依配額補足，report 優先、寧缺勿濫。"""
    front: list[ScoredCluster] = []
    per_section: dict[str, int] = {}
    for s in sorted(scored, key=lambda s: (-s.score, s.cluster_id)):
        if len(front) == FRONT_PAGE_SIZE:
            break
        if s.kind != "report" or s.section not in SECTION_QUOTAS:
            continue
        if per_section.get(s.section, 0) >= FRONT_PAGE_PER_SECTION:
            continue
        per_section[s.section] = per_section.get(s.section, 0) + 1
        front.append(s)
    used = {s.cluster_id for s in front}
    selections = [
        Selection(cluster=s, section=s.section, position=i, is_front=True)
        for i, s in enumerate(front, start=1)
    ]
    kind_rank = {"report": 0, "single_source": 1, "social": 2}
    for section, quota in SECTION_QUOTAS.items():
        candidates = sorted(
            (
                s
                for s in scored
                if s.section == section and s.kind in SECTION_KINDS[section] and s.cluster_id not in used
            ),
            key=lambda s: (kind_rank[s.kind], -s.score, s.cluster_id),
        )[:quota]
        for position, chosen in enumerate(candidates, start=1):
            used.add(chosen.cluster_id)
            selections.append(Selection(cluster=chosen, section=section, position=position, is_front=False))
    return selections
