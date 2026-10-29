"""手冊步驟 3 第 5–7 點的程式規則：證據包相關性過濾、轉載辨識（E10）、arXiv 措辭（E12）、
數據欄延遲（E15）、單一來源警語（E16）。

E12、E16 的回歸條件要撰稿輸出才能在重編版上跑（等錄音），這裡另外用不依賴選題結果的
合成稿件驗證：直接拿回歸案例的同一個條件函式（`tests/regression/checks.py`）檢查。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from reddit_tracker.collection.clustering import cluster_recent_items, mark_reprints
from reddit_tracker.collection.collector import recompute_duplicates
from reddit_tracker.collection.normalize import canonicalize_url, strip_title_labels, title_fingerprint
from reddit_tracker.daily import run as run_module
from reddit_tracker.daily.evidence import EvidenceItem, build_evidence
from reddit_tracker.daily.market import STALE_LABEL, is_stale, trading_days_between
from reddit_tracker.daily.render import render_html, telegram_digest
from reddit_tracker.daily.scoring import ScoredCluster, Selection
from reddit_tracker.daily.writer import (
    PREPRINT_LEAD,
    PREPRINT_NOTICE,
    SINGLE_SOURCE_NOTICE,
    SYSTEM_PROMPT,
    DailyWriter,
    WrittenStory,
    finalize_story,
    review_story,
    template_story,
)
from reddit_tracker.models import DailyArticle, DailyEdition, SourceItem, StoryCluster

from .regression.checks import arxiv_rules, single_source_notice
from .regression.rebuild import EditionView, Story

NOW = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
CASES = Path(__file__).parent / "regression" / "cases"


def _case(case_id: str) -> dict:
    return json.loads((CASES / f"{case_id}.json").read_text(encoding="utf-8"))


def _item(session, source_id, host, title, summary="", *, minutes=0, lang="zh-Hant", tier="T2", section="taiwan",
          cluster_id=None, duplicate_of_id=None):
    url = f"https://{host}/{hashlib.sha1(f'{source_id}{title}'.encode()).hexdigest()[:8]}"
    item = SourceItem(
        source_id=source_id, section=section, tier=tier,
        item_key=hashlib.sha1(f"{source_id}{url}".encode()).hexdigest(), url=url, canonical_url=canonicalize_url(url),
        title=title, summary=summary, lang=lang, published_at=NOW + timedelta(minutes=minutes),
        first_seen_at=NOW + timedelta(minutes=minutes), title_fingerprint=title_fingerprint(title),
        cluster_id=cluster_id, duplicate_of_id=duplicate_of_id,
    )
    session.add(item)
    session.flush()
    return item


# ── 轉載辨識（E10）─────────────────────────────────────────────────────────


def test_fingerprint_ignores_leading_labels():
    plain = "洪秀柱赴中稱台灣少數人認賊作父 陸委會：勿貶低自己國家"
    assert title_fingerprint(f"[兩岸] {plain}") == title_fingerprint(plain)
    assert title_fingerprint(f"【政治】{plain}") == title_fingerprint(plain)
    assert title_fingerprint(f"[快訊]【政治】 {plain}") == title_fingerprint(plain)
    assert strip_title_labels("中國擬加強保護[商業秘密]") == "中國擬加強保護[商業秘密]"  # 只去開頭


def test_recompute_duplicates_uses_new_fingerprint(session):
    cna = _item(session, "cna-cross-strait", "cna.com.tw", "中國擬加強保護商業秘密 可禁外資進出口技術")
    rti = _item(session, "rti-news", "rti.org.tw", "[兩岸] 中國擬加強保護商業秘密 可禁外資進出口技術", minutes=17)
    rti.title_fingerprint = "舊指紋"  # 改規則前收到的素材
    assert recompute_duplicates([rti, cna]) == 1
    assert (cna.duplicate_of_id, rti.duplicate_of_id) == (None, cna.id)
    assert rti.title_fingerprint == cna.title_fingerprint


def test_mark_reprints_title_similarity_wire_header_and_time_gap(session):
    cna = _item(session, "cna-cross-strait", "cna.com.tw", "洪秀柱赴中稱台灣少數人認賊作父 陸委會：勿貶低自己國家")
    rti = _item(session, "rti-news", "rti.org.tw", "[兩岸] 洪秀柱赴中稱台灣少數人認賊作父 陸委會：勿貶低自己", minutes=-30)
    yahoo = _item(session, "yahoo-tw-stock", "tw.stock.yahoo.com", "陸委會回應洪秀柱言論",
                  "（中央社台北26日電）針對前立委洪秀柱…", minutes=60)
    late = _item(session, "ltn-politics", "ltn.com.tw", "洪秀柱赴中稱台灣少數人認賊作父 陸委會：勿貶低自己國家", minutes=200)
    other = _item(session, "ltn-world", "ltn.com.tw", "陸委會：洪秀柱說法貶低台灣", minutes=10)
    reprints = mark_reprints([cna, rti, yahoo, late, other])
    # 央廣先發也一樣：中央社是原稿；Yahoo 帶中央社電頭；時間差超過 2 小時、標題不像的都不是轉載
    assert reprints == {rti.id: cna.id, yahoo.id: cna.id}


def test_mark_reprints_does_not_apply_title_similarity_to_english(session):
    a = _item(session, "cnbc-top", "cnbc.com", "Microsoft offers voluntary buyouts to 60,000 employees", lang="en")
    b = _item(session, "theverge", "theverge.com", "Microsoft offers buyouts to 60,000 employees", lang="en", minutes=20)
    syndicated = _item(session, "yahoo-finance", "finance.yahoo.com", a.title, lang="en", minutes=5,
                       duplicate_of_id=a.id)
    assert mark_reprints([a, b, syndicated]) == {syndicated.id: a.id}


def test_outlet_count_and_evidence_count_reprint_once(session):
    title = "總統恭喜味全龍拿下中職總冠軍 盼台灣棒球越來越好"
    summary = "味全龍隊今天在中華職棒總冠軍賽擊敗中信兄弟隊，拿下總冠軍，總統賴清德賽後發文恭喜。"
    cna = _item(session, "cna-sports", "cna.com.tw", title, summary)
    rti = _item(session, "rti-news", "rti.org.tw", f"[政治] {title}", summary, minutes=19)
    cluster_recent_items(session, now=NOW + timedelta(hours=1))
    assert rti.cluster_id == cna.cluster_id
    cluster = session.get(StoryCluster, cna.cluster_id)
    assert cluster.outlet_count == 1

    pack = build_evidence(session, [cluster.id], {"cna-sports": "中央社 運動", "rti-news": "中央廣播電台"})
    assert len(pack.items) == 1
    source = pack.items[0].as_source()
    assert source["outlet"] == "中央社（中央廣播電台轉載）"
    assert source["reprinted_by"] == ["中央廣播電台"]
    assert pack.items[0].source_name == "中央社 運動"  # 撰稿時歸因給原稿


# ── 證據包相關性過濾（E01、E05）──────────────────────────────────────────────


def test_build_evidence_drops_members_without_shared_entity(session):
    cluster = StoryCluster(lang_group="en", section="world", title="", first_published_at=NOW,
                           last_published_at=NOW, created_at=NOW, updated_at=NOW)
    session.add(cluster)
    session.flush()
    rep = _item(session, "dw-en", "dw.com", "Serbia's Vucic concedes defeat as students win election", lang="en",
                section="world", cluster_id=cluster.id)
    _item(session, "cna-world", "cna.com.tw", "塞爾維亞學運贏得國會選舉 武契奇承認敗選", section="world",
          cluster_id=cluster.id, minutes=30)
    _item(session, "apnews-top", "apnews.com", "Jaxon Smith-Njigba leads Seahawks to 20-3 win over Chiefs",
          lang="en", section="world", cluster_id=cluster.id, minutes=40)
    cluster.representative_item_id = rep.id
    session.flush()

    names = {"dw-en": "DW English", "cna-world": "中央社 國際", "apnews-top": "AP"}
    pack = build_evidence(session, [cluster.id], names)
    # 英文代表標題經譯名表統一成中文，中文來源（武契奇、塞爾維亞）不會被剔掉
    assert sorted(e.source_id for e in pack.items) == ["cna-world", "dw-en"]
    assert pack.notes == ["剔除：AP｜Jaxon Smith-Njigba leads…，原因：無共同實體"]


def test_evidence_filter_notes_reach_review_notes():
    evidence = [_ev("中央社 國際", "中文標題", "中文摘要" * 20)]
    selection = Selection(ScoredCluster(1, "world", "report", 10.0), "world", 1, False)
    planned = [run_module.Planned(1, selection, evidence, ["剔除：AP｜X…，原因：無共同實體"])]
    written = run_module._write_all(planned, {"world": "國際"}, None)
    assert written[1].review_notes == ["剔除：AP｜X…，原因：無共同實體"]


# ── arXiv（E12）與單一來源警語（E16）：不依賴選題結果 ──────────────────────────


def _ev(name, title, summary, *, outlet=None, source_id=None, lang="zh-Hant"):
    return EvidenceItem(
        outlet=outlet or name, source_id=source_id or name, source_name=name, tier="T2", lang=lang,
        title=title, summary=summary, url=f"https://{outlet or 'example.com'}/a", published_at="2026-10-27T05:00+08:00",
    )


ARXIV = [
    _ev("arXiv cs.AI", "SWE-Shift: Evaluating Coding Agents in Evolving Workspaces",
        "We introduce SWE-Shift, a benchmark of coding agents in evolving workspaces.",
        outlet="arxiv.org", source_id="arxiv-cs-ai", lang="en"),
]
SINGLE = [_ev("中央社 社會", "吳俊立住院待開刀仍遭拘提", "律師團深夜發聲指出法院已准假，吳俊立心肌炎住院等待開刀。" * 2,
              source_id="cna-society")]
MULTI = SINGLE + [_ev("自由時報 社會", "吳俊立遭拘提 律師：已准假", "律師團表示法院已准假。" * 3, outlet="ltn.com.tw",
                      source_id="ltn-society")]


class _StubWriter:
    """固定回傳的撰稿者（不呼叫任何模型）。"""

    name = "stub"

    def __init__(self, stories: dict[int, WrittenStory]) -> None:
        self.stories = stories

    def write(self, label, stories):
        return {key: self.stories[key] for key, _, _ in stories if key in self.stories}


def _llm(headline, body, deck="", why=""):
    return WrittenStory(headline, deck, body, why, "stub")


def _planned(key, kind, evidence, section="world"):
    return run_module.Planned(key, Selection(ScoredCluster(key, section, kind, 10.0), section, key, False), evidence)


def _view(planned, written) -> EditionView:
    stories = [
        Story(
            key=f"synthetic:{p.key}", section=p.selection.section, kind=p.selection.cluster.kind, published=True,
            is_front=False, sources=[{"title": e.title, "source_id": e.source_id, "outlet": e.source_name}
                                     for e in p.evidence],
            members=set(), headline=written[p.key].headline, deck=written[p.key].deck, body=written[p.key].body,
            why_it_matters=written[p.key].why_it_matters, writer=written[p.key].writer,
        )
        for p in planned
    ]
    return EditionView("synthetic", date(2026, 10, 27), stories, "", None, replay_misses=[])


def test_arxiv_story_uses_preprint_wording():
    bad = _llm("SWE-Shift 評測程式代理", "據 arXiv 獨家報導，目前僅有一家媒體指出，SWE-Shift 是新的程式代理評測基準。" * 2)
    problems = review_story(bad, ARXIV)
    assert any("arXiv 不是媒體" in p for p in problems) and any("預印本" in p for p in problems)

    planned = [_planned(1, "single_source", ARXIV, "science_health")]
    written = run_module._write_all(planned, {"science_health": "科學"}, _StubWriter({1: bad}))
    story = written[1]
    assert story.writer == "template"  # 違規的 LLM 稿改用模板稿
    assert story.body.startswith(PREPRINT_LEAD)
    assert story.body.split("\n")[-1] == PREPRINT_NOTICE
    assert story.deck == "【預印本】"
    view = _view(planned, written)
    assert arxiv_rules(_case("E12"), view) == []
    assert single_source_notice(_case("E16"), view) == []  # arXiv 稿不套單一來源警語

    # 原始錯誤在同一個條件下會被抓到
    view.events[0].body = bad.body
    assert arxiv_rules(_case("E12"), view)


def test_good_arxiv_llm_story_passes_review():
    good = _llm("SWE-Shift 評測程式代理", f"{PREPRINT_LEAD}，SWE-Shift 是評測程式代理在變動工作環境表現的基準。" * 2)
    assert review_story(good, ARXIV) == []


def test_single_source_notice_is_added_by_program_at_the_end():
    assert "single_source" not in SYSTEM_PROMPT  # 提示詞第 4 條已刪（E16）
    fact = "律師團深夜發聲指出法院已准假，吳俊立因心肌炎住院等待開刀，仍遭拘提。"
    single = _llm("吳俊立住院仍遭拘提", f"據中央社報導，{fact}\n\n律師團表示將向法院提出說明，{fact}")
    stuffed = _llm("吳俊立遭拘提", f"目前僅有一家媒體報導指出，{fact}\n\n律師團深夜發聲，{fact}")
    multi = _llm("吳俊立遭拘提 律師：已准假", f"據中央社與自由時報報導，{fact}{fact}")
    planned = [_planned(1, "single_source", SINGLE), _planned(2, "single_source", SINGLE), _planned(3, "report", MULTI)]
    written = run_module._write_all(planned, {"world": "國際"}, _StubWriter({1: single, 2: stuffed, 3: multi}))

    assert written[1].writer == "stub" and written[1].body.split("\n")[-1] == SINGLE_SOURCE_NOTICE
    assert written[1].body.count(SINGLE_SOURCE_NOTICE) == 1
    assert written[2].writer == "template"  # LLM 自己把警語塞在段落中間 → 未過審稿
    assert any("警語由程式加在文末" in n for n in written[2].review_notes)
    assert SINGLE_SOURCE_NOTICE not in written[3].body
    assert single_source_notice(_case("E16"), _view(planned, written)) == []

    # 原始錯誤（警語硬塞在段落中間、文末沒有）在同一個條件下會被抓到
    view = _view(planned, {**written, 1: stuffed})
    assert single_source_notice(_case("E16"), view)


def test_finalize_is_idempotent_and_template_has_no_notice_of_its_own():
    story = template_story(SINGLE, "single_source")
    assert SINGLE_SOURCE_NOTICE not in story.body
    finalize_story(story, SINGLE, "single_source")
    finalize_story(story, SINGLE, "single_source")
    assert story.body.count(SINGLE_SOURCE_NOTICE) == 1


def test_writer_prompt_flags_preprint_stories_only():
    class _Recorder:
        prompts: list[str] = []

        def complete(self, *, system, messages, **kwargs):
            self.prompts.append(messages[0]["content"])
            return type("R", (), {"content": '{"stories": []}'})()

    recorder = _Recorder()
    writer = DailyWriter("fake", client=recorder)
    writer.write("科學", [(1, "single_source", ARXIV)])
    writer.write("社會", [(1, "single_source", SINGLE)])
    assert '"source_type":"preprint"' in recorder.prompts[0] and PREPRINT_LEAD in recorder.prompts[0]
    assert "preprint" not in recorder.prompts[1]


# ── 數據欄延遲（E15）──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "close, edition, behind, stale",
    [
        ("2026-10-26", date(2026, 10, 27), 1, False),  # 週二出刊、週一收盤：正常
        ("2026-10-23", date(2026, 10, 26), 1, False),  # 週一出刊、上週五收盤：正常
        ("2026-10-23", date(2026, 10, 27), 2, True),
        ("2026-10-22", date(2026, 10, 27), 3, True),  # 10/27 試刊號的實際情況
    ],
)
def test_market_staleness_counts_trading_days(close, edition, behind, stale):
    assert trading_days_between(date.fromisoformat(close), edition) == behind
    assert is_stale(close, edition) is stale


def test_market_box_shows_stale_label():
    market = [{"name": "發行量加權股價指數", "close": "28,000", "change": "+10", "change_pct": "+0.1%",
               "date": "2026-10-22"}]
    sections = {"taiwan": "台灣"}
    stale = DailyEdition(edition_date=date(2026, 10, 27), stats={"market": market})
    fresh = DailyEdition(edition_date=date(2026, 10, 23), stats={"market": market})
    for edition in (stale, fresh):
        edition.articles = [DailyArticle(section="taiwan", position=1, is_front=True, kind="report", headline="頭條",
                                         deck="", body="內文", why_it_matters="", sources=[], writer="template")]
    assert STALE_LABEL in render_html(stale, sections) and STALE_LABEL in telegram_digest(stale, sections)
    assert STALE_LABEL not in render_html(fresh, sections) and STALE_LABEL not in telegram_digest(fresh, sections)


def test_render_labels_arxiv_only_story_as_preprint():
    article = DailyArticle(section="tech", position=1, is_front=False, kind="single_source", headline="SWE-Shift",
                           deck="", body="內文", why_it_matters="", writer="template",
                           sources=[{"outlet": "arXiv cs.AI", "url": "https://arxiv.org/abs/2610.00001", "title": "x"}])
    edition = DailyEdition(edition_date=date(2026, 10, 27), stats={})
    edition.articles = [article]
    html = render_html(edition, {"tech": "科技"})
    assert '<span class="tag">預印本</span>' in html and '<span class="tag">單一來源</span>' not in html
