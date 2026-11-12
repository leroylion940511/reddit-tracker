"""回放頁：稿件狀態、訊息、版本 diff、page_plans 差異。唯讀，核准走另一個 POST。"""

from __future__ import annotations

import difflib
import json
from datetime import date, datetime, timezone
from html import escape

from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AgentMessage, PagePlan, Story, StoryVersion

SECTION_LABELS = {
    "taiwan": "台灣", "world": "國際", "tech": "科技", "front": "頭版", "culture": "文化",
    "life_env": "生活環境", "science_health": "科學健康", "sports": "體育",
}
STATUS_LABELS = {
    "draft": "草稿", "checked": "已查核待核准", "approved": "已核准", "challenged": "有異議",
    "hold": "HOLD", "held": "HOLD",
}
TYPE_LABELS = {
    "PITCH": "提案", "CHALLENGE": "質疑", "REQUEST_REVISION": "要求修稿", "REVISION_DONE": "修稿完成",
    "REBUT": "反駁", "HOLD": "扣稿 HOLD", "RELEASE": "解除 HOLD", "PAGE_OBJECTION": "版面異議",
    "DECISION": "主編決定",
}
TAIPEI = ZoneInfo("Asia/Taipei")
CSS = """
body{margin:0;font:15px/1.6 system-ui,-apple-system,"PingFang TC",sans-serif;background:#f6f3ec;color:#1c1916}
.top,.cols{padding:16px 20px;max-width:1200px;margin:0 auto}
.cols{display:flex;gap:24px;align-items:flex-start}
.left{width:340px;flex:none}.right{flex:1;min-width:0}
h1{font-size:22px;margin:0 0 8px}h2{font-size:18px;margin:18px 0 8px;border-bottom:2px solid #d8d0bf;padding-bottom:4px}
h3{font-size:15px;margin:14px 0 6px}
a{color:#7a2a12}
pre{white-space:pre-wrap;word-break:break-word;background:#fff;padding:12px;border:1px solid #ddd;font-size:13px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:14px}
th,td{border:1px solid #ddd;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#ece6d6;white-space:nowrap}
.tablewrap{overflow-x:auto}
ul.stories{list-style:none;margin:0;padding:0}
ul.stories li{background:#fff;border:1px solid #ddd;border-radius:6px;padding:8px 10px;margin-bottom:8px}
.sec{display:inline-block;background:#ece6d6;border-radius:3px;padding:0 6px;font-size:12px;margin-right:4px}
.status{color:#8a1c1c;font-size:13px;white-space:nowrap}.status.ok{color:#1c6b2a}
.muted{color:#7a7468;font-size:13px}
details{margin:8px 0}summary{cursor:pointer;color:#7a2a12}
form{margin-top:12px}input{font:inherit;padding:2px 6px}button{font:inherit;padding:3px 12px}
@media (max-width:700px){.cols{display:block}.left{width:auto}.top,.cols{padding:12px}}
"""


def _taipei(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TAIPEI).strftime("%m-%d %H:%M:%S")


def _detail(message: AgentMessage) -> str:
    if isinstance(message.payload, dict):
        return str(message.payload.get("detail") or message.payload.get("why") or "")
    return ""


def _ordered_ids(plan: PagePlan | None) -> list[int]:
    if plan is None:
        return []
    slots = plan.slots or {}
    front = slots.get("front") or {}
    ids = [front.get("lead"), *(front.get("second") or []), *(front.get("briefs") or [])]
    for entries in (slots.get("sections") or {}).values():
        ids.extend(e.get("story_id") for e in entries or [] if isinstance(e, dict))
    seen: list[int] = []
    for i in ids:
        if i and i not in seen:
            seen.append(i)
    return seen


