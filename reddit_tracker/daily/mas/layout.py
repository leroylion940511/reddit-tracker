"""desk-v3 B：開放版面（MAS_OPEN_LAYOUT）的護欄設定。預設關閉時 run_mas 不讀這裡。"""

from __future__ import annotations

from dataclasses import dataclass

from ...config import get_settings
from ..scoring import SECTION_QUOTAS


@dataclass(frozen=True)
class LayoutLimits:
    enabled: bool
    section_min: int
    section_max: int
    edition_max: int


def check_limits(section_min: int, section_max: int, edition_max: int, sections: int = len(SECTION_QUOTAS)) -> list[str]:
    """回傳護欄設定的問題（空清單＝合法）。"""
    problems = []
    if section_min < 0:
        problems.append(f"MAS_SECTION_MIN 不能小於 0：{section_min}")
    if section_max < 1:
        problems.append(f"MAS_SECTION_MAX 至少要 1：{section_max}")
    if section_min > section_max:
        problems.append(f"MAS_SECTION_MIN（{section_min}）不能大於 MAS_SECTION_MAX（{section_max}）")
    if edition_max < sections * max(section_min, 0):
        problems.append(f"MAS_EDITION_MAX（{edition_max}）小於各版下限總和（{sections}×{section_min}）")
    if edition_max < 1:
        problems.append(f"MAS_EDITION_MAX 至少要 1：{edition_max}")
    return problems


def layout_limits(settings=None) -> LayoutLimits:
    """從設定讀護欄。開關開啟但設定不合法時丟 ValueError（不要靜默出一份怪版面）；
    關閉時不驗證，回傳 enabled=False。"""
    settings = settings or get_settings()
    limits = LayoutLimits(
        enabled=bool(settings.mas_open_layout),
        section_min=int(settings.mas_section_min),
        section_max=int(settings.mas_section_max),
        edition_max=int(settings.mas_edition_max),
    )
    if limits.enabled:
        problems = check_limits(limits.section_min, limits.section_max, limits.edition_max)
        if problems:
            raise ValueError("；".join(problems))
    return limits
