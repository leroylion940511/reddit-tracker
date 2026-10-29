import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from reddit_tracker.llm import codex as codex_module
from reddit_tracker.llm.codex import CodexClient, CodexError
from reddit_tracker.llm.quota import ModelQuotaGuard, QuotaExhausted


@pytest.fixture()
def settings(tmp_path):
    return SimpleNamespace(
        codex_bin="/usr/local/bin/codex", codex_model="m", codex_reasoning_effort="low", codex_timeout_seconds=5,
        codex_max_retries=1, llm_daily_limit=60, llm_quota_state_path=str(tmp_path / "quota.json"),
        telegram_bot_token="123456:SECRET-TOKEN", gemini_api_key=None, rsshub_access_key=None,
    )


@pytest.fixture()
def client(monkeypatch, settings):
    monkeypatch.setattr(codex_module, "get_settings", lambda: settings)
    return CodexClient()


def _fake_run(monkeypatch, *, content="{}", returncode=0, calls=None, fail_first=0):
    state = {"fail": fail_first}

    def run(cmd, *, input, cwd, **kwargs):
        if state["fail"]:
            state["fail"] -= 1
            if calls is not None:
                calls.append({"cmd": cmd, "input": input, "cwd_empty": True, "schema": None})
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="transient")
        out = Path(cmd[cmd.index("-o") + 1])
        if calls is not None:
            schema = cmd[cmd.index("--output-schema") + 1] if "--output-schema" in cmd else None
            calls.append({"cmd": cmd, "input": input, "cwd_empty": not any(Path(cwd).iterdir()),
                          "schema": json.loads(Path(schema).read_text()) if schema else None})
        out.write_text(content, encoding="utf-8")
        usage = {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2}}
        return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(usage) + "\n", stderr="boom")

    monkeypatch.setattr(codex_module.subprocess, "run", run)


def test_command_locks_down_tools_and_sandbox(client, tmp_path):
    cmd = client.command(workdir=tmp_path, schema_path=None, output_path=tmp_path / "o")
    assert cmd[:2] == ["/usr/local/bin/codex", "exec"]
    assert {"--ephemeral", "--ignore-user-config", "--ignore-rules"} <= set(cmd)
    assert cmd[cmd.index("-s") + 1] == "read-only"
    for feature in ("shell_tool", "unified_exec", "code_mode_host", "multi_agent"):
        assert f"features.{feature}=false" in cmd


def test_complete_passes_schema_and_system_and_parses_usage(client, monkeypatch):
    calls = []
    _fake_run(monkeypatch, content='{"groups":[]}', calls=calls)
    result = client.complete(
        system="SYS", messages=[{"role": "user", "content": "USER"}], max_output_tokens=10,
        temperature=0, json_mode=True, json_schema={"type": "object"},
    )
    assert result.content == '{"groups":[]}'
    assert (result.input_tokens, result.cached_tokens, result.output_tokens) == (10, 4, 2)
    assert calls[0]["schema"] == {"type": "object"}
    assert calls[0]["input"].startswith("SYS") and "USER" in calls[0]["input"]
    assert calls[0]["cwd_empty"]  # 在空的工作目錄執行


KWARGS = dict(system="s", messages=[{"role": "user", "content": "u"}], max_output_tokens=1, temperature=0)


def test_complete_rejects_failures_and_leaked_secrets(client, monkeypatch):
    _fake_run(monkeypatch, returncode=1)
    with pytest.raises(CodexError, match="exit 1"):
        client.complete(**KWARGS)
    _fake_run(monkeypatch, content='{"body":"123456:SECRET-TOKEN"}')
    with pytest.raises(CodexError, match="機密"):
        client.complete(**KWARGS)
    _fake_run(monkeypatch, content="   ")
    with pytest.raises(CodexError, match="空白"):
        client.complete(**KWARGS)


def test_each_attempt_including_retry_consumes_one_model_quota_unit(client, monkeypatch):
    calls = []
    _fake_run(monkeypatch, content='{"ok":1}', calls=calls, fail_first=1)
    assert client.complete(**KWARGS).content == '{"ok":1}'
    assert len(calls) == 2  # 失敗一次＋重試一次（CODEX_MAX_RETRIES=1）
    assert client.guard.used("m") == 2

    _fake_run(monkeypatch, returncode=1)
    with pytest.raises(CodexError):
        client.complete(**KWARGS)
    assert client.guard.used("m") == 4  # 兩次都失敗也各扣一格

    _fake_run(monkeypatch, content='{"body":"123456:SECRET-TOKEN"}')
    with pytest.raises(CodexError, match="機密"):
        client.complete(**KWARGS)
    assert client.guard.used("m") == 5  # 機密外洩不重試


def test_quota_is_shared_across_purposes_and_blocks_before_subprocess(monkeypatch, settings):
    monkeypatch.setattr(codex_module, "get_settings", lambda: settings)
    guard = ModelQuotaGuard(state_path=settings.llm_quota_state_path, daily_limit=2)
    calls = []
    _fake_run(monkeypatch, calls=calls)
    CodexClient(purpose="daily", guard=guard).complete(**KWARGS)
    CodexClient(purpose="reporter", guard=guard).complete(**KWARGS)
    with pytest.raises(QuotaExhausted):
        CodexClient(purpose="checker", guard=guard).complete(**KWARGS)
    assert len(calls) == 2  # 額度用完時根本不執行 codex
    assert guard.used("m") == 2
