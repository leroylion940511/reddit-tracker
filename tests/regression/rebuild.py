"""回歸集 runner：用離線 fixture 在 tmp SQLite 上重編 10/27 那一期（手冊步驟 2）。

流程與線上相同、全部走正式程式碼：
1. `1027_items.json.xz` 的素材寫進 tmp SQLite（不碰 production、不碰母本）。
2. 照線上當時的聚合時間表（`cluster_runs_utc`：10/26 22:53 首輪＋之後每輪收集）逐輪
   「放入該輪收到的素材 → `cluster_recent_items(now=該輪)`」，cluster id 會重新編號。
   一次全部重聚（手冊 3.8 的做法）跟線上的增量結果不同，例如 E03 就重現不出來。
3. `prepare_daily(now=…, writer=…)` 評分、編輯會議、選題、證據包、撰稿、審稿、渲染。
   - 編輯會議（`find_same_events`）用 `1027_merges.json` 重播：素材 id 對回新的 cluster id。
   - 撰稿等其他 LLM 請求走 `ReplayClient`（request_hash 查錄好的回應）；錄音檔
     `fixtures/1027_llm_records.json` 在步驟 7 之後才會有，找不到就記在 `replay_misses`，
     需要稿件文字的案例一律判失敗（不會改呼叫真模型）。
   - 數據欄用 10/27 當期記錄的證交所數值重播（不連網）。
4. 另外替案例提到的每個事件（不論有沒有見報）用同一個 `story_evidence` 組證據包。
"""

from __future__ import annotations

import json
import lzma
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import zhconv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from reddit_tracker.collection.clustering import cluster_recent_items, outlet_of
from reddit_tracker.collection.normalize import canonicalize_url
from reddit_tracker.config import get_settings
from reddit_tracker.daily import market as market_module
from reddit_tracker.daily import run
from reddit_tracker.daily.render import render_html
from reddit_tracker.daily.writer import GROUPS_SCHEMA, DailyWriter
from reddit_tracker.llm.replay import ReplayClient, ReplayResult, load_records
from reddit_tracker.models import Base, DailyArticle, DailyEdition, SourceItem, StoryCluster
from reddit_tracker.seeds.news_sources import load_registry

FIXTURES = Path(__file__).parent / "fixtures"
CASES_DIR = Path(__file__).parent / "cases"
EDITION_DATE = date(2026, 10, 27)
RECORDINGS = FIXTURES / "1027_llm_records.json"  # 步驟 7 之後才有

_SPACE = re.compile(r"\s+")


def norm_title(title: str | None) -> str:
    """比對標題用：NFKC、簡轉繁（證據包會轉）、去空白。"""
    text = zhconv.convert(unicodedata.normalize("NFKC", title or ""), "zh-tw")
    return _SPACE.sub("", text)


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_items() -> dict:
    return json.loads(lzma.decompress((FIXTURES / "1027_items.json.xz").read_bytes()))


def load_cases() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES_DIR.glob("E*.json"))]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# ── 版面的抽象：刊出版（10/27 實際）與重編版用同一套檢查 ───────────────────


@dataclass
class ClusterInfo:
    cluster_id: int
    outlet_count: int
    members: list[dict]  # {"title": 正規化標題, "outlet", "tier", "duplicate_of_id"}


@dataclass
class Story:
    key: str
    section: str
    kind: str
    published: bool
    is_front: bool
    sources: list[dict]  # 證據包／刊出出處：{"title", "source_id", "outlet"}
    members: set[str]  # 事件所有素材的正規化標題（刊出版只知道出處）
    clusters: list[ClusterInfo] = field(default_factory=list)  # 重編版才有
    headline: str | None = None
    deck: str | None = None
    body: str | None = None
    why_it_matters: str | None = None
    writer: str | None = None

    @property
    def source_titles(self) -> list[str]:
        return [norm_title(s["title"]) for s in self.sources]

    @property
    def text(self) -> str:
        return "\n".join(x for x in (self.headline, self.deck, self.body, self.why_it_matters) if x)


@dataclass
class EditionView:
    name: str
    edition_date: date
    events: list[Story]
    html: str
    market: list[dict] | None
    replay_misses: list[str] | None = None  # None：刊出版不適用

    @property
    def published(self) -> list[Story]:
        return [s for s in self.events if s.published]

    def events_with(self, titles: list[str]) -> list[Story]:
        wanted = {norm_title(t) for t in titles}
        return [s for s in self.events if s.members & wanted]


