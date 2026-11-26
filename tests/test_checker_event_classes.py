"""查核員事件四分類（FACT_CHECKER_EVENT_CLASSES，預設關閉；佇列第 12 項 (3)，2026-11-26）。不呼叫 LLM。"""

from __future__ import annotations

import json


from reddit_tracker.daily.mas.orchestrator import (
    CHECKER_EVENT_CLASS_SCHEMA,
    CHECKER_EVENT_CLASS_SUFFIX,
    CHECKER_PER_SOURCE_SCHEMA,
    CHECKER_SCHEMA,
    EVENT_RELATION_KEEP,
    EVENT_RELATIONS,
    checker_source_verdicts,
)
from reddit_tracker.eval import exp2
from reddit_tracker.llm.replay import ReplayResult
from tests.test_exp2 import V1, Scripted, dev  # noqa: F401  （dev 是 fixture）
from tests.test_factcheck_relevance import RECORDS, Replay, _review

# 11/01 5330：S1 自由時報台北辯論、S2 央廣台北辯論（同一場）、S3 公視高雄辯論（無關）
CLASSES_5330 = json.dumps({
    "action": "CHALLENGE", "problem": "NEEDS_CLARIFICATION", "detail": "S3 是高雄市長辯論。",
    "required_action": "排除 S3。",
    "sources": [
        {"sid": 2, "relation": "SAME_EVENT", "reason": "同一場台北市長辯論"},
        {"sid": 3, "relation": "UNRELATED", "reason": "高雄市長辯論"},
    ],
}, ensure_ascii=False)


def test_relation_mapping_and_enum_agree():
    assert set(EVENT_RELATION_KEEP) == set(EVENT_RELATIONS)
    enum = CHECKER_EVENT_CLASS_SCHEMA["properties"]["sources"]["items"]["properties"]["relation"]["enum"]
    assert enum == list(EVENT_RELATIONS)
    for relation in EVENT_RELATIONS:
        assert relation in CHECKER_EVENT_CLASS_SUFFIX


def test_relation_verdict_parsing():
    reply = json.dumps({"action": "CHALLENGE", "sources": [
        {"sid": 2, "relation": "SAME_EVENT"}, {"sid": 3, "relation": "follow_up"},
        {"sid": 4, "relation": "UNRELATED"}, {"sid": "S5", "relation": "ROUNDUP"}]})
    assert checker_source_verdicts(reply, [2, 3, 4, 5]) == {2: True, 3: True, 4: False, 5: False}
    # 不認得的關係＝沒回答，照整篇 action；verdict 與 relation 都有時以 verdict 為準
    odd = '{"action":"OK","sources":[{"sid":2,"relation":"MAYBE"},{"sid":3,"relation":"SAME_EVENT","verdict":"REMOVE"}]}'
    assert checker_source_verdicts(odd, [2, 3]) == {2: True, 3: False}
    # 沒點名的來源說 UNRELATED 也不算
    assert checker_source_verdicts('{"action":"OK","sources":[{"sid":4,"relation":"UNRELATED"}]}', [2]) == {2: True}


def test_flag_off_sends_the_old_request(session):
    client = Replay(RECORDS[5330])
    _review(session, 5330, client, event_classes=False)
    request = client.checker_requests[0]
    assert request["json_schema"] == CHECKER_SCHEMA
    assert request["messages"][0]["content"].startswith("稿件：")
    assert CHECKER_EVENT_CLASS_SUFFIX not in request["system"]


def test_flag_default_comes_from_settings(session, monkeypatch):
    from reddit_tracker.config import get_settings

    monkeypatch.setenv("FACT_CHECKER_EVENT_CLASSES", "true")
    get_settings.cache_clear()
    client = Replay(RECORDS[5330], assessment=CLASSES_5330)
    version, _ = _review(session, 5330, client)
    assert client.checker_requests[0]["json_schema"] == CHECKER_EVENT_CLASS_SCHEMA
    assert len(version.source_ids) == 2


def test_flag_is_off_by_default():
    from reddit_tracker.config import Settings

    assert Settings.model_fields["fact_checker_event_classes"].default is False


