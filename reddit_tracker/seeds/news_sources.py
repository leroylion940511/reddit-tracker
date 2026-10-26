"""多來源綜合日報的來源登錄表 loader。

登錄表本體在 `news_sources.yaml`；欄位定義見 docs/v5/SOURCE_REGISTRY.md。
這裡只負責讀檔、驗證與組出實際請求網址，不碰 DB。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit

import yaml
from pydantic import BaseModel, model_validator

Tier = Literal["T1", "T2", "T3", "T4"]
Method = Literal["rss", "rsshub", "json", "csv", "reddit"]

DEFAULT_REGISTRY_PATH = Path(__file__).with_name("news_sources.yaml")


class NewsSource(BaseModel):
    id: str
    name: str
    section: str
    tier: Tier
    method: Method
    url: str
    lang: str
    interval_min: int = 60
    enabled: bool = True
    requires_key: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_url_shape(self) -> NewsSource:
        if self.method == "rsshub" and not self.url.startswith("/"):
            raise ValueError(f"{self.id}: rsshub url 必須是以 / 開頭的路由")
        if self.method in ("rss", "json", "csv") and urlsplit(self.url).scheme != "https":
            raise ValueError(f"{self.id}: {self.method} url 必須是 https 網址")
        if self.method == "reddit" and "/" in self.url:
            raise ValueError(f"{self.id}: reddit url 只填 subreddit 名稱")
        return self

    def request_url(self, rsshub_base_url: str, rsshub_access_key: str | None) -> str:
        """組出實際請求網址；rsshub 會補上 base 與 key。"""
        if self.method == "rsshub":
            url = rsshub_base_url.rstrip("/") + quote(self.url, safe="/:=&?")
            if rsshub_access_key:
                url += ("&" if "?" in url else "?") + urlencode({"key": rsshub_access_key})
            return url
        if self.method == "reddit":
            return f"https://www.reddit.com/r/{self.url}/new/.rss"
        return self.url


class SourceRegistry(BaseModel):
    version: int
    sections: dict[str, str]
    sources: list[NewsSource]

    @model_validator(mode="after")
    def _check_consistency(self) -> SourceRegistry:
        seen: set[str] = set()
        for source in self.sources:
            if source.id in seen:
                raise ValueError(f"來源 id 重複：{source.id}")
            seen.add(source.id)
            if source.section not in self.sections:
                raise ValueError(f"{source.id}: 未定義的 section {source.section}")
        return self

    def enabled(self) -> list[NewsSource]:
        return [s for s in self.sources if s.enabled]


def load_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> SourceRegistry:
    with Path(path).open(encoding="utf-8") as fh:
        return SourceRegistry.model_validate(yaml.safe_load(fh))
