"""依「模型」計數的每日 LLM 額度（手冊步驟 1、6.7）。

同一個模型的所有用途（日報撰稿、編輯會議、之後的 MAS 角色）共用一個每日計數；
每一次實際送出的嘗試（含重試）都扣一格。計數存在 state 檔、以檔案鎖跨 process
共用，日界線採太平洋時間（與 Gemini 免費層一致）。停用的用途不要把上限設 0，
而是根本不建立那個 client。

`purpose_limits` 可以替個別用途再加一道上限（仍算在模型總數裡）：P 組影子版用
`SHADOW_PURPOSE`，上限是 `DAILY_SHADOW_LLM_LIMIT`，保證 M 組至少還有「總上限 − 影子上限」格。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
# P 組影子版（手冊步驟 10、12）的額度用途名；跟 M 組的 daily／角色用途分開計上限。
SHADOW_PURPOSE = "shadow"


class QuotaExhausted(RuntimeError):
    """本機每日額度用完；呼叫端應降級（模板稿），不得繞過。"""


class ModelQuotaGuard:
    """以 model 字串為鍵的檔案型額度計數；`requests_per_minute` 為 None 時不限速。"""

    def __init__(
        self,
        *,
        state_path: str | Path,
        daily_limit: int,
        requests_per_minute: int | None = None,
        purpose_limits: Mapping[str, int] | None = None,
    ) -> None:
        if daily_limit < 1 or (requests_per_minute is not None and requests_per_minute < 1):
            raise ValueError("daily limit and RPM must both be positive")
        if any(limit < 1 for limit in (purpose_limits or {}).values()):
            raise ValueError("purpose limits must be positive")
        self.state_path = Path(state_path)
        self.lock_path = Path(f"{state_path}.lock")
        self.daily_limit = daily_limit
        self.requests_per_minute = requests_per_minute
        self.purpose_limits = dict(purpose_limits or {})

    @staticmethod
    def _day() -> str:
        return datetime.now(PACIFIC).date().isoformat()

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - production target is macOS
            yield
            return

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            value = {}
        day = self._day()
        if not isinstance(value, dict) or value.get("day") != day:
            return {"day": day, "models": {}, "purposes": {}, "events": {}}
        return {
            "day": day,
            **{
                key: value.get(key) if isinstance(value.get(key), dict) else {}
                for key in ("models", "purposes", "events")
            },
        }

    def _save(self, value: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temp.replace(self.state_path)

    def used(self, model: str) -> int:
        with self._lock():
            return int(self._load()["models"].get(model, 0))

    def used_by(self, model: str, purpose: str) -> int:
        with self._lock():
            return int(self._load()["purposes"].get(model, {}).get(purpose, 0))

    def acquire(self, *, model: str, purpose: str) -> None:
        """預扣一格；超過每日上限或用途上限就拋 QuotaExhausted，超過 RPM 就短暫等待。"""
        while True:
            now = time.time()
            with self._lock():
                state = self._load()
                events = [
                    e for e in state["events"].get(model, []) if isinstance(e, (int, float)) and e > now - 60
                ]
                state["events"][model] = events
                used = int(state["models"].get(model, 0))
                if used >= self.daily_limit:
                    self._save(state)
                    raise QuotaExhausted(f"{model} 本機每日額度 {self.daily_limit} 已用完（{purpose}）")
                cap = self.purpose_limits.get(purpose)
                if cap is not None and int(state["purposes"].get(model, {}).get(purpose, 0)) >= cap:
                    self._save(state)
                    raise QuotaExhausted(f"{model} 用途 {purpose} 的每日上限 {cap} 已用完")
                if self.requests_per_minute is None or len(events) < self.requests_per_minute:
                    if self.requests_per_minute is not None:
                        events.append(now)
                    state["models"][model] = used + 1
                    per_model = state["purposes"].setdefault(model, {})
                    per_model[purpose] = int(per_model.get(purpose, 0)) + 1
                    self._save(state)
                    return
                wait_seconds = max(0.1, min(events) + 60 - now)
                self._save(state)
            logger.info("%s local RPM limit reached; waiting %.1fs", model, wait_seconds)
            time.sleep(wait_seconds)


def purpose_limits_from_settings(settings) -> dict[str, int]:
    """設定裡的用途上限（目前只有 P 組影子版）。"""
    return {SHADOW_PURPOSE: int(getattr(settings, "daily_shadow_llm_limit", 12))}
