"""本機綜合日報檢視器。

只綁定 127.0.0.1，提供 `site/daily/` 下已產生的日報 HTML；服務管理改用
`deploy/install_launchd.sh`。
"""

from __future__ import annotations

import webbrowser
from urllib.parse import parse_qs
from datetime import date, datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from .config import get_settings
from .daily.newsroom_page import render_newsroom
from .daily.office_page import VENDOR_THREE, render_office
from .daily.replay import build_replay
from .daily.store import approve_story, hold_story
from .db import session_scope

app = FastAPI(title="AI 綜合日報", docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/daily/")


@app.get("/daily/_static/three.module.js", include_in_schema=False)
def vendored_three() -> FileResponse:
    """本機那份 three.js（有放才有；沒放時 3D 頁從 CDN 載入）。要比 /daily/{edition_date} 先註冊。"""
    if not VENDOR_THREE.is_file():
        raise HTTPException(status_code=404, detail="沒有本機的 three.js")
    return FileResponse(VENDOR_THREE, media_type="text/javascript")


@app.get("/daily/index.html", include_in_schema=False)
def daily_index_page() -> FileResponse:
    """期別列表。要比下面的 `{edition_date}.html` 先註冊，否則 `index` 會被當成日期、回 422。"""
    page = Path(get_settings().daily_site_dir) / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="尚未產生期別列表")
    return FileResponse(page)


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
    """貼在視窗底部的一條，不蓋住文末來源。只加在網頁版，不寫進 Telegram 附件。"""
    d = edition_date.isoformat()
    font = "16px/1.35 system-ui,-apple-system,'PingFang TC','Noto Sans TC','Microsoft JhengHei',sans-serif"
    return (
        "<style>body{padding-bottom:96px}</style>"
        f'<nav id="rt-newsroom-bar" style="position:fixed;left:0;right:0;bottom:0;z-index:9999;'
        f"display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;align-items:center;"
        f"padding:10px 14px;background:#14181e;color:#f4f1ea;font:{font}\">"
        '<span style="margin-right:auto;font-weight:700">看這一期怎麼寫出來</span>'
        f'<a href="/daily/{d}/newsroom/office?variant=mas" style="background:#b0112a;color:#fff;'
        'padding:8px 14px;text-decoration:none;font-weight:700">3D 編輯室</a>'
        f'<a href="/daily/{d}/newsroom?variant=mas" style="background:#f4f1ea;color:#14181e;'
        'padding:8px 14px;text-decoration:none;font-weight:700">回放與核准</a>'
        f'<a href="/daily/{d}/newsroom?variant=pipeline" style="color:#f4f1ea;padding:8px 14px;'
        'text-decoration:none;border:1px solid #8b939e">P 組</a></nav>'
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


def _check_variant(variant: str) -> None:
    if variant not in ("pipeline", "mas"):
        raise HTTPException(status_code=400, detail="variant 只允許 pipeline 或 mas")


@app.get("/daily/{edition_date}/newsroom/office", include_in_schema=False)
def newsroom_office(edition_date: date, variant: str = "mas") -> HTMLResponse:
    """編輯室 3D 回放：把這一期的收集、角色呼叫、訊息、版本、版面一步一步演出來。唯讀。"""
    _check_variant(variant)
    with session_scope() as session:
        html = render_office(session, edition_date, variant)
    return HTMLResponse(html)


@app.get("/daily/{edition_date}/newsroom/replay.json", include_in_schema=False)
def newsroom_replay(edition_date: date, variant: str = "mas") -> JSONResponse:
    """3D 回放用的時間線資料（docs/v5/DAILY_EDITION.md「回放時間線」）。"""
    _check_variant(variant)
    with session_scope() as session:
        return JSONResponse(build_replay(session, edition_date, variant))


@app.post("/daily/{edition_date}/newsroom/decision", include_in_schema=False)
async def newsroom_decision(edition_date: date, request: Request) -> RedirectResponse:
    """真人核准或 HOLD。只收 POST：GET 會被瀏覽器預載或誤點觸發寫入（2026-11-26 起拿掉 GET）。

    參數可放 urlencoded 表單或 query string；表單自己解析，不需要 python-multipart。
    """
    fields = {k: v[-1] for k, v in parse_qs((await request.body()).decode("utf-8")).items()}
    fields = {**dict(request.query_params), **fields}
    try:
        story_id = int(fields["story_id"])
        action, by = fields["action"], fields["by"].strip()
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="缺 story_id／action／by") from exc
    variant = fields.get("variant", "mas")
    if not by:
        raise HTTPException(status_code=400, detail="缺審核者")
    _check_variant(variant)
    return apply_decision(edition_date, story_id=story_id, action=action, by=by, variant=variant)


def apply_decision(edition_date: date, *, story_id: int, action: str, by: str, variant: str = "mas") -> RedirectResponse:
    """核准或 HOLD 一篇稿，重畫網頁版（不重送 Telegram），303 回到該稿。"""
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
