"""共同實體、兩段門檻、譯名表、編輯會議跨語言合併（手冊步驟 3 第 1–4 點）。"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from reddit_tracker.collection.clustering import cluster_recent_items
from reddit_tracker.collection.entities import (
    DEFAULT_COMMON_WORDS_PATH,
    DEFAULT_GLOSSARY_PATH,
    EntityContext,
    EntityLexicon,
    GlossaryEntry,
    MergeRules,
    fold,
    load_common_words,
    load_glossary,
    load_lexicon,
)
from reddit_tracker.config import Settings
from reddit_tracker.daily.desk import desk_merges
from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.daily.scoring import ScoredCluster, apply_merges
from reddit_tracker.daily.writer import DailyWriter
from reddit_tracker.models import SourceItem

NOW = datetime(2026, 10, 27, 2, 0, tzinfo=timezone.utc)
SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "snapshots" / "2026-10-27.db"
# 實驗一防偷看：譯名表只收 10/30（含，台北時間）以前出現過的名字
GLOSSARY_CUTOFF_UTC = "2026-10-30 16:00:00"
LEX = load_lexicon(DEFAULT_GLOSSARY_PATH, DEFAULT_COMMON_WORDS_PATH)


def shared(a: str, b: str, *, a_zh=False, b_zh=False, context=None) -> set[str]:
    ea, eb = LEX.entities(a, a_zh), LEX.entities(b, b_zh)
    return LEX.shared(ea, eb, context if context is not None else EntityContext([ea, eb]))


# ── 譯名表與常見字清單 ─────────────────────────────────────────────────────


def test_glossary_has_30_to_50_unique_entries():
    glossary = load_glossary()
    assert 30 <= len(glossary) <= 50
    assert len({e.zh for e in glossary}) == len(glossary)
    assert all(e.en for e in glossary), "每個名字都要有英文寫法，跨語言合併才用得到"
    EntityLexicon(glossary, [])  # 同一寫法不得對到兩個譯名（重複會丟 ValueError）


def test_glossary_rejects_conflicting_variants():
    with pytest.raises(ValueError, match="重複"):
        EntityLexicon([GlossaryEntry(en=["Lula"], zh="魯拉"), GlossaryEntry(en=["lula"], zh="盧拉")], [])


def test_handbook_examples_in_glossary():
    names = {e.zh: e for e in load_glossary()}
    assert {"Lula", "Luiz Inácio Lula da Silva"} <= set(names["魯拉"].en)
    assert {"露拉", "盧拉"} <= set(names["魯拉"].also)
    assert "弗拉維奧" in names["佛拉維歐"].also
    assert {"Vučić", "Vucic", "Aleksandar Vučić"} <= set(names["武契奇"].en)


def test_common_words_include_handbook_examples():
    words = set(load_common_words())
    assert {"block", "apple", "new"} <= words


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="本機沒有唯讀母本")
def test_glossary_names_seen_before_cutoff():
    """每個譯名（任一中英文寫法）都在 10/30 以前的素材標題出現過（手冊 8.1 第 3 點）。"""
    con = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro&immutable=1", uri=True)
    try:
        titles = [fold(t).lower() for (t,) in con.execute(
            "select title from source_items where first_seen_at < ? and title is not null", (GLOSSARY_CUTOFF_UTC,)
        )]
    finally:
        con.close()
    unseen = [
        e.zh for e in load_glossary()
        if not any(fold(v).lower() in t for v in [*e.en, e.zh, *e.also] for t in titles)
    ]
    assert not unseen


# ── 實體抽取 ───────────────────────────────────────────────────────────────


def test_glossary_normalizes_names_to_chinese():
    assert LEX.glossary_names("Lula wins Brazil runoff after prediction markets favored Bolsonaro") == ["魯拉", "巴西", "波索納洛"]
    assert LEX.glossary_names("巴西總統露拉連任") == ["巴西", "魯拉"]
    assert LEX.glossary_names("Serbia's ex-president Vučić concedes") == ["塞爾維亞", "武契奇"]
    assert LEX.glossary_names("塞尔维亚总统武契奇承认败选") == ["塞爾維亞", "武契奇"]  # 簡體先轉繁體
    assert LEX.glossary_names("小波索納洛不認敗選") == ["佛拉維歐"]  # 最長的寫法優先
    assert LEX.glossary_names("Xinjiang") == []  # 英文名字要整個字符合


def test_handbook_example_serbia_vs_seahawks_has_no_shared_entity():
    assert shared("Serbia election: Vucic concedes defeat", "Jaxon Smith-Njigba has big night in Seahawks' 20-3 win over Chiefs") == set()
    assert shared("Jaxon Smith-Njigba has big night in Seahawks’ 20-3 win over Chiefs",
                  "武契奇承認敗選　塞爾維亞學生運動贏得議會選舉", b_zh=True) == set()


def test_cross_language_names_match_after_glossary():
    assert shared("Lula wins Brazil runoff after prediction markets favored Bolsonaro",
                  "巴西總統大選 魯拉逆轉勝連任", b_zh=True) == {"魯拉", "巴西"}


def test_sentence_first_and_common_words_are_not_entities():
    # E03：句首的 Block、Switzerland 不算，Block 也在常見字清單
    assert LEX.entities("Block’s new voice model sounds eerily human", False).names == frozenset()
    assert shared("Block’s new voice model sounds eerily human", "Switzerland. Block by block. At 1:1 scale") == set()
    # 句中的大寫字算；常見字（Apple、New）不算
    assert LEX.entities("Report: shares of Skydance and Apple fall in New York", False).names == {"skydance", "york"}


def test_title_case_titles_only_count_glossary_names():
    title = "Skydance Is Offering Employees Voluntary Buyouts Ahead of Layoffs, Adopts In-Office Policy"
    assert LEX.entities(title, False).names == frozenset()
    assert LEX.entities("Brazilian Markets Convulse After Lula Win", False).names == {"巴西", "魯拉"}
    # iPhone 這種開頭小寫的字也算 Title Case 的大寫字
    assert LEX.entities("Apple’s Foldable iPhone Duo Draws Early Complaints", False).names == frozenset()


def test_mixed_case_words_are_names_even_at_sentence_start():
    assert LEX.entities("iPhone Duo owners report cracks", False).names == {"iphone", "duo"}


def test_sentence_first_word_counts_when_corroborated_by_the_day():
    a = LEX.entities("Anthropic files for IPO as it competes for AI dominance", False)
    b = LEX.entities("AI giant Anthropic files for an IPO that could break records", False)
    assert "anthropic" not in a.names and "anthropic" in a.leads
    assert LEX.shared(a, b, EntityContext([a, b])) == {"anthropic"}
    # 當天也以小寫出現的字（一般英文字）不因句首而成立
    c = LEX.entities("Watch this space", False)
    d = LEX.entities("Fans watch as Watch maker fails", False)
    assert LEX.shared(c, d, EntityContext([c, d])) == set()


def test_numbers_keep_three_digits_but_not_years():
    assert LEX.entities("Microsoft offers buyouts to 60,000 employees in 2026", False).names == {"微軟", "60000"}
    assert LEX.entities("馬斯克喊 SpaceX 籌得 400 億美元", True).names == {"馬斯克", "spacex", "400"}


def test_html_entities_are_unescaped():
    assert LEX.entities("Apple acknowledges iPhone Duo display &#8216;issue&#8217;", False).names == {"iphone", "duo"}


def test_chinese_rare_fragments_count_as_entities():
    a = "蘇清泉稱沒小孩不知養兒苦 周春米：應鄭重向社會大眾道歉"
    b = "[政治] 屏東縣長選戰／稱周春米沒小孩不知養兒苦 蘇清泉臉書發文致歉"
    assert shared(a, b, a_zh=True, b_zh=True) == {"「蘇清泉」", "「沒小孩不知養兒苦」", "「周春米」"}
    # 不在譯名表的名字（洪秀柱以外的例子）也靠片段認出來；但 3 字以下的片段不算
    assert shared("蕭美琴讚沈伯洋", "沈伯洋女力後援會", a_zh=True, b_zh=True) == {"「沈伯洋」"}
    assert shared("學運勝選", "學運落敗", a_zh=True, b_zh=True) == set()


def test_common_chinese_fragments_are_not_entities():
    """出現在 5% 以上當天素材的片段不算（例如每篇都有的「選戰」樣板）。"""
    a = LEX.entities("縣長選戰升溫 甲候選人拜票", True)
    b = LEX.entities("縣長選戰升溫 乙候選人掃街", True)
    filler = [LEX.entities(f"縣長選戰升溫 第{i}則", True) for i in range(10)]
    filler += [LEX.entities(f"無關新聞{i}", True) for i in range(200)]
    assert LEX.shared(a, b, EntityContext([a, b, *filler])) == {"「候選人」"}
    assert LEX.shared(a, b, EntityContext([a, b])) == {"「縣長選戰升溫」", "「候選人」"}


# ── 兩段門檻 ───────────────────────────────────────────────────────────────


def test_merge_rules_two_band_thresholds():
    rules = MergeRules()
    assert rules.required_entities(0.60) == 1
    assert rules.required_entities(0.45) == 1
    assert rules.required_entities(0.44) == 2
    assert rules.required_entities(0.28) == 2
    assert rules.required_entities(0.27) is None


def test_merge_rules_come_from_settings(monkeypatch):
    monkeypatch.setenv("CLUSTER_HIGH_THRESHOLD", "0.5")
    monkeypatch.setenv("CLUSTER_MID_MIN_ENTITIES", "3")
    rules = MergeRules.from_settings(Settings(_env_file=None))
    assert (rules.high_threshold, rules.low_threshold, rules.mid_min_entities) == (0.5, 0.28, 3)
    defaults = MergeRules.from_settings(Settings(_env_file=None, cluster_high_threshold=0.45, cluster_mid_min_entities=2))
    assert defaults == MergeRules()


def _item(session, source_id, title, *, lang="en", summary="", hours_ago=1, section="tech"):
    item = SourceItem(
        source_id=source_id, section=section, tier="T2",
        item_key=hashlib.sha1(f"{source_id}{title}".encode()).hexdigest(),
        url=f"https://{source_id}.example/{abs(hash(title))}", canonical_url=f"https://{source_id}.example/{abs(hash(title))}",
        title=title, summary=summary, lang=lang,
        published_at=NOW - timedelta(hours=hours_ago), first_seen_at=NOW,
    )
    session.add(item)
    session.flush()
    return item


def test_similar_titles_without_shared_entity_are_not_merged(session):
    """E04：都有 buyouts，但 Microsoft 與 Skydance 是兩件事。"""
    ms1 = _item(session, "cnbc", "Microsoft offers voluntary buyouts to 60,000 employees", hours_ago=3)
    ms2 = _item(session, "verge", "Microsoft offers buyouts to 60,000 employees", hours_ago=2)
    sky = _item(session, "reuters", "Skydance offers buyouts to some employees to cut costs", hours_ago=1)
    for i in range(30):  # 讓 IDF 有意義
        _item(session, f"filler{i}", f"Unrelated filler headline number {i} about weather", hours_ago=4)
    stats = cluster_recent_items(session, now=NOW, lexicon=LEX)
    assert ms1.cluster_id == ms2.cluster_id
    assert sky.cluster_id != ms1.cluster_id
    assert stats.rejected_no_entity >= 1


def test_mid_band_needs_two_shared_entities(session):
    rules = MergeRules(high_threshold=0.99, low_threshold=0.1)  # 讓所有配對落在中段
    a = _item(session, "cna", "塞爾維亞總統武契奇承認敗選", lang="zh-Hant", hours_ago=3, section="world")
    b = _item(session, "ltn", "武契奇認輸 塞爾維亞變天", lang="zh-Hant", hours_ago=2, section="world")
    c = _item(session, "pts", "塞爾維亞學運勝選", lang="zh-Hant", hours_ago=1, section="world")
    cluster_recent_items(session, now=NOW, rules=rules, lexicon=LEX)
    assert a.cluster_id == b.cluster_id  # 武契奇＋塞爾維亞
    assert c.cluster_id != a.cluster_id  # 只有塞爾維亞


def test_below_low_threshold_never_merges(session):
    rules = MergeRules(high_threshold=1.01, low_threshold=1.0)
    a = _item(session, "cna", "塞爾維亞總統武契奇承認敗選", lang="zh-Hant", hours_ago=3, section="world")
    b = _item(session, "ltn", "塞爾維亞總統武契奇承認敗選了", lang="zh-Hant", hours_ago=2, section="world")
    cluster_recent_items(session, now=NOW, rules=rules, lexicon=LEX)
    assert a.cluster_id != b.cluster_id


# ── 編輯會議：跨語言合併與 LLM 第二意見 ────────────────────────────────────


def _clustered(session, titles_by_lang):
    items = [_item(session, f"src{i}", t, lang=lang, hours_ago=1 + i * 0.1, section="world")
             for i, (lang, t) in enumerate(titles_by_lang)]
    cluster_recent_items(session, now=NOW, lexicon=LEX)
    return [i.cluster_id for i in items]


def test_desk_merges_cross_language_by_glossary_entities(session):
    en, zh, nfl = _clustered(session, [
        ("en", "Lula wins Brazil runoff after prediction markets favored Bolsonaro"),
        ("zh-Hant", "巴西總統大選 魯拉逆轉勝連任"),
        ("en", "Jaxon Smith-Njigba has big night in Seahawks’ 20-3 win over Chiefs"),
    ])
    pool = [ScoredCluster(c, "world", "report", 10.0 - k) for k, c in enumerate((en, zh, nfl))]
    desk = desk_merges(session, pool, None, lexicon=LEX, rules=MergeRules())
    assert desk.entity_groups == [[en, zh]]
    assert desk.groups == [[en, zh]]


def test_desk_cross_language_needs_two_entities(session):
    en, zh = _clustered(session, [
        ("en", "What the vote means for Serbia’s foreign policy"),
        ("zh-Hant", "塞爾維亞學運開花結果 國會大選席次過半"),
    ])
    pool = [ScoredCluster(en, "world", "report", 2.0), ScoredCluster(zh, "world", "report", 1.0)]
    assert desk_merges(session, pool, None, lexicon=LEX, rules=MergeRules()).groups == []


def test_desk_rejects_llm_merge_without_shared_entity(session):
    """E01：LLM 說 NFL 稿與塞爾維亞是同一事件，程式找不到共同實體就剔除。"""
    serbia_en, serbia_zh, nfl = _clustered(session, [
        ("en", "Serbia election: Vucic concedes defeat to student-led movement"),
        ("zh-Hant", "武契奇承認敗選　塞爾維亞學生運動贏得議會選舉"),
        ("en", "Jaxon Smith-Njigba has big night in Seahawks’ 20-3 win over Chiefs"),
    ])
    pool = [ScoredCluster(c, "world", "report", 10.0 - k) for k, c in enumerate((serbia_en, serbia_zh, nfl))]
    desk = desk_merges(session, pool, [[nfl, serbia_zh]], lexicon=LEX, rules=MergeRules())
    assert desk.groups == [[serbia_en, serbia_zh]]  # 只剩程式自己的跨語言合併
    assert {r["cluster_id"] for r in desk.rejected} == {nfl, serbia_zh}
    assert all(r["reason"].startswith("無共同實體") for r in desk.rejected)
    assert desk.llm_groups == [[nfl, serbia_zh]]


def test_desk_keeps_llm_merge_with_shared_entity(session):
    a, b = _clustered(session, [
        ("en", "Report: Anthropic files for IPO"),
        ("en", "Shares of Anthropic jump in debut plans"),
    ])
    pool = [ScoredCluster(a, "tech", "report", 2.0), ScoredCluster(b, "tech", "report", 1.0)]
    desk = desk_merges(session, pool, [[a, b]], lexicon=LEX, rules=MergeRules())
    assert desk.groups == [[a, b]] and desk.rejected == []


def test_apply_merges_carries_chained_groups():
    """重疊的合併組（A＋B、A＋C，且 C 分數最高）不能遺失先前併入的事件。"""
    scored = [ScoredCluster(1, "world", "report", 5.0), ScoredCluster(2, "world", "single_source", 3.0),
              ScoredCluster(3, "world", "report", 9.0)]
    merged = apply_merges(scored, [[1, 2], [1, 3]])
    assert [s.cluster_id for s in merged] == [3]
    assert sorted(merged[0].all_ids) == [1, 2, 3]
    assert sorted(merged[0].signals["merged_cluster_ids"]) == [1, 2]


# ── 撰稿共用譯名表 ─────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self):
        self.prompts = []

    def complete(self, *, system, messages, max_output_tokens, temperature, json_mode=False, json_schema=None):
        self.prompts.append(messages[0]["content"])
        return type("R", (), {"content": '{"stories": []}'})()


def _evidence(title, summary=""):
    return EvidenceItem("x", "src", "來源", "T2", "en", title, summary, "https://x", "2026-10-27T06:00+08:00")


def test_writer_prompt_lists_glossary_names_from_evidence():
    client = _Recorder()
    writer = DailyWriter("fake", client=client, lexicon=LEX)
    writer.write("國際", [(1, "report", [_evidence("Lula beats Flávio Bolsonaro", "弗拉維奧不認輸")])])
    assert "譯名一律使用中央社譯名" in client.prompts[0]
    assert "魯拉（Lula／露拉／盧拉）" in client.prompts[0]
    assert "佛拉維歐（Flavio Bolsonaro／弗拉維奧／小波索納洛）" in client.prompts[0]


def test_writer_prompt_has_no_glossary_note_without_names():
    client = _Recorder()
    DailyWriter("fake", client=client, lexicon=LEX).write("科技", [(1, "report", [_evidence("Some chip news")])])
    assert "譯名" not in client.prompts[0]
