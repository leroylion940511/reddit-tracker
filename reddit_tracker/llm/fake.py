"""離線 fake provider：不連網、不執行任何 binary、不扣額度，輸出固定可重現。

給開發與測試用（手冊 6.7 第 1 點：開發時用 fake 或錄下來的回應）。編輯會議一律回
「沒有同一事件」；撰稿把每則第一篇證據的標題與摘要改排成稿件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FakeResult:
    content: str
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    cached_tokens: int | None = 0


class FakeClient:
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
        temperature: float,
        json_mode: bool = False,
        json_schema: dict | None = None,
    ) -> FakeResult:
        del system, max_output_tokens, temperature, json_mode
        self.calls += 1
        properties = (json_schema or {}).get("properties", {})
        if "groups" in properties:
            return FakeResult(json.dumps({"groups": []}))
        prompt = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        # DailyWriter 的撰稿 prompt 最後一段是證據 JSON。
        try:
            payload = json.loads(prompt.rsplit("\n\n", 1)[-1])
        except ValueError:
            payload = {}
        stories = []
        for story in payload.get("stories", []):
            lead = (story.get("evidence") or [{}])[0]
            outlet = lead.get("outlet", "")
            stories.append({
                "id": story["id"],
                "headline": lead.get("title", ""),
                "deck": "",
                "body": f"據{outlet}報導：{lead.get('summary') or lead.get('title', '')}",
                "why_it_matters": "",
            })
        return FakeResult(json.dumps({"stories": stories}, ensure_ascii=False))
