"""LLM provider 抽象 + Haiku 評分 / Opus 摘要 / 問答（M3+）。

對應 v3 的 `llm/` 子套件，但只搬 M3 評分階段真的會用到的部分：
- `base.py`：abstract `LLMScorer` + dataclass `HaikuVerdict`
- `haiku.py`：Anthropic Claude Haiku 4.5 評分實作
- `fake.py`：給 test / dev 用的可控 fake
- `factory.py`：依環境變數切實作

Opus 摘要與問答留待 M4 / M6 再加。
"""

from .base import HaikuVerdict, LLMScorer
from .factory import build_scorer
from .fake import FakeScorer
from .haiku import HaikuScorer
from .minimax import MinimaxScorer

__all__ = [
    "FakeScorer",
    "HaikuScorer",
    "HaikuVerdict",
    "LLMScorer",
    "MinimaxScorer",
    "build_scorer",
]
