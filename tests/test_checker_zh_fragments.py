"""佇列第 12 項 (2)：查核員程式點名承認當天少見的中文片段（`FACT_CHECKER_ZH_FRAGMENTS`，預設關閉）。

規則：與 S1 共有、當天少見（`EntityContext.is_rare`）的中文三字片段，合併後至少兩段互不相連才不點名。
真實數字（`rt-data-1123` 複本，`scripts/eval_checker_fragments.py`）：N-44224「蘇巧慧、李四川」、
N-54434「肯德基必勝客…、年底前」不再點名；11/01 5330 的高雄辯論只共有「市長選戰」一段，照樣點名。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from reddit_tracker.collection.entities import EntityContext, load_lexicon, rare_shared_fragments
from reddit_tracker.config import get_settings
from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.daily.mas import orchestrator
from reddit_tracker.daily.mas.orchestrator import CHECKER_MIN_ZH_FRAGMENTS, irrelevant_sources
from tests.test_daily import daily_env  # noqa: F401
from tests.test_factcheck_relevance import RECORDS, Replay, _evidence, _review


def _item(title: str, n: int = 0) -> EvidenceItem:
    return EvidenceItem(outlet=f"o{n}", source_id=f"s{n}", source_name=f"來源{n}", tier="T2", lang="zh-Hant",
                        title=title, summary="", url=f"https://example.com/{n}", published_at="", item_id=1000 + n)


def _context(titles: list[str]) -> EntityContext:
    lexicon = load_lexicon()
    return EntityContext(lexicon.entities(title, True) for title in titles)


def _flagged(items, context=None) -> set[int]:
    return {index for index, _ in irrelevant_sources(items, context)}


# N-44224（11/10）：央廣與自由時報同一則民調，沒有共同的譯名或數字
POLL = [_item("新北市長民調 蘇巧慧落後李四川3個百分點", 1),
        _item("聯合報民調領先李四川3％ 蘇巧慧拋願景：900天耕耘獲認同", 2)]
# 11/01 5330 的 S1、S3：台北、高雄兩場辯論只共有「市長選戰」
DEBATES = [_item("台北市長選戰首場辯論12:00登場  蔣萬安、沈伯洋正面攻防", 1),
           _item("高雄市長選戰辯論會週五登場 申論、提問及交叉詰問1.5小時", 3)]


def test_without_day_context_nothing_changes():
    assert _flagged(POLL) == {2}
    for story_id in RECORDS:
        evidence = _evidence(story_id)
        assert irrelevant_sources(evidence, None) == irrelevant_sources(evidence)


def test_two_rare_fragments_clear_the_source():
    context = _context([item.title for item in POLL])
    lexicon = load_lexicon()
    a, b = (lexicon.entities(item.title, True) for item in POLL)
    assert sorted(rare_shared_fragments(a, b, context)) == ["李四川", "蘇巧慧"]
    assert _flagged(POLL, context) == set()


def test_one_shared_phrase_is_not_enough():
    assert CHECKER_MIN_ZH_FRAGMENTS == 2
    context = _context([item.title for item in DEBATES])
    lexicon = load_lexicon()
    a, b = (lexicon.entities(item.title, True) for item in DEBATES)
    assert rare_shared_fragments(a, b, context) == ["市長選戰"]
    assert _flagged(DEBATES, context) == {2}


def test_common_fragments_do_not_count():
    # 當天 ≥ 5% 的標題都有「李四川」：只剩「蘇巧慧」一段，照樣點名
    filler = [f"李四川第{i}天行程" for i in range(40)] + [f"無關新聞第{i}則" for i in range(200)]
    context = _context([item.title for item in POLL] + filler)
    assert not context.is_rare("李四川") and context.is_rare("蘇巧慧")
    assert _flagged(POLL, context) == {2}


def test_fixture_cases_with_their_own_titles_as_the_day():
    # 10/31、11/01 真實證據包；當天統計只拿這幾篇標題（每個片段都算少見），只看「幾段」的規則
    def flagged(story_id):
        evidence = _evidence(story_id)
        return _flagged(evidence, _context([item.title for item in evidence]))

    assert 3 in flagged(5330)  # 高雄辯論仍點名
    assert 2 in flagged(5455)  # Amazon 財報稿裡的 Microsoft 財報（英文，不受影響）
    assert flagged(5327) == set()  # 同一場台北辯論：沈伯洋、蔣萬安、…電視辯論
    assert flagged(14) == set()  # 毒駕修法：立院三讀、累犯致死、可判死
    for story_id in RECORDS:  # 只會少點名、不會多點名
        evidence = _evidence(story_id)
        assert flagged(story_id) <= _flagged(evidence)


def test_review_skips_the_checker_call_when_nothing_is_flagged(session):
    # 5327：關閉時程式點名 S2、要問查核員；打開後不點名，不問查核員、來源全留
    evidence = _evidence(5327)
    context = _context([item.title for item in evidence])
    client = Replay(RECORDS[5327])
    version, messages = _review(session, 5327, client, day_context=context)
    assert client.calls == ["reporter"]
    assert version.status == "checked" and version.source_ids == RECORDS[5327]["v1"]["source_ids"]
    assert not [m for m in messages if m.type == "CHALLENGE"]


def test_review_still_challenges_the_kaohsiung_debate(session):
    evidence = _evidence(5330)
    context = _context([item.title for item in evidence])
    version, messages = _review(session, 5330, Replay(RECORDS[5330]), day_context=context)
    challenge = next(m for m in messages if m.type == "CHALLENGE")
    assert 3 in challenge.payload["drop_sids"]


@pytest.mark.parametrize("flag", [False, True])
def test_run_mas_passes_the_day_context_only_when_the_flag_is_on(session, monkeypatch, flag):
    from tests.test_mas_steps import DAY, NOW, SECTIONS, Scripted, _checker, _registry, _snapshot
    from tests.test_mas_steps import _item as mas_item

    monkeypatch.setenv("FACT_CHECKER_ZH_FRAGMENTS", "true" if flag else "false")
    get_settings.cache_clear()
    sentinel = EntityContext([])
    monkeypatch.setattr(orchestrator, "title_context", lambda *a, **k: sentinel)
    seen = []
    real = orchestrator.irrelevant_sources

    def spy(evidence, day_context=None):
        seen.append(day_context)
        return real(evidence, day_context)

    monkeypatch.setattr(orchestrator, "irrelevant_sources", spy)
    raw = []
    for i, section in enumerate(SECTIONS):
        item = mas_item(session, f"武契奇事件{i}", "國會選舉結果", url=f"https://www.cna.com.tw/{i}")
        raw.append(_snapshot([item.id], i, section=section, score=100 - i))

    def handler(kw):
        content = kw["messages"][0]["content"]
        data = json.loads(content) if content.startswith("{") else None
        if "分版主編" in kw["system"]:
            return json.dumps({"pitches": [{"story_id": p["story_id"], "angle": "國會", "priority": "front"}
                                           for p in data["candidates"]]})
        if "總編輯" in kw["system"] and data and "candidates" in data:
            ids = [c["story_id"] for c in data["candidates"]][:6]
            return json.dumps({"lead": ids[0], "second": ids[1:5], "briefs": ids[5:], "links": [],
                               "dropped": [], "reasons": [{"story_id": i, "why": "重要"} for i in ids]})
        if "記者" in kw["system"]:
            return json.dumps({"action": "DRAFT", "headline": "武契奇選舉", "body": "國會選舉結果。[S1]"})
        return _checker("OK", "")

    orchestrator.run_mas(session, edition_date=DAY, snapshot=SimpleNamespace(candidates=raw), registry=_registry(),
                         client=Scripted(handler), now=NOW)
    get_settings.cache_clear()
    assert seen and all(ctx is (sentinel if flag else None) for ctx in seen)
