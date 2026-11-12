"""編輯室 3D 回放頁：`office.html` 模板＋`replay.build_replay` 的資料。唯讀，不能在這頁核准。

three.js 預設從 CDN 載入（鎖版本）；`reddit_tracker/daily/vendor/three.module.js` 存在時改用本機那份，
沒有網路也能展示。3D 載入失敗時頁面仍可用右側的逐步紀錄。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from .replay import build_replay

TEMPLATE = Path(__file__).with_name("office.html")
VENDOR_THREE = Path(__file__).with_name("vendor") / "three.module.js"
THREE_CDN = "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"
THREE_LOCAL = "/daily/_static/three.module.js"
VARIANT_LABELS = {"mas": "M 組（MAS 編輯室）", "pipeline": "P 組（流水線）"}


def render_office(session: Session, edition_date: date, run_variant: str = "mas") -> str:
    data = build_replay(session, edition_date, run_variant)
    other = "pipeline" if run_variant == "mas" else "mas"
    # 資料放在 <script type="application/json"> 裡：把 "</" 拆開，新聞內容就關不掉這個標籤
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, value in {
        "__DATE__": edition_date.isoformat(),
        "__VARIANT_LABEL__": VARIANT_LABELS[run_variant],
        "__OTHER_VARIANT__": other,
        "__OTHER_LABEL__": VARIANT_LABELS[other],
        "__VARIANT__": run_variant,
        "__THREE_URL__": THREE_LOCAL if VENDOR_THREE.is_file() else THREE_CDN,
    }.items():
        html = html.replace(key, value)
    return html.replace("__REPLAY_JSON__", payload)
