"""回放頁：稿件狀態、訊息、版本 diff、page_plans 差異。唯讀，核准走另一個 POST。"""

from __future__ import annotations

import difflib
import json
from datetime import date
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentMessage, PagePlan, Story, StoryVersion

SECTION_LABELS = {"taiwan": "台灣", "world": "國際", "tech": "科技", "front": "頭版"}


def render_newsroom(
    session: Session,
    edition_date: date,
    run_variant: str = "mas",
    focus_story_id: int | None = None,
) -> str:
    stories = session.scalars(
        select(Story)
        .where(Story.edition_date == edition_date, Story.run_variant == run_variant)
        .order_by(Story.section, Story.id)
    ).all()
    plans = session.scalars(
        select(PagePlan)
        .where(PagePlan.edition_date == edition_date, PagePlan.run_variant == run_variant)
        .order_by(PagePlan.plan_version)
    ).all()
    rows = []
    for story in stories:
        version = session.scalar(
            select(StoryVersion).where(StoryVersion.story_id == story.id).order_by(StoryVersion.version.desc())
        )
        status = version.status if version else "—"
        label = SECTION_LABELS.get(story.section, story.section)
        headline = version.headline if version else "（尚無稿）"
        rows.append(
            f'<li><a href="?variant={escape(run_variant)}&story={story.id}">'
            f'{escape(label)}｜{escape(headline)}</a> '
            f'<span class="status" data-story-id="{story.id}">{escape(status)}</span></li>'
        )
    focus = ""
    if focus_story_id is not None:
        focus = _focus(session, edition_date, run_variant, focus_story_id)
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>回放 {edition_date.isoformat()}</title>
<style>
body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:#f6f3ec;color:#1c1916}}
.top,.cols{{padding:16px 20px}}.cols{{display:flex;gap:24px}}
.left{{width:320px}}.right{{flex:1;min-width:0}}
pre{{white-space:pre-wrap;background:#fff;padding:12px;border:1px solid #ddd}}
.status{{color:#8a1c1c}} form{{margin-top:12px}}
@media (max-width:420px){{.cols{{display:block}}.left{{width:auto}}}}
</style></head><body>
<section class="top"><h1>編輯室回放 {edition_date.isoformat()} · {escape(run_variant)}</h1>
<h2>page_plans</h2>{_plan_diffs(plans)}</section>
<div class="cols"><aside class="left"><h2>稿件</h2><ul>{"".join(rows) or "<li>這一期還沒有稿</li>"}</ul></aside>
<main class="right">{focus or "<p>點左邊一則稿，看訊息與版本 diff。</p>"}</main></div>
</body></html>"""


def _plan_diffs(plans: list[PagePlan]) -> str:
    if not plans:
        return "<p>還沒有版面計畫。</p>"
    blocks = []
    previous = None
    for plan in plans:
        current = json.dumps(plan.slots, ensure_ascii=False, sort_keys=True, indent=2)
        if previous is None:
            diff = current
        else:
            diff = "\n".join(difflib.unified_diff(
                previous.splitlines(), current.splitlines(),
                fromfile=f"plan v{plan.plan_version - 1}", tofile=f"plan v{plan.plan_version}", lineterm="",
            )) or "（與上一版相同）"
        blocks.append(f"<h3>v{plan.plan_version}</h3><pre>{escape(diff)}</pre>")
        previous = current
    return "".join(blocks)


def _focus(session: Session, edition_date: date, run_variant: str, story_id: int) -> str:
    story = session.get(Story, story_id)
    if story is None:
        return "<p>找不到這則稿。</p>"
    versions = session.scalars(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version)
    ).all()
    messages = session.scalars(
        select(AgentMessage)
        .where(
            AgentMessage.edition_date == edition_date,
            AgentMessage.run_variant == run_variant,
            AgentMessage.story_id == story_id,
        )
        .order_by(AgentMessage.created_at, AgentMessage.id)
    ).all()
    lines = []
    for message in messages:
        when = message.created_at.isoformat(timespec="seconds")
        detail = ""
        if isinstance(message.payload, dict):
            detail = str(message.payload.get("detail") or message.payload.get("why") or "")
        lines.append(
            f"<tr><td>{escape(when)}</td><td>{escape(message.sender_role)}</td>"
            f"<td>{escape(message.type)}</td><td>{escape(message.status)}</td><td>{escape(detail)}</td></tr>"
        )
    diff = ""
    if len(versions) >= 2:
        before, after = versions[-2], versions[-1]
        diff = "\n".join(difflib.unified_diff(
            (before.body or "").splitlines(), (after.body or "").splitlines(),
            fromfile=f"v{before.version}", tofile=f"v{after.version}", lineterm="",
        ))
    latest = versions[-1] if versions else None
    form = ""
    if latest is not None and latest.status != "approved":
        form = (
            f'<form method="get" action="/daily/{edition_date.isoformat()}/newsroom/decision">'
            f'<input type="hidden" name="story_id" value="{story_id}">'
            f'<input type="hidden" name="variant" value="{escape(run_variant)}">'
            f'<label>審核者 <input name="by" required></label> '
            f'<button name="action" value="approve">核准</button> '
            f'<button name="action" value="hold">HOLD</button></form>'
            f'<p>審核者只能核准或 HOLD，不能在這裡改稿。</p>'
        )
    return (
        f"<h2>story {story_id}</h2>"
        f"<table><tr><th>時間</th><th>角色</th><th>type</th><th>狀態</th><th>內容</th></tr>"
        f"{''.join(lines)}</table><h3>v1→v2 diff</h3><pre>{escape(diff or '（還沒有下一版）')}</pre>{form}"
    )
