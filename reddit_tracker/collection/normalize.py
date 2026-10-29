"""收集層的純函式：網址正規化、標題指紋、發布時間判斷、摘要清理。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "ref", "from", "feature", "cmpid", "ocid", "spm"}
MIN_VALID_PUBLISHED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
MAX_FUTURE_SKEW = timedelta(hours=1)
MIN_FINGERPRINT_CHARS = 8
SUMMARY_MAX_CHARS = 1000

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
# 標題開頭的分類標籤：央廣的「[兩岸]」、某些媒體的「【政治】」；轉載稿常只差這個標籤。
_LEADING_LABEL_RE = re.compile(r"^\s*(?:\[[^\[\]]{1,12}\]|【[^【】]{1,12}】)\s*")


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    )
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), urlencode(query), ""))


def strip_title_labels(title: str | None) -> str:
    """去掉開頭的 `[..]`／`【..】` 分類標籤（可能連續好幾個）。"""
    text = title or ""
    while True:
        stripped = _LEADING_LABEL_RE.sub("", text, count=1)
        if stripped == text:
            return text
        text = stripped


def title_key(title: str | None) -> str:
    """去標籤、NFKC、小寫後只保留字母與數字；指紋與轉載比對共用。"""
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", strip_title_labels(title)).lower()
        if unicodedata.category(ch)[0] in ("L", "N")
    )


def title_fingerprint(title: str | None) -> str | None:
    """去掉開頭標籤、只保留字母與數字後取 sha1；太短的標題（如「直播更新」）不比對，避免誤判重複。

    「[兩岸] 洪秀柱赴中…」與「洪秀柱赴中…」的指紋相同（E10）。
    """
    if not title:
        return None
    normalized = title_key(title)
    if len(normalized) < MIN_FINGERPRINT_CHARS:
        return None
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def item_key(guid: str | None, canonical_url: str) -> str:
    return hashlib.sha1((guid or canonical_url).encode("utf-8")).hexdigest()


def resolve_published_at(
    parsed: datetime | None, seen_at: datetime, offset_hours: float = 0
) -> tuple[datetime, bool]:
    """回傳 (published_at, estimated)。不可信的時間一律以首次收錄時間代替。"""
    if parsed is None:
        return seen_at, True
    adjusted = parsed + timedelta(hours=offset_hours)
    if adjusted < MIN_VALID_PUBLISHED_AT or adjusted > seen_at + MAX_FUTURE_SKEW:
        return seen_at, True
    return adjusted, False


def clean_summary(html: str | None) -> str | None:
    if not html:
        return None
    text = _SPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()
    return text[:SUMMARY_MAX_CHARS] or None
