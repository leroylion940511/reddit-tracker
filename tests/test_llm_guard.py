"""全域測試防護：執行 codex、連 Gemini API 都會讓測試失敗；其他 subprocess 不受影響。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest
import requests

from reddit_tracker.llm.codex import CodexClient
from tests import llm_guard

BLOCKED = pytest.fail.Exception


@pytest.fixture()
def expect_block():
    """這些測試故意觸發防護；確認有攔到後清掉紀錄，避免 autouse 檢查判失敗。"""
    yield
    assert llm_guard.attempts, "防護沒有攔到"
    llm_guard.attempts.clear()


@pytest.mark.parametrize(
    "args, kwargs",
    [
        (["/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex", "exec", "-"], {}),
        (["codex", "--version"], {}),
        (["/usr/bin/env", "codex", "exec"], {}),
        ("codex exec --json -", {"shell": True}),
        (["anything"], {"executable": "/opt/homebrew/bin/codex"}),
    ],
)
def test_subprocess_codex_is_blocked(expect_block, args, kwargs):
    with pytest.raises(BLOCKED, match="codex"):
        subprocess.run(args, capture_output=True, **kwargs)


def test_os_level_codex_is_blocked(expect_block):
    with pytest.raises(BLOCKED):
        os.system("codex exec -")


def test_codex_client_cannot_reach_binary(expect_block):
    """真的 CodexClient（沒有 mock subprocess）在執行前就被擋下，例外吞不掉。"""
    client = CodexClient(binary="/nonexistent/bin/codex", max_retries=0)
    with pytest.raises(BLOCKED):
        client.complete(
            system="s", messages=[{"role": "user", "content": "hi"}], max_output_tokens=10, temperature=0
        )


def test_gemini_http_is_blocked(expect_block):
    with pytest.raises(BLOCKED, match="Gemini"):
        requests.post("https://generativelanguage.googleapis.com/v1beta/models/x:generateContent", timeout=1)


def test_gemini_dns_is_blocked(expect_block):
    with pytest.raises(BLOCKED, match="Gemini"):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)


def test_swallowed_attempt_still_recorded():
    """程式碼若用 except BaseException 吞掉，autouse fixture 仍能從紀錄判失敗。"""
    try:
        subprocess.run(["codex"])
    except BaseException:  # noqa: BLE001 — 模擬被吞掉
        pass
    assert llm_guard.attempts
    llm_guard.attempts.clear()


def test_other_subprocesses_still_work():
    out = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "ok"
    assert not llm_guard.attempts
