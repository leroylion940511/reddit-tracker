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
from difflib import SequenceMatcher
from urllib.parse import urlsplit

import zhconv
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SourceItem, StoryCluster
from .collector import as_utc
from .entities import EntityContext, EntityLexicon, MergeRules, load_lexicon
from .normalize import title_key

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
CNA_DOMAIN = "cna.com.tw"
# 轉載辨識（手冊步驟 3 第 6 點、E10）：去開頭標籤後標題相似度 ≥ 0.8，或轉載方內文帶中央社電頭，
# 而且發布時間差 2 小時內。相似度只用在兩篇都是中文時：英文各家獨立報導的標題常常幾乎一樣
# （10/27 微軟優離：The Verge 與 CNBC 相似度 0.89），英文轉載（Yahoo Finance 轉 Reuters）
# 標題完全相同，收集時已判成重複稿。
REPRINT_TITLE_SIMILARITY = 0.8
REPRINT_MAX_GAP = timedelta(hours=2)
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


def has_cna_wire(title: str | None, summary: str | None) -> bool:
    text = f"{title or ''} {summary or ''}"
    return any(marker in text for marker in CNA_WIRE_MARKERS)


def domain_of(canonical_url: str) -> str:
    """可註冊網域（news.ltn.com.tw → ltn.com.tw）。"""
    labels = (urlsplit(canonical_url).hostname or "").split(".")
    keep = 3 if len(labels) >= 3 and tuple(labels[-2:]) in SECOND_LEVEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def outlet_of(canonical_url: str, title: str | None, summary: str | None) -> str:
    """出處：可註冊網域；內文帶中央社電頭的轉載稿歸中央社。"""
    if has_cna_wire(title, summary):
        return CNA_DOMAIN
    return domain_of(canonical_url)


def _is_reprint_pair(a: SourceItem, b: SourceItem, keys: dict[int, str]) -> bool:
    if abs(as_utc(a.published_at) - as_utc(b.published_at)) > REPRINT_MAX_GAP:
        return False
    for original, copy in ((a, b), (b, a)):
        # 中央社電頭：轉載方（不是中央社自己）內文寫明是中央社稿，原稿是中央社的稿
        if (
            domain_of(original.canonical_url) == CNA_DOMAIN
            and domain_of(copy.canonical_url) != CNA_DOMAIN
            and has_cna_wire(copy.title, copy.summary)
        ):
            return True
    ka, kb = keys[a.id], keys[b.id]
    if not ka or not kb or lang_group(a.lang) != "zh" or lang_group(b.lang) != "zh":
        return False
    matcher = SequenceMatcher(None, ka, kb, autojunk=False)
    return matcher.real_quick_ratio() >= REPRINT_TITLE_SIMILARITY and matcher.ratio() >= REPRINT_TITLE_SIMILARITY


def _reprint_rank(item: SourceItem) -> tuple:
    """同一組轉載裡誰是原稿：中央社優先（央廣、Yahoo 多半轉中央社），其次層級高、先發布、id 小。"""
    return (
        domain_of(item.canonical_url) != CNA_DOMAIN,
        TIER_RANK.get(item.tier, 9),
        as_utc(item.published_at),
        item.id,
    )


def mark_reprints(members: list[SourceItem]) -> dict[int, int]:
    """看整組素材找轉載，回傳 {轉載素材 id: 原稿 id}；原稿與非轉載素材不在結果裡。

    `outlet_of` 一次只看一篇，無法兩兩比對，所以另寫這個。收集時已判為重複稿
    （`duplicate_of_id`，標題指紋或網址相同）的一律算轉載；另外兩篇標題去掉開頭
    標籤後相似度 ≥ `REPRINT_TITLE_SIMILARITY`（只比中文標題）、或轉載方帶中央社電頭，而且發布時間差
    在 `REPRINT_MAX_GAP` 內，也算轉載。相連的素材成一組，組內 `_reprint_rank` 最前的是原稿。
    """
    by_id = {m.id: m for m in members}
    parent = {m.id: m.id for m in members}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for member in members:
        if member.duplicate_of_id in by_id:
            union(member.id, member.duplicate_of_id)
    keys = {m.id: title_key(m.title) for m in members}
    ordered = sorted(members, key=lambda m: as_utc(m.published_at))
    for x, a in enumerate(ordered):
        for b in ordered[x + 1 :]:
            if as_utc(b.published_at) - as_utc(a.published_at) > REPRINT_MAX_GAP:
                break
            if find(a.id) != find(b.id) and _is_reprint_pair(a, b, keys):
                union(a.id, b.id)
    groups: dict[int, list[SourceItem]] = defaultdict(list)
    for member in members:
        groups[find(member.id)].append(member)
    reprints = {}
    for group in groups.values():
        original = min(group, key=_reprint_rank)
        reprints.update({m.id: original.id for m in group if m is not original})
    return reprints


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
    # 轉載不算多來源（硬規則 3）：重複稿與 `mark_reprints` 認出的轉載只算原稿那一家。
    reprints = mark_reprints(members)
    cluster.outlet_count = len(
        {
            outlet_of(m.canonical_url, m.title, m.summary)
            for m in members
            if m.tier != "T4" and m.duplicate_of_id is None and m.id not in reprints
        }
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
