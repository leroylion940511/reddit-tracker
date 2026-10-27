"""Codex CLI provider：用本機 ChatGPT 訂閱登入的 `codex exec` 做單次 completion。

Codex 是 agent，不是單純的 completion API；而 prompt 裡的新聞標題與摘要是外部
不可信內容。所以每次呼叫都：在空的暫存目錄、read-only sandbox 執行，忽略使用者
config／rules，關掉 shell、code mode、子 agent、外掛等所有能碰到本機的工具，
並拒絕任何含有本專案機密值的輸出。
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger(__name__)

# 只留 completion 需要的部分；新版 CLI 若新增工具類 feature，要在這裡補關。
_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "code_mode_host", "multi_agent", "apps", "plugins",
    "memories", "browser_use", "in_app_browser", "computer_use", "skill_search",
    "tool_suggest", "sleep_tool", "goals", "image_generation", "view_image",
)


class CodexError(RuntimeError):
    """codex exec 失敗、逾時或回應不能安全使用。"""


@dataclass(frozen=True)
class CodexResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


def _usage(events: str) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return usage


class CodexClient:
    def __init__(
        self,
        *,
        binary: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self.binary = binary or settings.codex_bin
        self.model = model or settings.codex_model
        self.reasoning_effort = reasoning_effort or settings.codex_reasoning_effort
        self.timeout = timeout if timeout is not None else settings.codex_timeout_seconds
        self._secrets = [
            s for s in (settings.telegram_bot_token, settings.gemini_api_key, settings.rsshub_access_key)
            if s and len(s) >= 8
        ]

    def command(self, *, workdir: Path, schema_path: Path | None, output_path: Path) -> list[str]:
        cmd = [
            self.binary, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
            "--ignore-user-config", "-s", "read-only", "-C", str(workdir), "-m", self.model,
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"', "-c", 'web_search="disabled"',
        ]
        for feature in _DISABLED_FEATURES:
            cmd += ["-c", f"features.{feature}=false"]
        if schema_path is not None:
            cmd += ["--output-schema", str(schema_path)]
        return cmd + ["-o", str(output_path), "--json", "-"]

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> CodexResult:
        # codex exec 沒有 system／temperature／token 上限參數；system 併入 prompt 開頭。
        del max_output_tokens, temperature
        turns = [m["content"] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
        if not turns:
            raise ValueError("Codex requires at least one user message")
        prompt = f"{system}\n\n" + "\n\n".join(turns)
        if json_mode and json_schema is None:
            prompt += "\n\n只輸出 JSON。"

        with tempfile.TemporaryDirectory(prefix="reddit-tracker-codex-") as tmp:
            root = Path(tmp)
            workdir = root / "work"
            workdir.mkdir()
            schema_path = None
            if json_schema is not None:
                schema_path = root / "schema.json"
                schema_path.write_text(json.dumps(json_schema), encoding="utf-8")
            output_path = root / "out.txt"
            try:
                proc = subprocess.run(
                    self.command(workdir=workdir, schema_path=schema_path, output_path=output_path),
                    input=prompt, capture_output=True, text=True, timeout=self.timeout, cwd=workdir,
                )
            except FileNotFoundError as exc:
                raise CodexError(f"找不到 codex：{self.binary}") from exc
            except subprocess.TimeoutExpired as exc:
                raise CodexError(f"codex exec 超過 {self.timeout:.0f} 秒") from exc
            if proc.returncode != 0:
                raise CodexError(f"codex exec exit {proc.returncode}：{proc.stderr.strip()[-300:]}")
            try:
                content = output_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise CodexError("codex exec 沒有輸出最後訊息") from exc
        if not content:
            raise CodexError("codex exec 回傳空白")
        if any(secret in content for secret in self._secrets):
            raise CodexError("codex 輸出含有本機機密，丟棄")
        usage = _usage(proc.stdout)
        logger.info(
            "codex completion: model=%s input=%s cached=%s output=%s",
            self.model, usage.get("input_tokens"), usage.get("cached_input_tokens"), usage.get("output_tokens"),
        )
        return CodexResult(
            content=content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_tokens=usage.get("cached_input_tokens"),
        )