def render_newsroom(
    session: Session,
    edition_date: date,
    run_variant: str = "mas",
    focus_story_id: int | None = None,
) -> str:
    plans = session.scalars(
        select(PagePlan)
        .where(PagePlan.edition_date == edition_date, PagePlan.run_variant == run_variant)
        .order_by(PagePlan.plan_version)
    ).all()
    # 一個查詢取全部有稿的 story 與其版本；每個 story 取最大 version
    pairs = session.execute(
        select(Story, StoryVersion)
        .join(StoryVersion, StoryVersion.story_id == Story.id)
        .where(Story.edition_date == edition_date, Story.run_variant == run_variant)
        .order_by(StoryVersion.version)
    ).all()
    latest: dict[int, tuple[Story, StoryVersion]] = {}
    for story, version in pairs:
        latest[story.id] = (story, version)
    total = session.scalar(
        select(func.count()).select_from(Story).where(
            Story.edition_date == edition_date, Story.run_variant == run_variant
        )
    ) or 0
    titles = {sid: v.headline for sid, (_, v) in latest.items()}
    rank = {sid: n for n, sid in enumerate(_ordered_ids(plans[-1] if plans else None))}
    front_role = {}
    if plans:
        front = (plans[-1].slots or {}).get("front") or {}
        if front.get("lead"):
            front_role[front["lead"]] = "lead"
        for i in front.get("second") or []:
            front_role[i] = "second"
        for i in front.get("briefs") or []:
            front_role[i] = "briefs"
    ordered = sorted(latest.values(), key=lambda sv: (rank.get(sv[0].id, 10**9), sv[0].section, sv[0].id))
    rows = []
    for story, version in ordered:
        label = SECTION_LABELS.get(story.section, story.section)
        status_text = STATUS_LABELS.get(version.status, version.status)
        ok = " ok" if version.status == "approved" else ""
        by = f' <span class="muted">核准：{escape(version.approved_by)}</span>' if version.approved_by else ""
        tag = f'<span class="sec">頭版 {front_role[story.id]}</span>' if story.id in front_role else ""
        rows.append(
            f'<li><span class="sec">{escape(label)}</span>{tag}'
            f'<a href="?variant={escape(run_variant)}&amp;story={story.id}">{escape(version.headline)}</a><br>'
            f'<span class="status{ok}" data-story-id="{story.id}" data-status="{escape(version.status)}">'
            f'{escape(status_text)}</span>{by}</li>'
        )
    unwritten = total - len(latest)
    left = (
        f'<ul class="stories">{"".join(rows) or "<li>這一期還沒有稿</li>"}</ul>'
        f'<p class="muted">另有 {unwritten} 個候選事件未寫稿</p>'
    )
    timeline = session.scalars(select(AgentMessage).where(
        AgentMessage.edition_date == edition_date, AgentMessage.run_variant == run_variant
    ).order_by(AgentMessage.created_at, AgentMessage.id)).all()
    focus = ""
    if focus_story_id is not None:
        focus = _focus(session, edition_date, run_variant, focus_story_id)
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>回放 {edition_date.isoformat()}</title>
<style>{CSS}</style></head><body>
<section class="top"><h1>編輯室回放 {edition_date.isoformat()} · {escape(run_variant)}</h1>
<p><a href="/daily/{edition_date.isoformat()}">← 回到當期日報</a> · <a href="?variant={"pipeline" if run_variant == "mas" else "mas"}">切換到 {"P 組" if run_variant == "mas" else "M 組"}</a></p>
<h2>版面計畫</h2>{_plan_diffs(plans, titles)}</section>
<div class="cols"><aside class="left"><h2>稿件</h2>{left}</aside>
<main class="right">{_overview(timeline, titles, run_variant)}{focus or "<p>點左邊一則稿，看訊息與版本 diff。</p>"}</main></div>
</body></html>"""


def _story_link(story_id: int | None, titles: dict[int, str], run_variant: str) -> str:
    if story_id is None:
        return ""
    name = escape(titles.get(story_id, f"story {story_id}"))
    return f'<a href="?variant={escape(run_variant)}&amp;story={story_id}">{name}</a>'


def _overview(timeline: list[AgentMessage], titles: dict[int, str], run_variant: str) -> str:
    pitches = [m for m in timeline if m.type == "PITCH"]
    rows = []
    for m in timeline:
        if m.type == "PITCH":
            continue
        rows.append(
            f"<tr><td>{escape(_taipei(m.created_at))}</td>"
            f"<td>{escape(m.sender_role)}→{escape(m.recipient_role or '')}</td>"
            f"<td>{escape(TYPE_LABELS.get(m.type, m.type))}<br><span class=\"muted\">{escape(m.type)}"
            f" · {escape(m.status)}</span></td>"
            f"<td>{_story_link(m.story_id, titles, run_variant)}</td><td>{escape(_detail(m))}</td></tr>"
        )
    summary = ""
    if pitches:
        rejected = sum(1 for m in pitches if m.status == "rejected")
        summary = f'<p class="muted">PITCH 提案共 {len(pitches)} 則' + (f"（{rejected} 則被拒）" if rejected else "") + "</p>"
    table = (
        '<div class="tablewrap"><table><tr><th>時間（台北）</th><th>寄件→收件</th><th>類型</th><th>稿件</th>'
        f'<th>說明</th></tr>{"".join(rows)}</table></div>' if rows else "<p>沒有其他訊息。</p>"
    )
    return f"<h2>本期訊息</h2>{summary}{table}"


def _slot_table(slots: dict, titles: dict[int, str]) -> str:
    def name(i):
        return escape(titles.get(i, f"story {i}"))

    rows = []
    front = slots.get("front") or {}
    if front.get("lead"):
        rows.append(("頭版", "lead", name(front["lead"]), "full", ""))
    for i in front.get("second") or []:
        rows.append(("頭版", "second", name(i), "full", ""))
    for i in front.get("briefs") or []:
        rows.append(("頭版", "briefs", name(i), "link", ""))
    for section, entries in (slots.get("sections") or {}).items():
        for e in entries or []:
            if isinstance(e, dict):
                rows.append((
                    SECTION_LABELS.get(section, section), "", name(e.get("story_id")),
                    str(e.get("display", "")), str(e.get("label", "")),
                ))
    body = "".join(
        f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{c}</td><td>{escape(d)}</td><td>{escape(e)}</td></tr>"
        for a, b, c, d, e in rows
    )
    return (
        '<div class="tablewrap"><table><tr><th>版別</th><th>位置</th><th>稿件</th><th>顯示</th><th>說明</th></tr>'
        f"{body}</table></div>"
    )


def _plan_diffs(plans: list[PagePlan], titles: dict[int, str] | None = None) -> str:
    if not plans:
        return "<p>還沒有版面計畫。</p>"
    titles = titles or {}
    dump = [json.dumps(p.slots, ensure_ascii=False, sort_keys=True, indent=2) for p in plans]
    latest = plans[-1]
    note = ""
    if len(plans) > 1:
        same = dump[-1] == dump[-2]
        note = (
            f'<p class="muted">共 {len(plans)} 版；v{latest.plan_version} 與上一版'
            f'{"相同" if same else "有差異（見下方 diff）"}。</p>'
        )
    blocks = []
    for n, plan in enumerate(plans):
        if n == 0:
            diff = dump[0]
        else:
            diff = "\n".join(difflib.unified_diff(
                dump[n - 1].splitlines(), dump[n].splitlines(),
                fromfile=f"plan v{plans[n - 1].plan_version}", tofile=f"plan v{plan.plan_version}", lineterm="",
            )) or "（與上一版相同）"
        blocks.append(f"<h3>v{plan.plan_version}</h3><pre>{escape(diff)}</pre>")
    return (
        f"<h3>最新 v{latest.plan_version}</h3>{_slot_table(latest.slots or {}, titles)}{note}"
        f"<details><summary>原始 JSON 與各版 diff</summary>{''.join(blocks)}</details>"
    )


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
        when = _taipei(message.created_at)
        detail = _detail(message)
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
        f'<div class="tablewrap"><table><tr><th>時間（台北）</th><th>角色</th><th>type</th><th>狀態</th><th>內容</th></tr>'
        f"{''.join(lines)}</table></div><h3>v1→v2 diff</h3><pre>{escape(diff or '（還沒有下一版）')}</pre>{form}"
    )
