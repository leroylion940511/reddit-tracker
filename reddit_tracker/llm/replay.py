"""Replay provider：用 `request_hash` 找回錄好的 LLM 回應，不執行任何 binary、不連網。

手冊步驟 2／7：回歸測試與實驗不重新呼叫 LLM。每次真實呼叫都會把請求與回應寫進
`llm_records`（步驟 7 建表），之後用同一個 `request_hash` 重播。**找不到錄好的回應就
丟 `ReplayMissing`，絕不默默改呼叫真模型。**

`request_hash` = sha256(system prompt＋prompt＋model＋schema)，四者以 JSON 固定順序
序列化後再雜湊；prompt 是所有 user 訊息以空行相接（與 Codex 呼叫時送出的內容一致）。
步驟 7 寫入 `llm_records` 時必須用這裡的 `request_hash()`，兩邊才對得上。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ReplayMissing(LookupError):
    """沒有錄好的回應。呼叫端不得改用真模型。"""


@dataclass(frozen=True)
class ReplayResult:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None


def prompt_text(messages: list[dict]) -> str:
    return "\n\n".join(
        m["content"] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)
    )


def request_hash(*, system: str, prompt: str, model: str, schema: dict | None) -> str:
    canonical = json.dumps(
        [system, prompt, model, schema], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_records(path: str | Path) -> dict[str, str]:
    """讀錄好的回應 `{request_hash: response_text}`，只收 ok 的紀錄。

    支援兩種來源：JSON 檔（`[{"request_hash", "response_text", "ok"}, ...]`，回歸集 fixture 用）
    與含 `llm_records` 表的 SQLite 檔（步驟 7 的格式；用唯讀方式開）。
    """
    path = Path(path)
    if path.suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        return {r["request_hash"]: r["response_text"] for r in rows if r.get("ok", True)}
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT request_hash, response_text FROM llm_records"
            " WHERE ok = 1 AND request_hash IS NOT NULL AND response_text IS NOT NULL ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return dict(rows)  # 同一 hash 錄過多次時用最後一筆


class ReplayClient:
    """`complete()` 介面與 CodexClient 相同；`misses` 記下所有找不到的 request_hash。"""

    def __init__(self, records: Mapping[str, str], *, model: str) -> None:
        self.records = dict(records)
        self.model = model
        self.calls = 0
        self.misses: list[str] = []

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> ReplayResult:
        del max_output_tokens, temperature, json_mode
        self.calls += 1
        key = request_hash(system=system, prompt=prompt_text(messages), model=self.model, schema=json_schema)
        try:
            return ReplayResult(self.records[key])
        except KeyError:
            self.misses.append(key)
            raise ReplayMissing(f"沒有錄好的回應：request_hash={key}（model={self.model}）") from None
