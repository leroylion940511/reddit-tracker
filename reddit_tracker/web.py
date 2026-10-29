"""本機綜合日報檢視器。

只綁定 127.0.0.1，提供 `site/daily/` 下已產生的日報 HTML；服務管理改用
`deploy/install_launchd.sh`。
"""

from __future__ import annotations

import webbrowser
from datetime import date, datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .config import get_settings
from .daily.newsroom_page import render_newsroom
from .daily.store import approve_story, hold_story
from .db import session_scope

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


@app.get("/daily/{edition_date}/newsroom", include_in_schema=False)
def newsroom_page(edition_date: date, variant: str = "mas", story: int | None = None) -> HTMLResponse:
    """編輯室回放。左邊稿件狀態，右邊訊息與 v1→v2 diff。"""
    if variant not in ("pipeline", "mas"):
        raise HTTPException(status_code=400, detail="variant 只允許 pipeline 或 mas")
    with session_scope() as session:
        html = render_newsroom(session, edition_date, variant, story)
    return HTMLResponse(html)


@app.api_route("/daily/{edition_date}/newsroom/decision", methods=["GET", "POST"], include_in_schema=False)
def newsroom_decision(
    edition_date: date, story_id: int, action: str, by: str, variant: str = "mas",
) -> RedirectResponse:
    """真人核准或 HOLD。參數走 query string（這個環境沒有 python-multipart）。"""
    if action not in ("approve", "hold"):
        raise HTTPException(status_code=400, detail="只能核准或 HOLD")
    now = datetime.now(timezone.utc)
    try:
        with session_scope() as session:
            if action == "approve":
                approve_story(session, story_id, by=by, now=now)
            else:
                from .daily.mas.protocol import post_message

                post_message(
                    session, run_variant=variant, edition_date=edition_date, sender="human", recipient="eic",
                    type="HOLD", now=now, story_id=story_id, payload={"by": by, "detail": "審核者 HOLD"},
                )
                hold_story(session, story_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(f"/daily/{edition_date.isoformat()}/newsroom?variant={variant}&story={story_id}", status_code=303)


def main() -> None:
    """以 `uv run python -m reddit_tracker.web` 啟動本機日報檢視器。"""
    url = "http://127.0.0.1:8765"
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
