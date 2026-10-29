"""數據欄：證交所 OpenAPI 收盤指數，數字直接取自資料、不經 LLM。"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

TWSE_MI_INDEX_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
WANTED_INDICES = ("發行量加權股價指數", "臺灣50指數")
STALE_LABEL = "資料更新延遲"
# 收盤日期距出刊日超過這麼多個交易日就標示延遲（E15）。06:00 出刊時最新的是前一個交易日收盤。
MAX_TRADING_DAYS_BEHIND = 1


def trading_days_between(close: date, edition: date) -> int:
    """`close` 之後到 `edition`（含）有幾個交易日。只排除週末，不含國定假日
    （連假後第一期會多標一次延遲，寧可多標）。"""
    days, day = 0, close
    while day < edition:
        day += timedelta(days=1)
        days += day.weekday() < 5
    return days


def is_stale(close: str | date | None, edition: date) -> bool:
    """數據欄是否延遲：收盤日距出刊日超過 `MAX_TRADING_DAYS_BEHIND` 個交易日；日期不明也算延遲。"""
    if not close:
        return True
    close_date = date.fromisoformat(close) if isinstance(close, str) else close
    return trading_days_between(close_date, edition) > MAX_TRADING_DAYS_BEHIND


def _roc_to_iso(roc: str) -> str | None:
    """證交所日期為民國年 YYYMMDD，例如 1151022 → 2026-10-22。"""
    if len(roc) != 7 or not roc.isdigit():
        return None
    return f"{int(roc[:3]) + 1911}-{roc[3:5]}-{roc[5:]}"


def fetch_market_box(*, timeout: float = 20.0) -> list[dict] | None:
    try:
        resp = requests.get(TWSE_MI_INDEX_URL, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json()
    except Exception:  # noqa: BLE001 — 數據欄取不到就不顯示，不能擋住出刊
        logger.warning("TWSE market box unavailable", exc_info=True)
        return None
    box = []
    for row in rows:
        if row.get("指數") not in WANTED_INDICES:
            continue
        sign = "-" if row.get("漲跌") == "-" else "+"
        # 漲跌百分比本身已帶負號，漲跌點數則沒有。
        pct = str(row.get("漲跌百分比", "")).lstrip("+-")
        box.append({
            "name": row["指數"],
            "close": row.get("收盤指數"),
            "change": f"{sign}{row.get('漲跌點數')}",
            "change_pct": f"{sign}{pct}%",
            "date": _roc_to_iso(row.get("日期", "")),
        })
    return box or None
