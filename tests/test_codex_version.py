"""Codex CLI 版本守門與 llm_records 的實測版本（不執行 codex，subprocess 一律假的）。"""

from __future__ import annotations

import logging
import subprocess
from types import SimpleNamespace

import pytest

from reddit_tracker.llm import codex as codex_module
from reddit_tracker.llm import codex_version
from reddit_tracker.llm.codex_version import probe_cli_version as real_probe
from reddit_tracker.newsroom import scheduler

LOCKED = "gpt-6.1-sol | codex-cli 0.166.0 | reasoning_effort=low"


def _settings(**overrides):
    values = dict(
        daily_writer="codex", codex_bin="/opt/homebrew/bin/codex", daily_model_version=LOCKED,
        telegram_bot_token="123456:TOKEN", telegram_chat_id="42",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_version, "send_telegram_warning", lambda token, chat, text: calls.append((chat, text)))
    return calls


def _probe(monkeypatch, version):
    monkeypatch.setattr(codex_version, "probe_cli_version", lambda binary, **kw: version)


@pytest.mark.parametrize("output, expected", [
    ("codex-cli 0.166.0\n", "0.166.0"),
    ("codex-cli 0.164.0-alpha.11.1", "0.164.0-alpha.11.1"),
    ("", None),
    ("something else", None),
    (None, None),
])
def test_parse_cli_version(output, expected):
    assert codex_version.parse_cli_version(output) == expected


def test_locked_cli_version():
    assert codex_version.locked_cli_version(LOCKED) == "0.166.0"
    assert codex_version.locked_cli_version("gpt-6.1-sol+effort=low") is None
    assert codex_version.locked_cli_version(None) is None


def test_actual_model_version_replaces_or_marks_the_cli_segment():
    assert codex_version.actual_model_version(LOCKED, "0.167.0") == "gpt-6.1-sol | codex-cli 0.167.0 | reasoning_effort=low"
    assert codex_version.actual_model_version(LOCKED, None) == (
        "gpt-6.1-sol | codex-cli unknown(locked 0.166.0) | reasoning_effort=low"
    )
    assert codex_version.actual_model_version("m+effort=low", "0.166.0") == "m+effort=low"


def test_probe_parses_stdout_and_handles_failures(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw.get("timeout"), kw.get("shell")))
        return subprocess.CompletedProcess(cmd, 0, stdout="codex-cli 0.166.0\n", stderr="")

    monkeypatch.setattr(codex_version.subprocess, "run", fake_run)
    assert real_probe("/x/codex") == "0.166.0"
    assert seen == [(["/x/codex", "--version"], codex_version.PROBE_TIMEOUT_SECONDS, None)]

    monkeypatch.setattr(codex_version.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "err"))
    assert real_probe("/x/codex") is None
    monkeypatch.setattr(codex_version.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "???", ""))
    assert real_probe("/x/codex") is None

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(codex_version.subprocess, "run", timeout)
    assert real_probe("/x/codex") is None


def test_probe_missing_binary_returns_none(tmp_path):
    assert real_probe(str(tmp_path / "no-such-binary")) is None


def test_guard_ok_logs_info(monkeypatch, sent, caplog):
    _probe(monkeypatch, "0.166.0")
    with caplog.at_level(logging.INFO, logger=codex_version.__name__):
        assert codex_version.check_codex_version(_settings()) is True
    assert "codex version guard ok: codex-cli 0.166.0 (bin=/opt/homebrew/bin/codex)" in caplog.text
    assert sent == []


def test_guard_mismatch_logs_error_and_warns_telegram(monkeypatch, sent, caplog):
    _probe(monkeypatch, "0.167.0")
    with caplog.at_level(logging.INFO, logger=codex_version.__name__):
        assert codex_version.check_codex_version(_settings()) is False
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "0.167.0" in errors[0].getMessage() and "0.166.0" in errors[0].getMessage()
    assert len(sent) == 1 and sent[0][0] == "42" and "0.167.0" in sent[0][1]


def test_guard_unreadable_without_telegram_only_logs(monkeypatch, sent, caplog):
    _probe(monkeypatch, None)
    with caplog.at_level(logging.INFO, logger=codex_version.__name__):
        assert codex_version.check_codex_version(_settings(telegram_bot_token=None)) is False
    assert "unreadable" in caplog.text and sent == []


def test_guard_never_raises(monkeypatch, caplog):
    _probe(monkeypatch, "0.1.0")

    def boom(*a):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(codex_version, "send_telegram_warning", boom)
    assert codex_version.check_codex_version(_settings()) is False
    monkeypatch.setattr(codex_version, "probe_cli_version", real_probe)
    assert codex_version.check_codex_version(_settings(codex_bin="/nonexistent/codex-missing", telegram_bot_token=None)) is False


def test_guard_skips_non_codex_writer(monkeypatch, sent):
    called = []
    monkeypatch.setattr(codex_version, "probe_cli_version", lambda b, **kw: called.append(b))
    assert codex_version.check_codex_version(_settings(daily_writer="template")) is None
    assert codex_version.check_codex_version(_settings(daily_model_version="m+effort=low")) is None
    assert called == [] and sent == []


def _client_settings(tmp_path, **overrides):
    values = dict(
        codex_bin="/opt/homebrew/bin/codex", codex_model="gpt-6.1-sol", codex_reasoning_effort="low",
        codex_timeout_seconds=5, codex_max_retries=1, llm_daily_limit=60,
        llm_quota_state_path=str(tmp_path / "q.json"), telegram_bot_token=None, gemini_api_key=None,
        rsshub_access_key=None, daily_model_version=LOCKED,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_codex_client_records_actual_cli_version_probed_once(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(codex_version, "probe_cli_version", lambda b, **kw: calls.append(b) or "0.166.1")
    monkeypatch.setattr(codex_module, "get_settings", lambda: _client_settings(tmp_path))
    client = codex_module.CodexClient()
    assert calls == []  # 建 client 不跑 subprocess
    assert client.model_version == "gpt-6.1-sol | codex-cli 0.166.1 | reasoning_effort=low"
    assert client.model_version and calls == ["/opt/homebrew/bin/codex"]


def test_codex_client_marks_unreadable_version(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_module, "get_settings", lambda: _client_settings(tmp_path))
    assert codex_module.CodexClient().model_version == (
        "gpt-6.1-sol | codex-cli unknown(locked 0.166.0) | reasoning_effort=low"
    )


def test_codex_client_non_locked_model_keeps_effort_string(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_version, "probe_cli_version", lambda b, **kw: pytest.fail("should not probe"))
    monkeypatch.setattr(codex_module, "get_settings", lambda: _client_settings(tmp_path))
    assert codex_module.CodexClient(model="other").model_version == "other+effort=low"


def test_scheduler_prepare_runs_guard_before_prepare(monkeypatch):
    calls = []
    settings = SimpleNamespace(newsroom_delivery_timezone="Asia/Taipei", daily_mode="pipeline")
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "check_codex_version", lambda s, **kw: calls.append(("guard", s)))
    monkeypatch.setattr(scheduler, "prepare_daily", lambda day: calls.append(("prepare", day)) or 1)
    scheduler._prepare_daily_today()
    assert [c[0] for c in calls] == ["guard", "prepare"] and calls[0][1] is settings