def published_view() -> EditionView:
    """10/27 實際刊出的版面（fixture，不需要母本）。"""
    data = load_json("1027_edition.json")
    events = []
    for article in data["articles"]:
        sources = [{"title": s["title"], "source_id": s["source_id"], "outlet": s["outlet"]} for s in article["sources"]]
        events.append(
            Story(
                key=f"published:{article['cluster_id']}",
                section=article["section"],
                kind=article["kind"],
                published=True,
                is_front=article["is_front"],
                sources=sources,
                members={norm_title(s["title"]) for s in sources},
                headline=article["headline"],
                deck=article["deck"],
                body=article["body"],
                why_it_matters=article["why_it_matters"],
                writer=article["writer"],
            )
        )
    edition = DailyEdition(edition_date=EDITION_DATE, stats={"market": data["market"]})
    sections = load_registry(get_settings().news_sources_path).sections
    return EditionView("published", EDITION_DATE, events, render_html(edition, sections), data["market"])


# ── 重播 ────────────────────────────────────────────────────────────────


class MergesReplayClient:
    """編輯會議用 `1027_merges.json` 重播；其他請求交給 request_hash replay。"""

    def __init__(self, groups: list[list[int]], inner: ReplayClient) -> None:
        self.groups = groups
        self.inner = inner

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(self, *, system, messages, max_output_tokens, temperature, json_mode=False, json_schema=None):
        if json_schema == GROUPS_SCHEMA:
            return ReplayResult(json.dumps({"groups": self.groups}))
        return self.inner.complete(
            system=system, messages=messages, max_output_tokens=max_output_tokens,
            temperature=temperature, json_mode=json_mode, json_schema=json_schema,
        )


def replay_groups(item_groups: list[list[int]], cluster_of: dict[int, int | None]) -> list[list[int]]:
    """素材 id 組 → 重編後的 cluster id 組（保留順序、去重，少於 2 個 cluster 的組丟掉）。"""
    groups = []
    for items in item_groups:
        ids = list(dict.fromkeys(cluster_of[i] for i in items if cluster_of.get(i) is not None))
        if len(ids) >= 2:
            groups.append(ids)
    return groups


def _twse_rows(market: list[dict]) -> list[dict]:
    """把當期記錄的數據欄還原成證交所 MI_INDEX 的列，讓 `fetch_market_box` 照常解析。"""
    rows = []
    for m in market:
        y, mo, d = m["date"].split("-")
        rows.append({
            "日期": f"{int(y) - 1911:03d}{mo}{d}",
            "指數": m["name"],
            "收盤指數": m["close"],
            "漲跌": "-" if m["change"].startswith("-") else "+",
            "漲跌點數": m["change"].lstrip("+-"),
            "漲跌百分比": m["change_pct"].rstrip("%"),
        })
    return rows


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def _insert_items(engine, items: list[dict]) -> None:
    with Session(engine) as session:
        session.add_all(
            SourceItem(
                id=item["id"],
                source_id=item["source_id"],
                section=item["section"],
                tier=item["tier"],
                item_key=str(item["id"]),
                url=item["url"],
                canonical_url=canonicalize_url(item["url"]),
                title=item["title"],
                summary=item["summary"],
                lang=item["lang"],
                published_at=_utc(item["published_at"]),
                published_at_estimated=item["published_at_estimated"],
                first_seen_at=_utc(item["first_seen_at"]),
                duplicate_of_id=item["duplicate_of_id"],
            )
            for item in items
        )
        session.commit()


