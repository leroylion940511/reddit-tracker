"""彙整稿不併入單一事件（佇列第 12 項 (1)，`CLUSTER_ISOLATE_ROUNDUPS`，預設關閉；不呼叫 LLM）。

fixture `roundup_1030.json`：2026-10-30 黃仁勳間諜案的中文事件（37 篇，含風傳媒〈10/30國際早報〉）與英文事件
（標題、摘要前 300 字），取自 production 複本；中文事件的成員＝關閉時離線重跑實驗一方法 C 的結果。
`background` 是同兩天的其他中文標題，只用來讓 TF-IDF 的字頻接近真實（沒有它，間諜案的字每篇都有、權重太低）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from reddit_tracker.collection.clustering import cluster_recent_items
from reddit_tracker.collection.entities import MergeRules, is_roundup_title, load_lexicon
from reddit_tracker.config import Settings
from reddit_tracker.daily.desk import desk_merges
from reddit_tracker.daily.scoring import ScoredCluster
from reddit_tracker.models import SourceItem, StoryCluster

FIXTURE = Path(__file__).parent / "regression" / "fixtures" / "roundup_1030.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
EVENT, BACKGROUND = DATA["event"], DATA["background"]
NOW = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)
ROUNDUP, CNA, HKFP = 27811, 27465, 34624  # T457＝27811×27465、T523＝27811×34624
OFF, ON = MergeRules(), MergeRules(isolate_roundups=True)


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.fixture()
def spy_db(session):
    for row in EVENT:
        session.add(SourceItem(
            **{k: v for k, v in row.items() if not k.endswith("_at")}, item_key=str(row["id"]),
            published_at=_dt(row["published_at"]), first_seen_at=_dt(row["first_seen_at"]),
        ))
    for row in BACKGROUND:
        url = f"https://example.com/{row['id']}"
        session.add(SourceItem(
            id=row["id"], source_id="cna-headlines", section="taiwan", tier="T1", item_key=str(row["id"]), url=url,
            canonical_url=url, title=row["title"], lang=row["lang"], published_at=_dt(row["published_at"]),
            first_seen_at=_dt(row["published_at"]),
        ))
    session.flush()
    return session


def _cluster_ids(session) -> dict[int, int]:
    return dict(session.execute(select(SourceItem.id, SourceItem.cluster_id)).all())


def _scored(cluster_id: int) -> ScoredCluster:
    return ScoredCluster(cluster_id, "world", "report", 1.0)


@pytest.mark.parametrize("title", [
    "10/30國際早報｜川普早知黃仁勳身邊有中國情報資產、美日在日本合產AMRAAM飛彈、Alphabet單日暴跌12.6%",
    "10/30国际晚报｜川普",
    "早安世界》黃仁勳辭輝達執行長 財務長克瑞斯任臨時CEO",
    "晚間影音新聞／美俄烏三方會談阿布達比登場｜彰化選舉拚政見戰",
    "今晨國際頭條／AI燒錢投資人嚇壞！　美科技股遭血洗那指慘崩跌",
    "11/01各報重點新聞一覽",
    "【資安日報】10月28日，Google Brotli漏洞恐造成資訊洩漏",
    "一週大事／普發2萬三讀通過 美中俄元首會晤（2026.11.16-11.22）",
    "美國期中選舉民主黨奪回參眾兩院、黃之鋒再判囚10年 一週大事彙整",
    "The Download: Anthropic’s IPO, smarter power grids, and exercise pills",
    "10/30: CBS Evening News",
    "Thursday briefing: What we do (and don’t) know about Alice Huang and the Nvidia affair",
    "NFL roundup: Seahawks overwhelm Chiefs to end KC’s unbeaten run",
    "‘3 Body Problem’ Sets Season 2 Release Date at Netflix (TV News Roundup)",
])
def test_roundup_titles(title):
    assert is_roundup_title(title)


@pytest.mark.parametrize("title", [
    None, "",
    "馬斯克上榜！隨川普深圳APEC行 南華早報：黃仁勳有變數",
    "沈伯洋若當選......《南華早報》聚焦雙城論壇與兩岸難題",
    "華爾街日報：黃仁勳涉兩起婚外情 輝達董事會擬撤換",
    "東北季風明天下午報到迎風面變天！下一波更強 下探17度",
    # 懶人包、一次看多半是單一事件的整理，併進該事件是對的
    "懶人包》產假延長到14周 育兒留停放寬到孩子滿9歲 育兒福利新制一次看",
    "金馬獎5大亮點一次看 李安奉俊昊攜手頒獎、怪物新人吸睛",
    "美國期中選舉前一週 聯邦選委會網站遭駭系統中斷",
    "Roundup settlement expected before Christmas, Bayer CEO says",
    "Bayer wins Roundup cancer trial after Supreme Court ruling",
    "Pete Hegseth to hold news briefing as he faces possible impeachment – US politics live",
    "Military briefing: what would another US-Iran conflict look like?",
    "Nvidia stock slips as investors digest CEO exit, broader chip sector falls",
])
def test_single_event_titles_are_not_roundups(title):
    assert not is_roundup_title(title)


def test_flag_is_off_by_default_and_comes_from_settings():
    assert MergeRules().isolate_roundups is False
    assert MergeRules.from_settings(Settings(_env_file=None)) == MergeRules()
    assert MergeRules.from_settings(Settings(_env_file=None, cluster_isolate_roundups=True)) == ON


def test_t457_roundup_joins_the_spy_event_only_when_off(spy_db):
    cluster_recent_items(spy_db, now=NOW, rules=OFF)
    assert _cluster_ids(spy_db)[ROUNDUP] == _cluster_ids(spy_db)[CNA]


def test_t457_roundup_stands_alone_when_on(spy_db):
    stats = cluster_recent_items(spy_db, now=NOW, rules=ON)
    ids = _cluster_ids(spy_db)
    assert stats.isolated_roundups == sum(is_roundup_title(r["title"]) for r in EVENT + BACKGROUND) == 2
    assert [i for i, c in ids.items() if c == ids[ROUNDUP]] == [ROUNDUP]


def test_other_members_stay_together_when_on(spy_db):
    with spy_db.begin_nested() as savepoint:
        cluster_recent_items(spy_db, now=NOW, rules=OFF)
        off = _cluster_ids(spy_db)
        savepoint.rollback()
    spy_db.expire_all()
    cluster_recent_items(spy_db, now=NOW, rules=ON)
    on = _cluster_ids(spy_db)

    def groups(ids):
        out: dict[int, set[int]] = {}
        for item_id, cluster_id in ids.items():
            if item_id != ROUNDUP:
                out.setdefault(cluster_id, set()).add(item_id)
        return {frozenset(g) for g in out.values()}

    assert groups(off) == groups(on)


def test_roundup_already_inside_an_event_no_longer_bridges(spy_db):
    """打開之前併進去的彙整稿留在原事件（歸屬不改），但新素材不能再靠它併入。"""
    roundup = spy_db.get(SourceItem, ROUNDUP)
    cluster = StoryCluster(
        lang_group="zh", section="world", title="舊事件", first_published_at=roundup.published_at,
        last_published_at=roundup.published_at, created_at=NOW, updated_at=NOW,
    )
    spy_db.add(cluster)
    spy_db.flush()
    roundup.cluster_id = cluster.id
    cluster_recent_items(spy_db, now=NOW, rules=ON)
    ids = _cluster_ids(spy_db)
    assert ids[ROUNDUP] == cluster.id
    assert [i for i, c in ids.items() if c == cluster.id] == [ROUNDUP]


def test_t523_desk_does_not_use_the_roundup_cluster(spy_db):
    """LLM 說早報和英文事件是同一件事：關閉時共有黃仁勳就放行；打開時整組剔除、留下紀錄。"""
    cluster_recent_items(spy_db, now=NOW, rules=ON)
    ids = _cluster_ids(spy_db)
    alone, english = ids[ROUNDUP], ids[HKFP]
    pool = [_scored(alone), _scored(english)]
    off = desk_merges(spy_db, pool, [[alone, english]], lexicon=load_lexicon(), rules=OFF)
    on = desk_merges(spy_db, pool, [[alone, english]], lexicon=load_lexicon(), rules=ON)
    assert [sorted(g) for g in off.groups] == [sorted([alone, english])]
    assert on.groups == [] and on.llm_groups == [[alone, english]]
    assert [(r["cluster_id"], "彙整稿" in r["reason"]) for r in on.rejected] == [(alone, True)]


def test_desk_still_confirms_the_rest_of_the_group(spy_db):
    cluster_recent_items(spy_db, now=NOW, rules=ON)
    ids = _cluster_ids(spy_db)
    alone, chinese, english = ids[ROUNDUP], ids[CNA], ids[HKFP]
    on = desk_merges(
        spy_db, [], [[alone, chinese, english]], lexicon=load_lexicon(),
        rules=replace(ON, cross_lang_min_entities=99),
    )
    assert [sorted(g) for g in on.groups] == [sorted([chinese, english])]
    assert [r["cluster_id"] for r in on.rejected] == [alone]
