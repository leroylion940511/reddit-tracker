"""事件聚合：把不同媒體報導同一件事的 source_items 併成 story_clusters。

規格見 docs/v5/CLUSTERING.md。TF-IDF 餘弦相似度、增量指派：既有素材的事件
歸屬不再改變，新素材併入最相近的既有事件或自成新事件。
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import zhconv
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SourceItem, StoryCluster
from .collector import as_utc
from .entities import EntityContext, EntityLexicon, MergeRules, load_lexicon

# 除了與某一篇夠像，也要與事件整體（成員向量和）夠像，避免單一連結一路串錯。
CENTROID_MIN = 0.20
WINDOW = timedelta(hours=72)
MAX_PUBLISH_GAP = timedelta(hours=48)
SUMMARY_CHARS = 300
# 只用「不太常見」的 token 找候選，避免每篇都和整個時間窗比對；
# 候選選出後再用完整向量算精確分數。
CANDIDATE_MAX_DF_RATIO = 0.05
CANDIDATE_MIN_DF_CAP = 50
MAX_CANDIDATES = 20
TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}
CNA_WIRE_MARKERS = ("中央社記者", "（中央社", "(中央社")
SECOND_LEVEL_SUFFIXES = {
    ("com", "tw"), ("org", "tw"), ("gov", "tw"), ("edu", "tw"), ("net", "tw"),
    ("co", "uk"), ("org", "uk"), ("com", "hk"), ("com", "sg"), ("co", "jp"),
    ("or", "jp"), ("ne", "jp"), ("com", "cn"), ("com", "au"),
}
EN_STOPWORDS = frozenset(
    "the and for with that this from are was were has have had not but its it's into over "
    "after about more than will would could should can may says said say new also been "
    "their they them his her she him who what when where which while how why our out "
    "you your all any one two first last year years week day days today amid against "
    "between under just like make made get gets got news live update updates "
    # hnrss 等聚合 feed 的摘要樣板，會讓無關的文章彼此相似
    "article url comments points".split()
)

_CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_WORD = re.compile(r"[a-z]+|\d{3,}")
_URL = re.compile(r"https?://\S+")
# 通訊社電頭、圖說、民國日期等樣板：每篇都有，會讓同一家媒體的無關稿件彼此相似。
_BOILERPLATE = re.compile(
    r"[（(]中央社[^）)]{0,40}[）)]|中央社記者\S{0,8}攝|\d{2,4}年\d{1,2}月\d{1,2}日|\d{1,2}日電"
)


@dataclass
class ClusterRunStats:
    window_items: int = 0
    joined_existing: int = 0
    new_clusters: int = 0
    duplicates_assigned: int = 0
    touched_clusters: int = 0
    # 相似度夠、但共同實體不足而沒合併的次數（不確定就不要合併）
    rejected_no_entity: int = 0


def lang_group(lang: str | None) -> str:
    return "zh" if (lang or "").startswith("zh") else (lang or "und")


def tokenize(text: str, lang: str | None) -> list[str]:
    if lang == "zh":
        text = zhconv.convert(text, "zh-tw")
    text = _BOILERPLATE.sub(" ", unicodedata.normalize("NFKC", text))
    text = _URL.sub(" ", text.lower())
    tokens = [run[i : i + 2] for run in _CJK_RUN.findall(text) for i in range(len(run) - 1)]
    tokens += [w for w in _WORD.findall(text) if w.isdigit() or (len(w) > 2 and w not in EN_STOPWORDS)]
    return tokens


def outlet_of(canonical_url: str, title: str | None, summary: str | None) -> str:
    text = f"{title or ''} {summary or ''}"
    if any(marker in text for marker in CNA_WIRE_MARKERS):
        return "cna.com.tw"
    labels = (urlsplit(canonical_url).hostname or "").split(".")
    keep = 3 if len(labels) >= 3 and tuple(labels[-2:]) in SECOND_LEVEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def _document_text(item: SourceItem) -> str:
    title = item.title or ""
    return f"{title} {title} {(item.summary or '')[:SUMMARY_CHARS]}"


def _vectorize(token_lists: list[list[str]]) -> tuple[list[dict[str, float]], Counter]:
    df: Counter = Counter()
    for tokens in token_lists:
        df.update(set(tokens))
    total = len(token_lists)
    vectors = []
    for tokens in token_lists:
        weights = {
            token: (1 + math.log(count)) * (math.log((total + 1) / (df[token] + 1)) + 1)
            for token, count in Counter(tokens).items()
        }
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        vectors.append({token: w / norm for token, w in weights.items()})
    return vectors, df


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(token, 0.0) for token, w in a.items())


def _refresh_cluster(
    session: Session,
    cluster: StoryCluster,
    now: datetime,
    general_sources: frozenset[str],
    disabled_sources: frozenset[str] = frozenset(),
) -> None:
    members = session.scalars(select(SourceItem).where(SourceItem.cluster_id == cluster.id)).all()
    # 舊事件裡可能混有已停用來源的素材；事件訊號只看仍啟用的來源。
    members = [m for m in members if m.source_id not in disabled_sources] or members
    tiers = Counter(member.tier for member in members)
    # 綜合 feed（央廣、中央社聚焦等）的板塊不代表這則新聞的板塊，不參與投票。
    voters = [m for m in members if m.source_id not in general_sources]
    editorial = [m for m in voters if m.tier in ("T1", "T2")] or voters or members
    representative = min(
        (m for m in members if m.duplicate_of_id is None),
        key=lambda m: (TIER_RANK.get(m.tier, 9), as_utc(m.published_at)),
    )
    cluster.section = Counter(m.section for m in editorial).most_common(1)[0][0]
    cluster.title = representative.title
    cluster.representative_item_id = representative.id
    cluster.item_count = len(members)
    cluster.outlet_count = len(
        {outlet_of(m.canonical_url, m.title, m.summary) for m in members if m.tier != "T4"}
    )
    cluster.t1_count, cluster.t2_count, cluster.t4_count = tiers["T1"], tiers["T2"], tiers["T4"]
    cluster.first_published_at = min(as_utc(m.published_at) for m in members)
    cluster.last_published_at = max(as_utc(m.published_at) for m in members)
    cluster.updated_at = now


def _centroid_score(vector: dict[str, float], centroid: dict[str, float]) -> float:
    norm = math.sqrt(sum(w * w for w in centroid.values())) or 1.0
    return _cosine(vector, centroid) / norm


def cluster_recent_items(
    session: Session,
    *,
    now: datetime | None = None,
    rules: MergeRules | None = None,
    lexicon: EntityLexicon | None = None,
    general_sources: frozenset[str] = frozenset(),
    disabled_sources: frozenset[str] = frozenset(),
) -> ClusterRunStats:
    """`rules`／`lexicon` 預設取設定值與 seeds 檔（譯名表、常見字）。"""
    now = now or datetime.now(timezone.utc)
    rules = rules or MergeRules.from_settings()
    lexicon = lexicon or load_lexicon()
    stats = ClusterRunStats()
    # 已停用來源（例如 2026-10-28 停用的社群來源）以前抓到的素材不再參與聚合。
    items = session.scalars(
        select(SourceItem)
        .where(
            SourceItem.duplicate_of_id.is_(None),
            SourceItem.published_at >= now - WINDOW,
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
        .order_by(SourceItem.published_at, SourceItem.id)
    ).all()
    stats.window_items = len(items)
    if not items:
        return stats

    vectors, df = _vectorize([tokenize(_document_text(item), item.lang) for item in items])
    max_df = max(CANDIDATE_MIN_DF_CAP, int(len(items) * CANDIDATE_MAX_DF_RATIO))
    groups = [lang_group(item.lang) for item in items]
    entities = [lexicon.entities(item.title or "", group == "zh") for item, group in zip(items, groups)]
    # 「當天素材」＝這次時間窗內的素材標題：中文片段要在 5% 以下的素材出現才算少見，
    # 英文句首字要有別篇在句中大寫佐證。
    context = EntityContext(entities)
    index: dict[str, list[int]] = defaultdict(list)
    centroids: dict[int, Counter] = defaultdict(Counter)
    touched: dict[int, StoryCluster] = {}

    def place(position: int, cluster_id: int) -> None:
        centroids[cluster_id].update(vectors[position])
        for token in vectors[position]:
            if df[token] <= max_df:
                index[token].append(position)

    for position, item in enumerate(items):
        if item.cluster_id is not None:
            place(position, item.cluster_id)

    for position, item in enumerate(items):
        if item.cluster_id is not None:
            continue
        vector = vectors[position]
        overlap: Counter = Counter()
        for token, weight in vector.items():
            for other in index.get(token, ()):
                overlap[other] += weight * vectors[other][token]
        published = as_utc(item.published_at)
        scored = []
        for other, _ in overlap.most_common(MAX_CANDIDATES):
            if groups[other] != groups[position]:
                continue
            if abs(as_utc(items[other].published_at) - published) > MAX_PUBLISH_GAP:
                continue
            score = _cosine(vector, vectors[other])
            if rules.required_entities(score) is not None:
                scored.append((score, other))

        # 由最像的開始找：相似度過門檻、共同實體夠、和事件整體也夠像，才併入。
        cluster = None
        for score, other in sorted(scored, key=lambda pair: (-pair[0], pair[1])):
            target = items[other].cluster_id
            if target is None or _centroid_score(vector, centroids[target]) < CENTROID_MIN:
                continue
            shared = lexicon.shared(entities[position], entities[other], context)
            if len(shared) < rules.required_entities(score):
                stats.rejected_no_entity += 1
                continue
            cluster = touched.get(target) or session.get(StoryCluster, target)
            stats.joined_existing += 1
            break
        if cluster is None:
            cluster = StoryCluster(
                lang_group=groups[position],
                section=item.section,
                title=item.title,
                first_published_at=published,
                last_published_at=published,
                created_at=now,
                updated_at=now,
            )
            session.add(cluster)
            session.flush()
            stats.new_clusters += 1
        item.cluster_id = cluster.id
        touched[cluster.id] = cluster
        place(position, cluster.id)

    session.flush()
    root_cluster = {item.id: item.cluster_id for item in items}
    duplicates = session.scalars(
        select(SourceItem).where(
            SourceItem.duplicate_of_id.in_(list(root_cluster)),
            SourceItem.cluster_id.is_(None),
            SourceItem.source_id.not_in(sorted(disabled_sources)),
        )
    ).all()
    for duplicate in duplicates:
        duplicate.cluster_id = root_cluster[duplicate.duplicate_of_id]
        if duplicate.cluster_id not in touched:
            touched[duplicate.cluster_id] = session.get(StoryCluster, duplicate.cluster_id)
    stats.duplicates_assigned = len(duplicates)
    session.flush()

    for cluster in touched.values():
        _refresh_cluster(session, cluster, now, general_sources, disabled_sources)
    stats.touched_clusters = len(touched)
    return stats
