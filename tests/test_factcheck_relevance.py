"""查核員刪來源的回歸（2026-10-31／11-01 M 組真實案例，不呼叫 LLM）。

fixture `factcheck_1031_1101.json` 由 `scripts/recheck_factcheck.py --export-fixture` 從 production 複本匯出：
有 IRRELEVANT_SOURCE CHALLENGE 的 10 篇稿，第 1 版的證據（S 順序）、第 1／2 版稿、當期查核員 LLM 的回應。
當期程式只看標題、句首字不算名字，把 21 個來源刪到 8 篇只剩 1 家；其中只有 5330 的高雄辯論稿、
5455 的 Microsoft 財報稿是真的無關。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.daily.mas.orchestrator import (
    CHECKER_PER_SOURCE_SCHEMA,
    CHECKER_SCHEMA,
    REPORTER_SYSTEM,
    checker_says_same_event,
    checker_source_verdicts,
    irrelevant_sources,
    review_one,
)
from reddit_tracker.daily.store import MAS, add_story
from reddit_tracker.models import AgentMessage

FIXTURE = Path(__file__).parent / "regression" / "fixtures" / "factcheck_1031_1101.json"
RECORDS = {r["story_id"]: r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))}
NOW = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)

# 當期被刪、其實是同一事件的來源（story_id → S 編號）
WRONG_CUTS = {
    14: {2},  # 毒駕修法：央廣
    15: {2, 3},  # 幣安遭駭：科技新報、央廣
    18: {2, 3, 4, 5, 6},  # Binance hack：NPR、DW、Al Jazeera、Guardian、Yahoo Finance
    33: {2, 3},  # 以色列大選
    34: {2, 3, 4, 5},  # 拉加德請辭：央廣、自由時報…
    5327: {2},  # 台北市長辯論：報導者
    5328: {2, 3},  # Oleshky 撤離
    5331: {2},  # 聯合國索馬利亞特派團：央廣
}
# 真的無關、要繼續刪的來源
CORRECT_CUTS = {5330: {3}, 5455: {2}}  # 台北辯論稿裡的高雄辯論、Amazon 財報稿裡的 Microsoft 財報


def _evidence(story_id: int) -> list[EvidenceItem]:
    return [EvidenceItem(**item) for item in RECORDS[story_id]["evidence"]]


def _cuts(story_id: int) -> set[int]:
    """新規則：程式點名、且查核員當期回應沒有判定同一事件，才刪。"""
    flagged = {index for index, _ in irrelevant_sources(_evidence(story_id))}
    if checker_says_same_event(RECORDS[story_id]["challenge"]["llm_assessment"]):
        return set()
    return flagged


def test_fixture_matches_what_was_cut_on_the_day():
    assert set(RECORDS) == set(WRONG_CUTS) | set(CORRECT_CUTS)
    for story_id, record in RECORDS.items():
        stored = set(record["challenge"]["drop_sids"])
        assert stored >= WRONG_CUTS.get(story_id, set()) | CORRECT_CUTS.get(story_id, set())
        assert len(record["v2"]["source_ids"]) == 1  # 當期都被刪到剩 1 家


@pytest.mark.parametrize("story_id", sorted(WRONG_CUTS))
def test_same_event_sources_are_no_longer_cut(story_id):
    assert not _cuts(story_id) & WRONG_CUTS[story_id]


@pytest.mark.parametrize("story_id", sorted(CORRECT_CUTS))
def test_unrelated_sources_are_still_cut(story_id):
    assert _cuts(story_id) >= CORRECT_CUTS[story_id]


def test_sentence_initial_names_are_corroborated_inside_the_pack():
    # 「Binance hack: …」「Binance crypto platform …」的 Binance 是句首字；NPR 標題句中有 Binance，算名字
    assert {i for i, _ in irrelevant_sources(_evidence(18))} == {5}  # 只剩 Guardian 標題沒有 Binance
    assert not irrelevant_sources(_evidence(5328))  # Oleshky
    # 不比中文片段：高雄辯論與台北辯論共有「市長選戰」，程式仍要點名，交給查核員
    assert 3 in {i for i, _ in irrelevant_sources(_evidence(5330))}


def test_checker_verdict_parsing():
    assert checker_says_same_event('{"action":"OK","problem":"NONE","detail":"","required_action":""}')
    assert checker_says_same_event('{"action":"ok","problem":"NONE"}')
    assert not checker_says_same_event('{"action":"CHALLENGE","problem":"NEEDS_CLARIFICATION"}')
    assert not checker_says_same_event(None)
    assert not checker_says_same_event("not json")


# ── 整條查核流程（Scripted client 重播當期的稿與查核員回應）──────────────────


class Replay:
    """記者回當期第 1 版（DRAFT）／第 2 版（REVISE）；查核員回當期存下的判斷。"""

    def __init__(self, record: dict, assessment: str | None = "stored"):
        self.record = record
        self.assessment = record["challenge"]["llm_assessment"] if assessment == "stored" else assessment
        self.calls: list[str] = []
        self.checker_requests: list[dict] = []

    def complete(self, **kwargs):
        user = kwargs["messages"][-1]["content"]
        if kwargs["system"] == REPORTER_SYSTEM:
            self.calls.append("reporter")
            version = self.record["v2"] if "REVISE" in user else self.record["v1"]
            content = json.dumps({
                "action": "REVISE" if "REVISE" in user else "DRAFT", "headline": version["headline"],
                "deck": version["deck"], "body": version["body"], "why_it_matters": version["why_it_matters"],
                "reason": "",
            }, ensure_ascii=False)
        else:
            self.calls.append("fact_checker")
            self.checker_requests.append(kwargs)
            if self.assessment is None:
                raise RuntimeError("checker down")
            content = self.assessment
        return SimpleNamespace(content=content, input_tokens=1, output_tokens=1, cached_tokens=0)


def _review(session, story_id: int, client, **kwargs) -> tuple:
    record = RECORDS[story_id]
    story = add_story(session, edition_date=date.fromisoformat(record["edition_date"]), run_variant=MAS, spec={
        "keeper_cluster_id": record["keeper_cluster_id"], "section": record["section"], "kind": record["kind"],
        "score": 1,
    })
    version = review_one(
        session, edition_date=story.edition_date, story=story, evidence=_evidence(story_id), client=client, now=NOW,
        **kwargs,
    )
    messages = session.scalars(select(AgentMessage).where(AgentMessage.story_id == story.id)).all()
    return version, messages


@pytest.mark.parametrize("story_id", [18, 34, 5327])
def test_review_keeps_all_sources_when_checker_says_same_event(session, story_id):
    record = RECORDS[story_id]
    client = Replay(record)
    version, messages = _review(session, story_id, client)
    all_ids = record["v1"]["source_ids"]
    assert version.status == "checked" and version.source_ids == all_ids
    assert not [m for m in messages if m.type == "CHALLENGE"]
    release = next(m for m in messages if m.type == "RELEASE")
    assert set(release.payload["cleared_item_ids"]) <= set(all_ids) and "查核員判定同一事件" in release.payload["detail"]
    assert client.calls == ["reporter", "fact_checker"]  # 不再為了修稿多叫記者


@pytest.mark.parametrize(("story_id", "removed"), [(5330, 25838), (5455, 19672)])
def test_review_still_drops_unrelated_sources(session, story_id, removed):
    version, messages = _review(session, story_id, Replay(RECORDS[story_id]))
    assert removed not in version.source_ids and version.version == 2
    challenge = next(m for m in messages if m.type == "CHALLENGE")
    assert challenge.payload["problem"] == "IRRELEVANT_SOURCE"


def test_without_checker_judgement_the_program_result_stands(session):
    # 查核員 LLM 失敗（或額度用完）時沒有「同一事件」的判斷，照程式刪；行為與修正前相同
    version, messages = _review(session, 5327, Replay(RECORDS[5327], assessment=None))
    assert version.source_ids == [RECORDS[5327]["v1"]["source_ids"][0]]
    assert next(m for m in messages if m.type == "CHALLENGE").payload["drop_sids"] == [2]


def test_cleared_sources_survive_a_number_challenge_and_recheck(session):
    record = json.loads(json.dumps(RECORDS[5327]))
    record["v1"]["body"] += " 現場約有 4321 人。"  # 證據裡沒有的數字
    record["v2"] = dict(record["v1"], body=RECORDS[5327]["v1"]["body"])
    version, messages = _review(session, 5327, Replay(record))
    challenge = next(m for m in messages if m.type == "CHALLENGE")
    assert challenge.payload["problem"] == "UNSUPPORTED_NUMBER" and challenge.payload["drop_sids"] == []
    assert challenge.payload["cleared_sids"] == [2]
    # 修稿後重驗不把查核員已判定同一事件的 S2 當成無關（不會 STILL_BAD）
    assert version.status == "checked" and version.source_ids == record["v1"]["source_ids"]
    assert not [m for m in messages if (m.payload or {}).get("problem") == "STILL_BAD"]


# ── 逐來源判斷（FACT_CHECKER_PER_SOURCE，預設關閉）────────────────────────────

# 11/01 5330：S1 自由時報台北辯論、S2 央廣台北辯論（同一場）、S3 公視高雄辯論（無關）
PER_SOURCE_5330 = json.dumps({
    "action": "CHALLENGE", "problem": "NEEDS_CLARIFICATION",
    "detail": "S3 是高雄市長辯論，與 S1 的台北市長辯論不同。", "required_action": "排除 S3。",
    "sources": [
        {"sid": 2, "verdict": "KEEP", "reason": "同一場台北市長辯論"},
        {"sid": 3, "verdict": "REMOVE", "reason": "高雄市長辯論"},
    ],
}, ensure_ascii=False)


def test_per_source_verdict_parsing():
    assert checker_source_verdicts(PER_SOURCE_5330, [2, 3]) == {2: True, 3: False}
    # 舊格式（只有全域 action）：OK 全留、CHALLENGE 全刪
    assert checker_source_verdicts('{"action":"OK","problem":"NONE"}', [2, 3]) == {2: True, 3: True}
    assert checker_source_verdicts(RECORDS[5330]["challenge"]["llm_assessment"], [2, 3]) == {2: False, 3: False}
    # 沒提到的點名來源照全域 action；"S2" 寫法也收；沒點名的 REMOVE 不算（刪來源要程式先點名）
    partial = '{"action":"OK","sources":[{"sid":"S3","verdict":"remove","reason":""},{"sid":4,"verdict":"REMOVE"}]}'
    assert checker_source_verdicts(partial, [2, 3]) == {2: True, 3: False}
    # 判斷值不認得就當沒提到
    assert checker_source_verdicts('{"action":"CHALLENGE","sources":[{"sid":2,"verdict":"MAYBE"}]}', [2]) == {2: False}
    # 沒有回應或格式錯＝照程式全刪
    assert checker_source_verdicts(None, [2, 3]) == {2: False, 3: False}
    assert checker_source_verdicts("not json", [2]) == {2: False}


def test_5330_per_source_keeps_same_debate_and_drops_kaohsiung(session):
    record = RECORDS[5330]
    s1, s2, s3 = record["v1"]["source_ids"]
    client = Replay(record, assessment=PER_SOURCE_5330)
    version, messages = _review(session, 5330, client, per_source=True)
    assert version.version == 2 and version.status == "checked"
    assert version.source_ids == [s1, s2]  # 當期只剩 [s1]
    challenge = next(m for m in messages if m.type == "CHALLENGE")
    assert challenge.payload["problem"] == "IRRELEVANT_SOURCE" and challenge.payload["drop_sids"] == [3]
    assert challenge.payload["cleared_sids"] == [2] and challenge.payload["cleared_item_ids"] == [s2]
    # 修稿後重驗不把查核員判 KEEP 的 S2 再點名
    assert not [m for m in messages if (m.payload or {}).get("problem") == "STILL_BAD"]
    assert client.calls == ["reporter", "fact_checker", "reporter"]
    request = client.checker_requests[0]
    assert request["json_schema"] == CHECKER_PER_SOURCE_SCHEMA
    assert "程式點名的可疑來源：S2、S3" in request["messages"][0]["content"]


def test_per_source_flag_off_sends_the_old_request(session):
    # 預設關閉：提示詞與 schema 跟 11/01 前逐字相同，request_hash 不變（1027_t2a 錄音靠這個重播）
    client = Replay(RECORDS[5330])
    version, _ = _review(session, 5330, client)
    request = client.checker_requests[0]
    assert request["json_schema"] == CHECKER_SCHEMA and "sources" not in request["json_schema"]["properties"]
    assert request["messages"][0]["content"].startswith("稿件：")
    assert request["system"].endswith("另檢查每個來源與 S1 是否同一事件；無關來源必須提出異議。")
    assert version.source_ids == [RECORDS[5330]["v1"]["source_ids"][0]]  # 舊行為：S2、S3 一起刪


def test_per_source_flag_comes_from_settings(session, monkeypatch):
    from reddit_tracker.config import get_settings
    monkeypatch.setenv("FACT_CHECKER_PER_SOURCE", "true")
    get_settings.cache_clear()
    client = Replay(RECORDS[5330], assessment=PER_SOURCE_5330)
    version, _ = _review(session, 5330, client)
    assert client.checker_requests[0]["json_schema"] == CHECKER_PER_SOURCE_SCHEMA
    assert len(version.source_ids) == 2


def test_per_source_mode_still_accepts_old_global_answers(session):
    # 旗標開了但模型回舊格式（當期存下的全域 CHALLENGE）：照舊全刪
    version, messages = _review(session, 5330, Replay(RECORDS[5330]), per_source=True)
    assert version.source_ids == [RECORDS[5330]["v1"]["source_ids"][0]]
    assert next(m for m in messages if m.type == "CHALLENGE").payload["drop_sids"] == [2, 3]
    # 全域 OK：全留，跟關閉時一樣
    version, messages = _review(session, 5327, Replay(RECORDS[5327]), per_source=True)
    assert version.status == "checked" and version.source_ids == RECORDS[5327]["v1"]["source_ids"]


def test_per_source_keep_cannot_clear_unsupported_numbers(session):
    record = json.loads(json.dumps(RECORDS[5330]))
    record["v1"]["body"] += " 現場約有 4321 人。"  # 證據裡沒有的數字
    record["v2"] = dict(record["v1"], body=RECORDS[5330]["v1"]["body"])
    all_keep = json.dumps({"action": "OK", "problem": "NONE", "detail": "", "required_action": "", "sources": [
        {"sid": 2, "verdict": "KEEP", "reason": ""}, {"sid": 3, "verdict": "KEEP", "reason": ""}]})
    version, messages = _review(session, 5330, Replay(record, assessment=all_keep), per_source=True)
    challenge = next(m for m in messages if m.type == "CHALLENGE")
    assert challenge.payload["problem"] == "UNSUPPORTED_NUMBER" and challenge.payload["drop_sids"] == []
    assert challenge.payload["cleared_sids"] == [2, 3]
    assert version.version == 2 and "4321" not in version.body


def test_per_source_mode_checker_failure_falls_back_to_program(session):
    version, messages = _review(session, 5330, Replay(RECORDS[5330], assessment=None), per_source=True)
    assert version.source_ids == [RECORDS[5330]["v1"]["source_ids"][0]]
    assert next(m for m in messages if m.type == "CHALLENGE").payload["drop_sids"] == [2, 3]
