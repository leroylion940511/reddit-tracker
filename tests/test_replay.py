"""Replay provider：request_hash 穩定、找不到就丟 ReplayMissing、可從 JSON 或 llm_records 表載入。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from reddit_tracker.daily.evidence import EvidenceItem
from reddit_tracker.daily.writer import STORIES_SCHEMA, SYSTEM_PROMPT, DailyWriter
from reddit_tracker.llm.replay import ReplayClient, ReplayMissing, load_records, prompt_text, request_hash

MESSAGES = [{"role": "user", "content": "第一段"}, {"role": "assistant", "content": "略"}, {"role": "user", "content": "第二段"}]


def test_request_hash_covers_system_prompt_model_schema():
    base = dict(system="s", prompt="p", model="gpt-6.1-sol", schema={"type": "object"})
    h = request_hash(**base)
    assert h == request_hash(**base) and len(h) == 64
    for key, other in [("system", "s2"), ("prompt", "p2"), ("model", "fake"), ("schema", None)]:
        assert request_hash(**{**base, key: other}) != h
    # schema 的 key 順序不影響
    assert request_hash(**{**base, "schema": {"b": 1, "a": 2}}) == request_hash(**{**base, "schema": {"a": 2, "b": 1}})


def test_prompt_text_joins_user_turns_like_codex():
    assert prompt_text(MESSAGES) == "第一段\n\n第二段"


def test_replay_hit_and_miss():
    key = request_hash(system="s", prompt="第一段\n\n第二段", model="m", schema=None)
    client = ReplayClient({key: '{"ok": true}'}, model="m")
    result = client.complete(system="s", messages=MESSAGES, max_output_tokens=1, temperature=0)
    assert json.loads(result.content) == {"ok": True}
    with pytest.raises(ReplayMissing):
        client.complete(system="s2", messages=MESSAGES, max_output_tokens=1, temperature=0)
    assert client.calls == 2 and len(client.misses) == 1


def test_daily_writer_through_replay():
    evidence = [EvidenceItem("o", "s", "中央社", "T2", "zh", "標題", "摘要", "https://x", "2026-10-27T06:00+08:00")]
    probe = ReplayClient({}, model="m")
    with pytest.raises(ReplayMissing):
        DailyWriter("replay", client=probe).write("台灣", [(1, "report", evidence)])
    (key,) = probe.misses
    story = {"id": 1, "headline": "標題一則", "deck": "", "body": "正文" * 40, "why_it_matters": ""}
    client = ReplayClient({key: json.dumps({"stories": [story]})}, model="m")
    written = DailyWriter("replay", client=client).write("台灣", [(1, "report", evidence)])
    assert written[1].headline == "標題一則" and written[1].writer == "replay"
    # 錄音的 key 確實是 system＋prompt＋model＋schema
    assert key == request_hash(system=SYSTEM_PROMPT, prompt=probe_prompt(evidence), model="m", schema=STORIES_SCHEMA)


def probe_prompt(evidence):
    calls = []

    class Spy:
        def complete(self, **kwargs):
            calls.append(prompt_text(kwargs["messages"]))
            raise ReplayMissing("spy")

    with pytest.raises(ReplayMissing):
        DailyWriter("spy", client=Spy()).write("台灣", [(1, "report", evidence)])
    return calls[0]


def test_load_records_from_json_and_sqlite(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(
        json.dumps([
            {"request_hash": "a", "response_text": "A", "ok": True},
            {"request_hash": "b", "response_text": "B", "ok": False},
        ]),
        encoding="utf-8",
    )
    assert load_records(path) == {"a": "A"}

    db = tmp_path / "work.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE llm_records (id INTEGER PRIMARY KEY, request_hash TEXT, response_text TEXT, ok BOOLEAN)")
    conn.executemany(
        "INSERT INTO llm_records (request_hash, response_text, ok) VALUES (?, ?, ?)",
        [("a", "old", 1), ("a", "new", 1), ("c", "bad", 0)],
    )
    conn.commit()
    conn.close()
    assert load_records(db) == {"a": "new"}
