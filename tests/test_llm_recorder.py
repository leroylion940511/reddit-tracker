"""scripts/llm_recorder.py：錄真 Codex 的包裝 client（這裡全部用假的 `_run_once`，不執行 subprocess）。"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

from reddit_tracker.llm.codex import CodexClient, CodexError
from reddit_tracker.llm.replay import ReplayClient, load_records, request_hash

_SPEC = importlib.util.spec_from_file_location(
    "llm_recorder", Path(__file__).resolve().parents[1] / "scripts/llm_recorder.py"
)
recorder_mod = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("llm_recorder", recorder_mod)
_SPEC.loader.exec_module(recorder_mod)

MESSAGES = [{"role": "user", "content": "板塊：國際。"}]
SCHEMA = {"type": "object"}


class FakeGuard:
    def __init__(self):
        self.acquired = 0

    def acquire(self, *, model, purpose):
        self.acquired += 1


class FakeCodex(CodexClient):
    model = "gpt-test"
    reasoning_effort = "low"
    purpose = "daily"
    max_retries = 1

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.guard = FakeGuard()
        self.prompts = []

    def _run_once(self, prompt, schema):
        self.prompts.append(prompt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return type("R", (), {"content": outcome, "input_tokens": 10, "output_tokens": 2, "cached_tokens": 0})()


def _client(tmp_path, codex, **kwargs):
    return recorder_mod.RecordingCodexClient(
        codex, db_path=tmp_path / "work.db", version="codex-cli 0.0.0", role="writer", run_variant="test",
        edition_date=date(2026, 10, 27), max_attempts=kwargs.pop("max_attempts", 60), log=lambda *a, **k: None, **kwargs,
    )


def _rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_records ORDER BY id")]
    finally:
        conn.close()


def test_every_attempt_is_recorded_and_hash_matches_replay(tmp_path):
    codex = FakeCodex([CodexError("exit 1"), '{"stories":[]}'])
    client = _client(tmp_path, codex)
    result = client.complete(system="SYS", messages=MESSAGES, max_output_tokens=1, temperature=0, json_mode=True,
                             json_schema=SCHEMA)
    assert result.content == '{"stories":[]}'
    assert codex.prompts == ["SYS\n\n板塊：國際。"] * 2  # 與 CodexClient.complete 送出的內容相同
    assert codex.guard.acquired == 2  # 每次嘗試都扣額度
    rows = _rows(tmp_path / "work.db")
    key = request_hash(system="SYS", prompt="板塊：國際。", model="gpt-test", schema=SCHEMA)
    assert [(r["ok"], r["request_hash"]) for r in rows] == [(0, key), (1, key)]
    assert "exit 1" in rows[0]["error"] and rows[1]["response_text"] == '{"stories":[]}'
    assert rows[1]["model_version"] == "gpt-test | codex-cli 0.0.0 | reasoning_effort=low"
    assert rows[1]["edition_date"] == "2026-10-27" and rows[1]["role"] == "writer" and rows[1]["provider"] == "codex"

    # 同一個 request_hash 已有 ok：直接重用，不再呼叫
    again = client.complete(system="SYS", messages=MESSAGES, max_output_tokens=1, temperature=0, json_schema=SCHEMA)
    assert again.content == '{"stories":[]}' and len(codex.prompts) == 2 and client.reused == 1

    # 匯出後 ReplayClient 用同一個 hash 重播得到
    out = tmp_path / "records.json"
    assert recorder_mod.export_ok_records([tmp_path / "work.db"], out) == 1
    assert "prompt_text" not in json.loads(out.read_text())[0]
    replay = ReplayClient(load_records(out), model="gpt-test")
    assert replay.complete(system="SYS", messages=MESSAGES, max_output_tokens=1, temperature=0,
                           json_schema=SCHEMA).content == '{"stories":[]}'


def test_desk_requests_are_recorded_as_desk(tmp_path):
    client = _client(tmp_path, FakeCodex(['{"groups":[]}']))
    client.complete(system="S", messages=MESSAGES, max_output_tokens=1, temperature=0,
                    json_schema={"type": "object", "properties": {"groups": {}}})
    assert _rows(tmp_path / "work.db")[0]["role"] == "desk"


def test_attempt_budget_counts_all_ledgers(tmp_path):
    other = tmp_path / "other.db"
    first = recorder_mod.RecordingCodexClient(
        FakeCodex(["a"]), db_path=other, version="v", role="writer", run_variant="x",
        edition_date=date(2026, 10, 27), max_attempts=1, log=lambda *a, **k: None,
    )
    first.complete(system="S", messages=[{"role": "user", "content": "one"}], max_output_tokens=1, temperature=0)
    codex = FakeCodex(["b"])
    client = _client(tmp_path, codex, max_attempts=1, ledgers=[other])
    with pytest.raises(recorder_mod.AttemptBudgetExhausted):
        client.complete(system="S", messages=[{"role": "user", "content": "two"}], max_output_tokens=1, temperature=0)
    assert codex.prompts == [] and codex.guard.acquired == 0


def test_old_llm_records_table_gets_new_columns(tmp_path):
    path = tmp_path / "copy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE llm_records (id INTEGER PRIMARY KEY, provider VARCHAR(32) NOT NULL,"
                 " model VARCHAR(64) NOT NULL, purpose VARCHAR(32) NOT NULL, called_at DATETIME)")
    conn.execute("INSERT INTO llm_records (provider, model, purpose) VALUES ('gemini', 'm', 'daily')")
    conn.commit()
    conn.close()
    recorder_mod.ensure_llm_records(path)
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(llm_records)")}
    assert {"request_hash", "prompt_text", "response_text", "latency_ms", "ok", "error", "role", "run_variant",
            "edition_date", "story_id", "model_version"} <= cols
    assert recorder_mod.attempts_used([path]) == 0  # 舊紀錄沒有 request_hash，不算本任務的嘗試
