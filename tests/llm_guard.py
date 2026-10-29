"""測試防護：測試期間任何人嘗試執行 codex binary 或連 Gemini API，測試直接失敗。

`install()` 在 pytest 啟動時包住 subprocess／os 的執行入口、requests 的 HTTP 送出與
DNS 查詢。攔到時丟 `pytest.fail`（BaseException，`except Exception` 吞不掉），並記在
`attempts`；conftest 的 autouse fixture 在每個測試結束時再檢查一次，所以就算被
`except BaseException` 吞掉也還是會失敗。
"""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests.adapters

GEMINI_HOSTS = ("generativelanguage.googleapis.com",)
_CODEX_NAME = re.compile(r"^codex(\.exe)?$", re.IGNORECASE)

attempts: list[str] = []
_installed = False


def _tokens(args) -> list[str]:
    if isinstance(args, (str, bytes, os.PathLike)):
        text = os.fsdecode(args)
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()
    try:
        return [os.fsdecode(a) for a in args]
    except TypeError:
        return []


def _block(what: str) -> None:
    attempts.append(what)
    pytest.fail(f"測試不得呼叫真 LLM：{what}", pytrace=True)


def check_command(args, executable=None) -> None:
    tokens = _tokens(args) + ([os.fsdecode(executable)] if executable else [])
    for token in tokens:
        if _CODEX_NAME.match(Path(token).name):
            _block(f"執行 codex（{' '.join(tokens)[:200]}）")


def check_host(host: str | bytes | None) -> None:
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    host = (host or "").lower().rstrip(".")
    if any(host == h or host.endswith("." + h) for h in GEMINI_HOSTS):
        _block(f"連線 Gemini API（{host}）")


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    popen_init = subprocess.Popen.__init__

    def guarded_popen_init(self, args, *a, **kw):
        check_command(args, kw.get("executable"))
        popen_init(self, args, *a, **kw)

    subprocess.Popen.__init__ = guarded_popen_init

    def wrap_os(name: str, argv_index: int) -> None:
        original = getattr(os, name, None)
        if original is None:
            return

        def guarded(*args, **kwargs):
            check_command(args[argv_index] if len(args) > argv_index else [], args[0] if args else None)
            return original(*args, **kwargs)

        setattr(os, name, guarded)

    wrap_os("system", 0)
    for name in ("posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe"):
        wrap_os(name, 1)

    send = requests.adapters.HTTPAdapter.send

    def guarded_send(self, request, *args, **kwargs):
        check_host(urlsplit(request.url).hostname)
        return send(self, request, *args, **kwargs)

    requests.adapters.HTTPAdapter.send = guarded_send

    getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        check_host(host)
        return getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = guarded_getaddrinfo
