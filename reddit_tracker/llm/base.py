"""LLM 評分介面 + 共用 dataclass。

`HaikuVerdict` 是評分層唯一的跨層資料結構。任何 scorer 實作必須吐這個。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import CandidatePost


@dataclass(frozen=True)
class HaikuVerdict:
    """企劃書 §4.2 第二層 — 五軸 + verdict + reason。

    所有分數欄位範圍 [0.0, 1.0]，prompt 端強制 schema。
    `verdict` 為 'track' / 'skip'。
    """

    story_potential: float    # 是否有「事件展開」的潛力
    emotional_pull: float     # 情緒拉力（共鳴 / 反差 / 反諷）
    grassroots: float         # 素人輪廓符合度（基於 karma）
    novelty: float            # 新穎 / 跳脫日常
    authenticity: float       # 真實性（非廣告 / 釣魚）
    verdict: str              # 'track' or 'skip'
    reason: str               # 1-2 句中文簡述

    # cost 追蹤（寫進 scoring_records.cost_usd 與 llm_records）
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLMScorer(ABC):
    @abstractmethod
    def score(self, post: CandidatePost) -> HaikuVerdict:
        """對單篇 candidate 評分。失敗請 raise，不要回 None。

        ScoringService 會 catch 並寫 stage='haiku' passed=False 的 row。
        """


__all__ = ["HaikuVerdict", "LLMScorer"]
