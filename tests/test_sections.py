"""手冊步驟 4：併版（daily/sections.py）、三內版 12 篇配額、頭版短訊。全部離線，不呼叫 LLM。"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from reddit_tracker.collection.clustering import cluster_recent_items
from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.render import MVP_SECTIONS
from reddit_tracker.daily.scoring import SECTION_QUOTAS, ScoredCluster, select_articles
from reddit_tracker.daily.sections import (
    INNER_SECTIONS,
    Members,
    classify,
    load_section_rules,
    rewrite_sections,
)
from reddit_tracker.daily.writer import WrittenStory
from reddit_tracker.models import DailyEdition, SourceItem
from reddit_tracker.seeds.news_sources import SourceRegistry

NOW = datetime(2026, 10, 27, 22, 0, tzinfo=timezone.utc)
EDITION = date(2026, 10, 28)
RULES = load_section_rules()


def _m(*titles, langs=("zh-Hant",), sections=(), official=False):
    return Members(list(titles), frozenset(langs), frozenset(sections), official)


def test_quotas_are_three_inner_sections_twelve_articles():
    assert SECTION_QUOTAS == {"taiwan": 4, "world": 4, "tech": 4}
    assert sum(SECTION_QUOTAS.values()) == 12
    assert INNER_SECTIONS == MVP_SECTIONS


@pytest.mark.parametrize(
    "section, members, expected",
    [
        # 兩岸：與台灣直接相關 → 台灣；其他 → 國際
        ("cross_strait", _m("洪秀柱稱台灣少數人認賊作父 陸委會：勿貶低自己國家"), "taiwan"),
        ("cross_strait", _m("Former Japan Prime Minister Yasuo Fukuda dies at 90", langs=("en",)), "world"),
        ("cross_strait", _m("中國家庭規模持續縮小 平均每戶人口2.52人"), "world"),
        ("cross_strait", _m("China protests US arms sale to Taiwan", langs=("en",)), "taiwan"),
        ("cross_strait", _m("某官方新聞稿", official=True), "taiwan"),
        # 財經：台灣 → 科技 → 中文台灣財經 → 國際
        ("finance", _m("台積電法說會 台股大漲"), "taiwan"),
        ("finance", _m("騰輝-KY啟用泰國新廠 昆山同步擴產15億元"), "taiwan"),
        ("finance", _m("Microsoft offers voluntary buyouts to 60,000 employees", langs=("en",)), "tech"),
        ("finance", _m("AI太燒錢！Meta擬籌950億美元 輝達等三巨頭有意買單"), "tech"),
        ("finance", _m("Some company raises money", langs=("en",), sections=("tech",)), "tech"),
        ("finance", _m("怕升息砸百萬積蓄提前還房貸！他以為能省錢 半年後超後悔"), "taiwan"),
        ("finance", _m("《強勢美股特報》TSLA,DOW,CMG,ROST等10檔"), "world"),
        ("finance", _m("JetBlue posts bigger loss on fuel costs", langs=("en",)), "world"),
        ("finance", _m("中国乘联分会：今年国内汽车销量超预期低迷", langs=("zh",)), "world"),
        # 生活版的教育、社會類（E14）→ 台灣；其他生活新聞不動（只出短訊）
        ("life_env", _m("教育部：台灣高等研究學院無延宕 提前啟動試辦"), "taiwan"),
        ("life_env", _m("未來一週3波東北季風接力 迎風面易有短暫雨"), "life_env"),
        ("life_env", _m("Students protest school closures in France", langs=("en",)), "life_env"),
        # 其他版、三內版不動
        ("sports", _m("台灣隊經典賽奪冠"), "sports"),
        ("world", _m("台灣外交部回應"), "world"),
    ],
)
def test_classify(section, members, expected):
    new, why = classify(section, members, RULES)
    assert new == expected
    assert (why is None) == (new == section)


def test_english_terms_need_word_boundaries():
    assert classify("finance", _m("Thailand mail volumes rise", langs=("en",)), RULES)[0] == "world"  # 不是 AI
    assert classify("finance", _m("Brazil plans AI rules", langs=("en",)), RULES)[0] == "tech"


# ── DB：改寫分版、兩岸財經稿不消失、短訊不呼叫 LLM ──────────────────────


REGISTRY = SourceRegistry(
    version=1,
    sections={"taiwan": "台灣", "world": "國際", "cross_strait": "兩岸與亞太", "finance": "財經", "tech": "科技",
              "life_env": "生活與環境", "sports": "體育", "social": "社群觀察", "data": "數據欄"},
    sources=[
        {"id": f"{name}-{n}", "name": f"{label}{n}", "section": name, "tier": "T2", "method": "rss",
         "url": f"https://{name}{n}.example/rss", "lang": "zh-Hant"}
        for name, label in (("cross_strait", "兩岸媒體"), ("finance", "財經媒體"), ("life_env", "生活媒體"),
                            ("sports", "體育媒體"), ("world", "國際媒體"))
        for n in (1, 2)
    ] + [
        {"id": "ptt", "name": "PTT", "section": "social", "tier": "T4", "method": "rss", "url": "https://ptt.cc",
         "lang": "zh-Hant", "enabled": False, "notes": "停用"},
    ],
)


def _add(session, source_id, title, *, section, hours_ago=3):
    url = f"https://{source_id.replace('_', '')}.com/{hashlib.sha1(title.encode()).hexdigest()[:8]}"
    session.add(SourceItem(
        source_id=source_id, section=section, tier="T2", item_key=hashlib.sha1(url.encode()).hexdigest(),
        url=url, canonical_url=url, title=title, summary=title, lang="zh-Hant",
        published_at=NOW - timedelta(hours=hours_ago), first_seen_at=NOW - timedelta(hours=hours_ago),
    ))


def _pair(session, section, title_a, title_b):
    """同一事件兩家媒體（寫法不同、不算轉載），聚合成一個 report 事件。"""
    _add(session, f"{section}-1", title_a, section=section)
    _add(session, f"{section}-2", title_b, section=section)


class RecordingWriter:
    name = "codex"

    def __init__(self):
        self.requests = 0
        self.labels = []
        self.story_count = 0

    def find_same_events(self, candidates):
        self.requests += 1
        return []

    def write(self, label, stories):
        self.requests += 1
        self.labels.append(label)
        self.story_count += len(stories)
        return {k: WrittenStory(f"{label}稿{k}", "重點", "據報導，測試正文。" * 10, "", "codex") for k, _, _ in stories}


@pytest.fixture()
def env(session, monkeypatch, tmp_path):
    _pair(session, "cross_strait", "洪秀柱赴中稱台灣少數人認賊作父 陸委會回應", "陸委會批洪秀柱貶低台灣 「認賊作父」說惹議")
    _pair(session, "cross_strait", "北韓金正恩訪問中國丹東 鴨綠江新橋開通", "金正恩跨越鴨綠江新橋 突訪丹東")
    _pair(session, "finance", "台股收盤大漲 台積電股價創新高", "台積電領軍衝新高 台股終場大漲逾300點")
    _pair(session, "finance", "微軟推六萬名員工自願優離方案 加碼人工智慧", "微軟六萬人優離 人工智慧支出創新高")
    _pair(session, "life_env", "教育部：台灣高等研究學院無延宕 提前啟動試辦", "台灣高等研究學院籌設 教育部宣布試辦招生")
    _pair(session, "sports", "中華隊世界盃棒球奪冠 全隊今晚返國", "世界盃棒球冠軍中華隊 球迷機場接機")
    session.flush()
    cluster_recent_items(session, now=NOW, disabled_sources=REGISTRY.disabled_source_ids())
    session.commit()

    @contextmanager
    def scope():
        yield session
        session.commit()

    writer = RecordingWriter()
    settings = SimpleNamespace(
        daily_writer="codex", codex_bin="/bin/sh", gemini_api_key="x", news_sources_path="unused",
        daily_site_dir=str(tmp_path), newsroom_delivery_timezone="Asia/Taipei",
    )
    monkeypatch.setattr(run_module, "session_scope", scope)
    monkeypatch.setattr(run_module, "get_settings", lambda: settings)
    monkeypatch.setattr(run_module, "load_registry", lambda path: REGISTRY)
    monkeypatch.setattr(run_module, "fetch_market_box", lambda: None)
    monkeypatch.setattr(run_module, "DailyWriter", lambda name: writer)
    return SimpleNamespace(session=session, writer=writer, tmp_path=tmp_path)


def test_without_rewrite_cross_strait_and_finance_would_vanish(env):
    """只改配額不改分版：兩岸、財經事件都不在三個內版，整篇消失（手冊步驟 4 的警告）。"""
    from reddit_tracker.daily.scoring import score_candidates

    scored = score_candidates(env.session, edition_date=EDITION, now=NOW)
    assert {s.section for s in scored} >= {"cross_strait", "finance"}
    assert {s.section for s in select_articles(scored)} <= {"world"}  # 只剩什麼都不是的

    rewritten = rewrite_sections(env.session, scored, registry=REGISTRY)
    assert not {s.section for s in rewritten} & {"cross_strait", "finance"}
    moved = [s for s in rewritten if "original_section" in s.signals]
    assert {s.signals["original_section"] for s in moved} == {"cross_strait", "finance", "life_env"}
    assert all(s.signals["section_rule"] for s in moved)
    assert [s.section for s in rewritten if s.signals.get("original_section") is None] == ["sports"]


def test_prepare_puts_cross_strait_and_finance_into_inner_sections_and_briefs_skip_llm(env):
    edition = env.session.get(DailyEdition, run_module.prepare_daily(EDITION, now=NOW))
    placed = {a.headline: (a.section, (a.signals or {}).get("original_section")) for a in edition.articles}
    origins = {(section, origin) for section, origin in placed.values()}
    assert ("taiwan", "cross_strait") in origins  # 洪秀柱
    assert ("world", "cross_strait") in origins  # 金正恩
    assert ("taiwan", "finance") in origins  # 台股
    assert ("tech", "finance") in origins  # 微軟
    assert ("taiwan", "life_env") in origins  # 教育部（E14）
    assert {a.section for a in edition.articles} <= {"taiwan", "world", "tech"}
    # 頭版從正式稿裡標記：report 都上頭版（不足 6 則），single_source 不上頭版
    assert {a.id for a in edition.articles if a.is_front} == {a.id for a in edition.articles if a.kind == "report"}

    briefs = edition.stats["briefs"]
    assert [(b["section"], b["headline"]) for b in briefs] == [("sports", briefs[0]["headline"])]
    assert "中華隊" in briefs[0]["headline"] and briefs[0]["url"].startswith("https://sports-")
    # 短訊不呼叫 LLM：writer 只寫了正式稿（編輯會議＋頭版＋內版），沒有體育版的請求
    assert "體育" not in env.writer.labels and env.writer.story_count == len(edition.articles)
    assert edition.stats["llm_requests"] == 1 + len(env.writer.labels)
    html = (env.tmp_path / "2026-10-28.html").read_text(encoding="utf-8")
    front = html.split('id="front"')[1].split('id="taiwan"')[0]
    assert "短訊" in front and briefs[0]["headline"] in front
    sports = html.split('id="sports"')[1]
    assert "本版未開放" in sports.split("</div>")[0]


def test_select_never_exceeds_twelve_or_writes_front_twice():
    scored = [ScoredCluster(i, section, "report", 1000 - i) for i, section in enumerate(["taiwan", "world", "tech"] * 10)]
    selections = select_articles(scored)
    assert len(selections) == 12 and sum(s.is_front for s in selections) == 6
    assert len({s.cluster.cluster_id for s in selections}) == 12