def rebuild_view(workdir: Path, needed_titles: set[str]) -> EditionView:
    """在 `workdir` 的 tmp SQLite 重編 10/27；`needed_titles`：要額外組證據包的事件標題。"""
    data = load_items()
    now = _utc(data["now_utc"])
    settings = get_settings()
    registry = load_registry(settings.news_sources_path)
    db_path = workdir / "1027_rebuild.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)

    pending = sorted(data["items"], key=lambda item: item["first_seen_at"])
    for run_at in data["cluster_runs_utc"]:
        batch = [item for item in pending if _utc(item["first_seen_at"]) <= _utc(run_at)]
        pending = pending[len(batch):]
        _insert_items(engine, batch)
        with Session(engine) as session:
            cluster_recent_items(
                session,
                now=_utc(run_at),
                general_sources=registry.general_source_ids(),
                disabled_sources=registry.disabled_source_ids(),
            )
            session.commit()
    assert not pending, "有素材晚於最後一輪聚合"
    with Session(engine) as session:
        cluster_of = dict(session.execute(select(SourceItem.id, SourceItem.cluster_id)).all())

    records = load_records(RECORDINGS) if RECORDINGS.exists() else {}
    replay = ReplayClient(records, model=settings.codex_model)
    client = MergesReplayClient(replay_groups(load_json("1027_merges.json"), cluster_of), replay)
    writer = DailyWriter("replay", client=client)
    edition_market = load_json("1027_edition.json")["market"]

    @contextmanager
    def scope():
        session = Session(engine, expire_on_commit=False, autoflush=False)
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    captured = {}
    plan_edition = run.plan_edition

    def capture_plan(session, **kwargs):
        captured["plan"] = plan_edition(session, **kwargs)
        return captured["plan"]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(run, "session_scope", scope)
        mp.setattr(run, "plan_edition", capture_plan)
        mp.setattr(run, "RETRY_DELAY_SECONDS", 0)
        mp.setattr(market_module.requests, "get", lambda *a, **k: _FakeResponse(_twse_rows(edition_market)))
        mp.setenv("DAILY_SITE_DIR", str(workdir / "site"))
        get_settings.cache_clear()
        try:
            edition_id = run.prepare_daily(EDITION_DATE, now=now, writer=writer)
        finally:
            get_settings.cache_clear()

    plan = captured["plan"]
    with Session(engine) as session:
        edition = session.get(DailyEdition, edition_id)
        html = Path(edition.html_path).read_text(encoding="utf-8")
        market = (edition.stats or {}).get("market")
        articles = {a.cluster_id: a for a in session.scalars(select(DailyArticle).where(DailyArticle.edition_id == edition_id))}
        members: dict[int, list[SourceItem]] = {}
        for item in session.scalars(select(SourceItem).where(SourceItem.cluster_id.is_not(None))):
            members.setdefault(item.cluster_id, []).append(item)
        outlet_counts = dict(session.execute(select(StoryCluster.id, StoryCluster.outlet_count)).all())
        wanted = {norm_title(t) for t in needed_titles}
        planned = {p.selection.cluster.cluster_id: p for p in plan.planned}

        events = []
        for candidate in plan.candidates:
            items = [m for cid in candidate.all_ids for m in members.get(cid, [])]
            titles = {norm_title(m.title) for m in items}
            chosen = planned.get(candidate.cluster_id)
            if chosen is None and not titles & wanted:
                continue
            evidence = chosen.evidence if chosen else run.story_evidence(session, candidate, registry)
            article = articles.get(candidate.cluster_id) if chosen else None
            events.append(
                Story(
                    key=f"rebuild:{'+'.join(map(str, candidate.all_ids))}",
                    section=chosen.selection.section if chosen else candidate.section,
                    kind=candidate.kind,
                    published=chosen is not None,
                    is_front=chosen.selection.is_front if chosen else False,
                    sources=[{"title": e.title, "source_id": e.source_id, "outlet": e.source_name} for e in evidence],
                    members=titles,
                    clusters=[
                        ClusterInfo(
                            cluster_id=cid,
                            outlet_count=outlet_counts[cid],
                            members=[
                                {
                                    "title": norm_title(m.title),
                                    "outlet": outlet_of(m.canonical_url, m.title, m.summary),
                                    "tier": m.tier,
                                    "duplicate_of_id": m.duplicate_of_id,
                                }
                                for m in members.get(cid, [])
                            ],
                        )
                        for cid in candidate.all_ids
                    ],
                    headline=article.headline if article else None,
                    deck=article.deck if article else None,
                    body=article.body if article else None,
                    why_it_matters=article.why_it_matters if article else None,
                    writer=article.writer if article else None,
                )
            )
    engine.dispose()
    return EditionView("rebuild", EDITION_DATE, events, html, market, replay_misses=list(replay.misses))
