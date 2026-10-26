"""本機綜合日報檢視器。

只綁定 127.0.0.1，提供 `site/daily/` 下已產生的日報 HTML；服務管理改用
`deploy/install_launchd.sh`。
"""

from __future__ import annotations

import webbrowser
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .config import get_settings

app = FastAPI(title="AI 綜合日報", docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/daily/")


@app.get("/daily/", include_in_schema=False)
@app.get("/daily/{edition_date}", include_in_schema=False)
def daily_edition_page(edition_date: date | None = None) -> FileResponse:
    """v2.0 綜合日報的網頁版；不帶日期時開最新一期。"""
    site = Path(get_settings().daily_site_dir)
    if edition_date is None:
        pages = sorted(site.glob("*.html"))
        if not pages:
            raise HTTPException(status_code=404, detail="尚未產生任何日報")
        return FileResponse(pages[-1])
    page = site / f"{edition_date.isoformat()}.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="這一天沒有日報")
    return FileResponse(page)


def main() -> None:
    """以 `uv run python -m reddit_tracker.web` 啟動本機日報檢視器。"""
    url = "http://127.0.0.1:8765"
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
