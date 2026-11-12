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
@app.get("/daily/{edition_date}.html", include_in_schema=False)  # 日報內的期別連結是相對的 YYYY-MM-DD.html；裝飾器由下往上註冊，要比上一行先
def daily_edition_page(edition_date: date | None = None) -> FileResponse:
    """v2.0 綜合日報的網頁版；不帶日期時開最新一期。"""
    site = Path(get_settings().daily_site_dir)
    if edition_date is None:
        pages = sorted(site.glob("*.html"))
        if not pages:
            raise HTTPException(status_code=404, detail="尚未產生任何日報")
        page = pages[-1]
        try:
            edition_date = date.fromisoformat(page.stem)
        except ValueError:  # 例如 index.html（期別列表），不加回放入口
            return FileResponse(page)
    else:
        page = site / f"{edition_date.isoformat()}.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="這一天沒有日報")
    return HTMLResponse(_with_newsroom_link(page.read_text(encoding="utf-8"), edition_date))


def _newsroom_bar(edition_date: date) -> str:
    d = edition_date.isoformat()
    return (
        '<nav id="rt-newsroom-bar" style="position:fixed;right:16px;bottom:16px;z-index:9999;'
        'display:flex;gap:8px;font:14px/1.4 system-ui,-apple-system,\'PingFang TC\',sans-serif">'
        f'<a href="/daily/{d}/newsroom?variant=mas" style="background:#7a2a12;color:#fff;padding:8px 14px;'
        'border-radius:20px;text-decoration:none;box-shadow:0 2px 6px rgba(0,0,0,.25)">編輯室回放（M 組）</a>'
        f'<a href="/daily/{d}/newsroom?variant=pipeline" style="background:#fff;color:#7a2a12;padding:8px 14px;'
        'border:1px solid #7a2a12;border-radius:20px;text-decoration:none">P 組</a></nav>'
    )


def _with_newsroom_link(html: str, edition_date: date) -> str:
    """檔案本身不改（Telegram 附的是同一份），只在網頁版注入回放入口。"""
    bar = _newsroom_bar(edition_date)
    idx = html.lower().rfind("</body>")
    return html[:idx] + bar + html[idx:] if idx != -1 else html + bar


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
    from .daily.run import refresh_after_review

    refresh_after_review(edition_date, scope=session_scope)  # 網頁版跟著核准狀態重畫，不重送 Telegram
    return RedirectResponse(f"/daily/{edition_date.isoformat()}/newsroom?variant={variant}&story={story_id}", status_code=303)


def main() -> None:
    """以 `uv run python -m reddit_tracker.web` 啟動本機日報檢視器。"""
    url = "http://127.0.0.1:8765"
    webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