def test_5330_keeps_same_debate_and_drops_kaohsiung(session):
    record = RECORDS[5330]
    s1, s2, _ = record["v1"]["source_ids"]
    client = Replay(record, assessment=CLASSES_5330)
    version, messages = _review(session, 5330, client, event_classes=True)
    assert version.version == 2 and version.status == "checked" and version.source_ids == [s1, s2]
    challenge = next(m for m in messages if m.type == "CHALLENGE")
    assert challenge.payload["drop_sids"] == [3] and challenge.payload["cleared_sids"] == [2]
    assert not [m for m in messages if (m.payload or {}).get("problem") == "STILL_BAD"]
    request = client.checker_requests[0]
    assert request["system"].endswith(CHECKER_EVENT_CLASS_SUFFIX)
    assert "程式點名的可疑來源：S2、S3" in request["messages"][0]["content"]


def test_event_classes_win_over_per_source(session):
    client = Replay(RECORDS[5330], assessment=CLASSES_5330)
    _review(session, 5330, client, per_source=True, event_classes=True)
    assert client.checker_requests[0]["json_schema"] == CHECKER_EVENT_CLASS_SCHEMA
    assert client.checker_requests[0]["json_schema"] != CHECKER_PER_SOURCE_SCHEMA


def test_follow_up_is_kept(session):
    record = RECORDS[5330]
    follow = json.dumps({"action": "OK", "problem": "NONE", "detail": "", "required_action": "", "sources": [
        {"sid": 2, "relation": "FOLLOW_UP", "reason": ""}, {"sid": 3, "relation": "SAME_EVENT", "reason": ""}]})
    version, _ = _review(session, 5330, Replay(record, assessment=follow), event_classes=True)
    assert version.status == "checked" and version.source_ids == record["v1"]["source_ids"]


def test_old_global_answer_still_works(session):
    # 模型回舊格式（全域 CHALLENGE、沒有 sources）：照程式全刪
    record = RECORDS[5330]
    version, _ = _review(session, 5330, Replay(record), event_classes=True)
    assert version.source_ids == [record["v1"]["source_ids"][0]]


def test_checker_failure_falls_back_to_program(session):
    version, messages = _review(session, 5330, Replay(RECORDS[5330], assessment=None), event_classes=True)
    assert version.source_ids == [RECORDS[5330]["v1"]["source_ids"][0]]
    assert next(m for m in messages if m.type == "CHALLENGE").payload["drop_sids"] == [2, 3]


class Classes(Scripted):
    """事件四分類查核：`relations`＝{sid: relation}。"""

    def __init__(self, action, relations):
        super().__init__()
        self.action, self.relations = action, relations

    def complete(self, **kwargs):
        if kwargs.get("json_schema") != CHECKER_EVENT_CLASS_SCHEMA:
            return super().complete(**kwargs)
        self.seen.append("event_classes")
        sources = [{"sid": sid, "relation": rel, "reason": f"理由{sid}"} for sid, rel in self.relations.items()]
        return ReplayResult(json.dumps({"action": self.action, "problem": "NONE", "detail": "x",
                                        "required_action": "y", "sources": sources}, ensure_ascii=False))


def test_exp2_event_class_ablation(dev, tmp_path):  # noqa: F811
    case = next(c for c in dev if c.case_id == "E02")
    drafts = {"E02": {**V1, "body": "蘇清泉二度道歉 [S1][S2]。"}}
    base = exp2.run_arm("c", [case], drafts, Scripted("CHALLENGE"), tmp_path / "c.db")
    client = Classes("CHALLENGE", {2: "FOLLOW_UP", 3: "SAME_EVENT", 4: "UNRELATED", 5: "UNRELATED", 6: "ROUNDUP"})
    c4, verdicts = exp2.run_ablation([case], drafts, client, tmp_path / "c4.db", event_classes=True)
    assert c4[0].arm == exp2.EVENT_CLASS_ARM and c4[0].blocked and client.seen[0] == "event_classes"
    assert c4[0].checker_calls == 1
    assert exp2.removal_counts(c4, [case]) == {"total": 3, "wrong": 3, "collateral": 0}
    assert [(v["sid"], v["verdict"], v.get("relation")) for v in verdicts] == [
        (2, "KEEP", "FOLLOW_UP"), (3, "KEEP", "SAME_EVENT"), (4, "REMOVE", "UNRELATED"),
        (5, "REMOVE", "UNRELATED"), (6, "REMOVE", "ROUNDUP")]
    text = exp2.render_ablation(base, c4, [case], verdicts, label="(c4) 事件四分類")
    assert "| (c4) 事件四分類 | 1/1 | 0/0 | 3 | 3 | 0 |" in text and "REMOVE（ROUNDUP）" in text

