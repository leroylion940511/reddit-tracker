"""編輯室回放的時間線（3D 辦公室頁面用）。唯讀。

把一期發生的事整理成一步一步的 `beats`：收集（source_fetch_runs）→ 聚合與快照 → P 流水線 →
各角色的模型呼叫（llm_records）→ 角色之間的訊息（agent_messages）→ 稿件版本（story_versions）→
版面計畫（page_plans）→ 真人核准 → 發行。前端照順序播放，不自己推論任何新聞判斷。

時間：
- 模型呼叫一律用 `llm_records.called_at`（每次嘗試結束時的真實時間）。
- 訊息有 `llm_call_id`（2026-11-12 之後的期數）就用訊息自己的 `created_at`（真實時間）。
- 更早的期數，訊息的 `created_at` 是編排器的假時鐘（每則 +1 秒），不能拿來排序；改用同一篇稿、
  同一個角色的第 k 次呼叫去對（`timing="reconstructed"`），頁面上會標明。
"""

from __future__ import annotations

import difflib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AgentMessage, DailyEdition, DailySnapshot, LLMRecord, PagePlan, SourceFetchRun, Story, StoryVersion,
)

TAIPEI = ZoneInfo("Asia/Taipei")
SECTION_LABELS = {"taiwan": "台灣", "world": "國際", "tech": "科技", "front": "頭版"}
ROLE_LABELS = {
    "eic": "總編輯", "section_taiwan": "台灣版主編", "section_world": "國際版主編", "section_tech": "科技版主編",
    "section_editor": "分版主編", "reporter": "記者", "fact_checker": "查核員", "copy_editor": "文稿編輯",
    "layout_editor": "版面編輯", "system": "程式", "human": "真人審核", "wire": "傳真機（RSSHub）",
    "researcher": "資料員（RSS）", "pipeline": "流水線（P 組）", "checktool": "查核工具（程式）",
}
TYPE_LABELS = {
    "PITCH": "提案", "CHALLENGE": "異議", "REQUEST_REVISION": "要求修稿", "REVISION_DONE": "修稿完成",
    "REBUT": "反駁", "HOLD": "暫緩 HOLD", "RELEASE": "放行", "PAGE_OBJECTION": "版面異議", "DECISION": "總編決定",
}
PHASES = [
    ("collect", "收集"), ("cluster", "聚合／快照"), ("pipeline", "流水線 P"), ("pitch", "提案"),
    ("write", "寫稿／查核"), ("layout", "版面協商"), ("copy", "文稿"), ("approve", "核准"), ("publish", "發行"),
]
TEXT_LIMIT = 2400
COLLECT_BUCKET_HOURS = 4
EPS = timedelta(milliseconds=1)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _clip(text: str | None, limit: int = TEXT_LIMIT) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"…（共 {len(text)} 字，已截短）"


def _short(text: str | None, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _json(text: str | None):
    try:
        return json.loads(text or "")
    except (ValueError, TypeError):
        return None


def _section_of_prompt(prompt: str | None) -> str | None:
    data = _json(prompt)
    return data.get("section") if isinstance(data, dict) else None


def _source_meta() -> dict[str, tuple[str, str]]:
    """source_id →（名稱, 管道）。讀不到登錄表就回空的，頁面改顯示 source_id。"""
    try:
        from ..seeds.news_sources import load_registry

        return {s.id: (s.name, s.method) for s in load_registry().sources}
    except Exception:  # noqa: BLE001 — 名稱只影響顯示
        return {}


class _Timeline:
    def __init__(self) -> None:
        self.items: list[tuple[datetime, int, dict]] = []

    def add(self, at: datetime, beat: dict) -> dict:
        self.items.append((at, len(self.items), beat))
        return beat

    def beats(self) -> list[dict]:
        out = []
        for index, (at, _, beat) in enumerate(sorted(self.items, key=lambda x: (x[0], x[1]))):
            local = at.astimezone(TAIPEI)
            out.append({"i": index, "at": local.strftime("%H:%M:%S"), "day": local.strftime("%m-%d"),
                        "iso": local.isoformat(timespec="seconds"), **beat})
        return out


def _llm_detail(rec: LLMRecord) -> dict:
    return {
        "llm_id": rec.id, "secs": round((rec.latency_ms or 0) / 1000, 1), "ok": bool(rec.ok),
        "model": rec.model_version or rec.model, "error": rec.error or "",
        "prompt": _clip(rec.prompt_text), "response": _clip(rec.response_text),
    }


def _collect_beats(session: Session, timeline: _Timeline, start: datetime, end: datetime) -> dict:
    meta = _source_meta()
    rows = session.execute(
        select(SourceFetchRun.source_id, SourceFetchRun.started_at, SourceFetchRun.ok, SourceFetchRun.items_new,
               SourceFetchRun.not_modified)
        .where(SourceFetchRun.started_at >= start.replace(tzinfo=None), SourceFetchRun.started_at < end.replace(tzinfo=None))
        .order_by(SourceFetchRun.started_at)
    ).all()
    buckets: dict[tuple[int, str], dict] = {}
    span = timedelta(hours=COLLECT_BUCKET_HOURS)
    for source_id, started, ok, new, not_modified in rows:
        started = _utc(started)
        index = int((started - start) / span)
        name, method = meta.get(source_id, (source_id, "rss"))
        actor = "wire" if method == "rsshub" else "researcher"
        bucket = buckets.setdefault((index, actor), {"runs": 0, "failed": 0, "new": 0, "unchanged": 0, "by": defaultdict(int)})
        bucket["runs"] += 1
        bucket["failed"] += 0 if ok else 1
        bucket["unchanged"] += 1 if not_modified else 0
        bucket["new"] += new or 0
        if new:
            bucket["by"][name] += new
    totals = {"runs": len(rows), "new": 0, "failed": 0, "sources": len({r[0] for r in rows})}
    for (index, actor), bucket in sorted(buckets.items()):
        begin = start + span * index
        finish = min(begin + span, end)
        top = sorted(bucket["by"].items(), key=lambda kv: -kv[1])
        window = f"{begin.astimezone(TAIPEI):%m-%d %H:%M}–{finish.astimezone(TAIPEI):%H:%M}"
        totals["new"] += bucket["new"]
        totals["failed"] += bucket["failed"]
        if actor == "wire":
            say = f"RSSHub 傳來 {bucket['new']} 則新素材（{len(top)} 個來源）"
        else:
            say = f"上網查了 {bucket['runs']} 次 RSS，找到 {bucket['new']} 則新素材"
        timeline.add(finish - timedelta(seconds=2 if actor == "wire" else 1), {
            "phase": "collect", "kind": "collect", "actor": actor, "mode": "print" if actor == "wire" else "browse",
            "title": f"收集 {window}", "say": say,
            "sheets": [{"label": name, "n": count} for name, count in top[:6]],
            "detail": {"window": window, "runs": bucket["runs"], "failed": bucket["failed"],
                       "unchanged": bucket["unchanged"], "new": bucket["new"],
                       "sources": [{"name": name, "new": count} for name, count in top[:30]]},
            "state": {"collected": bucket["new"]},
        })
    return totals


def _message_text(message: AgentMessage, titles: dict[int, str]) -> str:
    payload = message.payload if isinstance(message.payload, dict) else {}
    kind = message.type
    if kind == "CHALLENGE":
        if payload.get("problem") == "NONE":
            return f"看過了，沒問題：{payload.get('detail', '')}"
        if payload.get("problem") == "UNSUPPORTED_NUMBER":
            return f"異議（程式比對數字，模型說 OK 也蓋不掉）：{payload.get('detail', '')}"
        return f"異議：{payload.get('detail', '')}"
    if kind == "REVISION_DONE":
        return f"改好了，v{payload.get('new_version', '?')}：{payload.get('change', '')}"
    if kind == "REBUT":
        return f"我不同意：{payload.get('reason', '')}"
    if kind == "RELEASE":
        return payload.get("detail") or "重驗通過"
    if kind == "HOLD":
        who = f"（{payload['by']}）" if payload.get("by") else ""
        return f"這篇先暫緩{who}：{payload.get('detail') or payload.get('reason') or ''}"
    if kind == "REQUEST_REVISION":
        return payload.get("detail") or "請修稿"
    if kind == "PAGE_OBJECTION":
        detail = payload.get("detail") or ""
        inner = _json(detail) if isinstance(detail, str) and detail.lstrip().startswith("{") else None
        if isinstance(inner, dict):
            detail = inner.get("detail") or inner.get("problem") or detail
        return f"版面意見：{detail}"
    if kind == "DECISION":
        if payload.get("error"):
            return f"沒有可用的決定：{payload['error']}"
        lead = titles.get(payload.get("lead"), f"story {payload.get('lead')}")
        count = 1 + len(payload.get("second") or []) + len(payload.get("briefs") or [])
        why = payload.get("why") or next((r.get("why") for r in payload.get("reasons") or []
                                           if r.get("story_id") == payload.get("lead")), "")
        return f"頭版定案 {count} 則，主稿《{lead}》。{why}"
    return payload.get("detail") or kind


def _actor_of(role: str, section: str | None = None) -> str:
    if role == "section_editor":
        return f"section_{section}" if section in ("taiwan", "world", "tech") else "section_taiwan"
    return role if role in ROLE_LABELS else "system"


def build_replay(session: Session, edition_date: date, run_variant: str = "mas") -> dict:
    """一期的回放資料（純 dict，可直接 json.dumps）。沒有這一期的資料時 beats 是空的。"""
    edition = session.scalar(select(DailyEdition).where(DailyEdition.edition_date == edition_date))
    snapshot = session.scalar(select(DailySnapshot).where(DailySnapshot.edition_date == edition_date))
    records = session.scalars(
        select(LLMRecord).where(LLMRecord.edition_date == edition_date).order_by(LLMRecord.id)
    ).all()
    messages = session.scalars(
        select(AgentMessage).where(AgentMessage.edition_date == edition_date, AgentMessage.run_variant == run_variant)
        .order_by(AgentMessage.id)
    ).all()
    pairs = session.execute(
        select(Story, StoryVersion).join(StoryVersion, StoryVersion.story_id == Story.id)
        .where(Story.edition_date == edition_date, Story.run_variant == run_variant)
        .order_by(StoryVersion.story_id, StoryVersion.version)
    ).all()
    plans = session.scalars(
        select(PagePlan).where(PagePlan.edition_date == edition_date, PagePlan.run_variant == run_variant)
        .order_by(PagePlan.plan_version)
    ).all()
    stats = (edition.stats or {}) if edition is not None else {}

    versions: dict[int, list[StoryVersion]] = defaultdict(list)
    story_rows: dict[int, Story] = {}
    for story, version in pairs:
        story_rows[story.id] = story
        versions[story.id].append(version)
    titles = {sid: rows[-1].headline for sid, rows in versions.items()}
    source_titles: dict[int, str] = {}
    for rec in records:
        if rec.role == "section_editor":
            data = _json(rec.prompt_text)
            for cand in (data or {}).get("candidates", []) if isinstance(data, dict) else []:
                if isinstance(cand, dict) and cand.get("story_id"):
                    source_titles[cand["story_id"]] = cand.get("title") or ""

    def name_of(story_id) -> str:
        return titles.get(story_id) or source_titles.get(story_id) or f"story {story_id}"

    first_call = min((_utc(r.called_at) - timedelta(milliseconds=r.latency_ms or 0) for r in records), default=None)
    prepared = _utc(edition.prepared_at) if edition is not None and edition.prepared_at else None
    snapshot_at = _utc(snapshot.created_at) if snapshot is not None else None
    anchor = prepared or snapshot_at or first_call or datetime.combine(
        edition_date, datetime.min.time(), tzinfo=TAIPEI).astimezone(timezone.utc) + timedelta(hours=6)
    timeline = _Timeline()

    # ① 收集：上一期準備之後到這一期準備之前
    totals = _collect_beats(session, timeline, anchor - timedelta(hours=24), anchor)

    # ②③ 聚合、快照
    candidates = len(snapshot.candidates) if snapshot is not None else stats.get("candidate_clusters", 0)
    rewrites = stats.get("section_rewrites") or {}
    timeline.add(anchor, {
        "phase": "cluster", "kind": "cluster", "actor": "system", "mode": "sort",
        "title": "事件聚合（程式）",
        "say": f"把素材分組成事件：共 {stats.get('candidate_clusters', candidates)} 個候選事件。不確定就不合併。",
        "detail": {"candidate_clusters": stats.get("candidate_clusters", candidates),
                   "entity_merges": len(stats.get("entity_merge_groups") or []),
                   "llm_merges": len(stats.get("llm_merge_groups") or []),
                   "rejected_merges": len(stats.get("rejected_merges") or []),
                   "section_rewrites": rewrites},
    })
    timeline.add(anchor + EPS, {
        "phase": "cluster", "kind": "snapshot", "actor": "system", "mode": "stamp",
        "title": "06:00 快照",
        "say": f"快照蓋章：凍結 {candidates} 個候選事件與證據素材，P、M 兩組都從這一份開始。",
        "detail": {"candidates": candidates, "briefs": len(stats.get("briefs") or [])},
    })

    # P 流水線（M 組頁面也播：它是同一天的對照組）
    for rec in records:
        if rec.run_variant != "pipeline":
            continue
        end = _utc(rec.called_at)
        first_line = (rec.prompt_text or "").split("\n", 1)[0]
        if rec.role == "desk":
            groups = (_json(rec.response_text) or {}).get("groups") if isinstance(_json(rec.response_text), dict) else None
            say = f"編輯會議第二意見：跨語言同一事件 {len(groups or [])} 組（程式還要確認共同實體）"
            title = "跨語言合併（建快照時，P、M 共用）"
        else:
            section = first_line.split("。")[0].replace("板塊：", "") if first_line.startswith("板塊：") else "一版"
            written = (_json(rec.response_text) or {}).get("stories") if isinstance(_json(rec.response_text), dict) else None
            say = f"{section}：一次呼叫寫完整版 {len(written or [])} 篇"
            title = f"流水線撰稿｜{section}"
        timeline.add(end, {
            "phase": "pipeline", "kind": "llm", "actor": "pipeline", "mode": "think",
            "title": title, "say": say if rec.ok else f"呼叫失敗：{_short(rec.error, 60)}",
            "secs": round((rec.latency_ms or 0) / 1000, 1), "detail": _llm_detail(rec),
        })

    recorded = any(m.llm_call_id for m in messages)
    by_id = {rec.id: rec for rec in records}
    mas_records = [r for r in records if r.run_variant == run_variant and run_variant == "mas"]
    pool: dict[tuple, list[LLMRecord]] = defaultdict(list)  # (story_id, role) → 依序的呼叫
    for rec in mas_records:
        pool[(rec.story_id, rec.role)].append(rec)
    version_of_call: dict[int, StoryVersion] = {}
    for story_id, rows in versions.items():
        calls = pool.get((story_id, "reporter"), [])
        agent_rows = [v for v in rows if v.sender != "human"]
        if len(calls) >= len(agent_rows):  # 重試多於版本時，最後幾次才是成功寫出版本的那幾次
            calls = calls[len(calls) - len(agent_rows):] if any(not c.ok for c in calls) else calls
        for call, version in zip(calls, agent_rows):
            version_of_call[call.id] = version

    def version_state(version: StoryVersion, status: str | None = None) -> dict:
        return {"stories": {str(version.story_id): {"version": version.version, "status": status or "draft",
                                                    "headline": version.headline}}}

    def diff_of(version: StoryVersion) -> str:
        previous = next((v for v in versions[version.story_id] if v.version == version.version - 1), None)
        if previous is None:
            return ""
        return "\n".join(difflib.unified_diff(
            (previous.body or "").splitlines(), (version.body or "").splitlines(),
            fromfile=f"v{previous.version}", tofile=f"v{version.version}", lineterm="", n=1))

    # ⑤ M 組各角色的模型呼叫
    for rec in mas_records:
        end = _utc(rec.called_at)
        secs = round((rec.latency_ms or 0) / 1000, 1)
        beat = {"kind": "llm", "mode": "think", "secs": secs, "detail": _llm_detail(rec), "story_id": rec.story_id}
        response = _json(rec.response_text)
        response = response if isinstance(response, dict) else {}
        if not rec.ok:
            beat |= {"phase": "write", "actor": _actor_of(rec.role or "system", _section_of_prompt(rec.prompt_text)),
                     "title": f"{ROLE_LABELS.get(rec.role, rec.role)}｜呼叫失敗", "say": f"這次呼叫失敗，重試：{_short(rec.error, 70)}"}
        elif rec.role == "section_editor":
            section = _section_of_prompt(rec.prompt_text)
            front = sum(1 for p in response.get("pitches", []) if p.get("priority") == "front")
            beat |= {"phase": "pitch", "actor": _actor_of("section_editor", section),
                     "title": f"{SECTION_LABELS.get(section, section)}版主編想提案",
                     "say": f"看本版 4 篇候選和全站前十名…想推 {front} 篇上頭版"}
        elif rec.role == "reporter":
            version = version_of_call.get(rec.id)
            action = str(response.get("action", "")).upper()
            if version is not None and version.version == 1:
                say, title = f"寫好 v1：《{version.headline}》", "記者寫稿"
            elif version is not None:
                say, title = f"改寫成 v{version.version}：《{version.headline}》", "記者修稿"
            elif action == "REBUT":
                say, title = f"不同意，準備反駁：{_short(response.get('reason'), 60)}", "記者反駁"
            else:
                say, title = "寫好一版稿", "記者寫稿"
            beat |= {"phase": "write", "actor": "reporter", "title": title, "say": say}
            if version is not None:
                beat["state"] = version_state(version)
                beat["detail"] |= {"version": version.version, "headline": version.headline,
                                   "body": _clip(version.body, 1200), "diff": _clip(diff_of(version), 2000)}
                beat["paper"] = {"label": f"v{version.version}", "to": "fact_checker"}
        elif rec.role == "fact_checker":
            action = str(response.get("action", "")).upper()
            verdict = "同一事件、數字沒混用" if action == "OK" else "有問題"
            beat |= {"phase": "write", "actor": "fact_checker", "title": "查核員判斷（程式工具覺得可疑才問）",
                     "say": f"判斷：{verdict}。{_short(response.get('detail'), 70)}"}
        elif rec.role == "layout_editor":
            beat |= {"phase": "layout", "actor": "layout_editor", "title": "版面編輯檢查頭版",
                     "say": _short(response.get("detail") or response.get("problem") or "檢查頭版容量、重複與版別平衡", 90)}
        elif rec.role == "eic":
            beat |= {"phase": "layout", "actor": "eic", "title": "總編輯裁決",
                     "say": "比較各版提案，決定頭版放哪幾則…"}
        elif rec.role == "copy_editor":
            action = str(response.get("action", "")).upper()
            verdict = "標題與內文一致" if action != "CHALLENGE" else f"有問題：{_short(response.get('detail'), 60)}"
            beat |= {"phase": "copy", "actor": "copy_editor", "title": "文稿編輯看頭版稿",
                     "say": f"《{_short(name_of(rec.story_id), 24)}》{verdict}"}
        else:
            beat |= {"phase": "write", "actor": _actor_of(rec.role or "system"), "title": rec.role or "模型呼叫", "say": ""}
        timeline.add(end, beat)

    # 訊息的時間
    used: dict[tuple, int] = defaultdict(int)
    last_story_time: dict[int | None, datetime] = {}
    previous_time = anchor + 2 * EPS

    def reconstructed_time(message: AgentMessage) -> datetime:
        """舊期數（沒有 llm_call_id）：用同一篇稿、同一角色的第 k 次呼叫對出訊息的真實時間。"""
        payload = message.payload if isinstance(message.payload, dict) else {}
        sender, story_id = message.sender_role, message.story_id

        def take(key) -> LLMRecord | None:
            calls = pool.get(key) or []
            if key[1] == "reporter":
                calls = calls[1:]  # 第一次呼叫是 v1，沒有訊息
            if used[key] < len(calls):
                used[key] += 1
                return calls[used[key] - 1]
            return None

        def last_used(key) -> LLMRecord | None:
            calls = pool.get(key) or []
            count = used[key] + (1 if key[1] == "reporter" else 0)
            return calls[min(count, len(calls)) - 1] if calls and count else None

        rec = None
        if message.type == "PITCH":
            rec = next((r for r in pool.get((None, "section_editor"), [])
                        if _section_of_prompt(r.prompt_text) == payload.get("section")), None)
        elif sender == "fact_checker":
            # 相關性／數字那條路 payload 一定有 llm_assessment 這個鍵；是 None 表示這次沒問模型
            asked = payload.get("llm_assessment") if "llm_assessment" in payload else True
            rec = take((story_id, sender)) if asked else None
        elif sender in ("copy_editor", "reporter"):
            rec = take((story_id, sender))
        elif sender in ("layout_editor", "eic"):
            rec = take((story_id, sender)) or take((None, sender)) or last_used((None, sender))
        elif sender == "system" and story_id is not None and payload.get("llm_assessment"):
            rec = take((story_id, "fact_checker"))
        if rec is not None:
            return _utc(rec.called_at) + EPS
        if sender == "human":
            return _utc(message.created_at)
        if story_id is not None:  # 程式發的訊息：排在這篇稿目前為止最後一次呼叫之後
            done = [r for r in (last_used((story_id, "reporter")), last_used((story_id, "fact_checker"))) if r is not None]
            if done:
                return max(_utc(r.called_at) for r in done) + EPS
        return last_story_time.get(story_id, previous_time) + EPS

    hold_now: set[int] = set()
    pitch_groups: dict[str, dict] = {}
    for message in messages:
        payload = message.payload if isinstance(message.payload, dict) else {}
        if recorded or message.sender_role == "human":
            at = _utc(message.created_at)
        else:
            at = reconstructed_time(message)
        at = max(at, last_story_time.get(message.story_id, at))
        last_story_time[message.story_id] = at + EPS
        previous_time = max(previous_time, at)
        if message.type == "PITCH" and message.status != "rejected":
            section = payload.get("section")
            group = pitch_groups.get(section)
            if group is None:
                group = pitch_groups[section] = timeline.add(at, {
                    "phase": "pitch", "kind": "message", "type": "PITCH", "type_label": "提案", "mode": "say",
                    "actor": _actor_of("section_editor", section), "to": "eic", "status": message.status,
                    "title": f"{SECTION_LABELS.get(section, section)}版主編提案", "detail": {"pitches": []},
                    "paper": {"label": "提案", "to": "eic"},
                })
            group["detail"]["pitches"].append({
                "story_id": message.story_id, "title": name_of(message.story_id), "angle": payload.get("angle", ""),
                "priority": payload.get("priority", "section"), "message_id": message.id,
            })
            items = group["detail"]["pitches"]
            front = [p for p in items if p["priority"] == "front"]
            lead = front[0] if front else items[0]
            group["say"] = (f"我這版今天做 {len(items)} 篇，{len(front)} 篇想上頭版。"
                            f"首推《{_short(lead['title'], 26)}》：{_short(lead['angle'], 60)}")
            continue
        actor = _actor_of(message.sender_role, payload.get("section"))
        target = _actor_of(message.recipient_role, payload.get("section"))
        if message.sender_role == "system" and message.story_id is not None:
            actor = "checktool"  # 查核員桌上的程式工具：重驗、放行、暫緩
        beat = {
            "phase": "write", "kind": "message", "type": message.type, "type_label": TYPE_LABELS.get(message.type, message.type),
            "mode": "say", "actor": actor, "to": target, "status": message.status, "story_id": message.story_id,
            "title": f"{ROLE_LABELS.get(actor, actor)} → {ROLE_LABELS.get(target, target)}｜{TYPE_LABELS.get(message.type, message.type)}",
            "say": _short(_message_text(message, {**source_titles, **titles}), 150),
            "detail": {"message_id": message.id, "llm_id": message.llm_call_id, "correlation_id": message.correlation_id,
                       "target_version": message.target_version,
                       "payload": _clip(json.dumps(payload, ensure_ascii=False, indent=1), 2400)},
        }
        if message.status == "rejected":
            beat["say"] = f"（被程式拒絕）{beat['say']}"
            reason = payload.get("program_reason")
            if reason:
                beat["detail"]["program_reason"] = reason
        story_versions = versions.get(message.story_id) or []
        if message.type == "CHALLENGE" and message.status != "rejected" and payload.get("problem") != "NONE":
            beat["walk"] = True
            if message.story_id:
                beat["state"] = {"stories": {str(message.story_id): {"status": "challenged"}}}
            if message.sender_role == "copy_editor":
                beat["phase"] = "copy"
        elif message.type == "CHALLENGE":
            beat["phase"] = "copy" if message.sender_role == "copy_editor" else "write"
        elif message.type == "RELEASE" and message.story_id:
            hold_now.discard(message.story_id)
            beat["mode"] = "stamp"
            beat["state"] = {"stories": {str(message.story_id): {"status": "checked"}}}
            beat["paper"] = {"label": "✓", "to": "eic"}
        elif message.type == "HOLD" and message.story_id and message.status != "rejected":
            hold_now.add(message.story_id)
            beat["mode"] = "stamp"
            beat["state"] = {"stories": {str(message.story_id): {"status": "hold"}}}
            beat["phase"] = "approve" if message.sender_role == "human" else "write"
        elif message.type == "REVISION_DONE" and story_versions:
            new = next((v for v in story_versions if v.version == payload.get("new_version")), None)
            if new is not None:
                beat["state"] = version_state(new)
                beat["detail"]["diff"] = _clip(diff_of(new), 2000)
            beat["paper"] = {"label": f"v{payload.get('new_version', '')}", "to": target}
        elif message.type in ("PAGE_OBJECTION", "REQUEST_REVISION"):
            beat["phase"] = "layout"
            beat["walk"] = message.type == "PAGE_OBJECTION"
        elif message.type == "DECISION":
            beat["phase"] = "layout"
            beat["detail"]["reasons"] = [
                {"title": name_of(r.get("story_id")), "why": r.get("why", "")} for r in payload.get("reasons") or []]
            beat["detail"]["dropped"] = [
                {"title": name_of(r.get("story_id")), "why": r.get("why", "")} for r in payload.get("dropped") or []]
        if message.type == "REBUT":
            beat["walk"] = True
        timeline.add(at, beat)

    # 版面計畫：第幾版、誰的決定造成的
    plan_time = {m.id: last_story_time.get(m.story_id) for m in messages}
    message_at: dict[int, datetime] = {}
    for at, _, beat in timeline.items:
        mid = (beat.get("detail") or {}).get("message_id")
        if mid:
            message_at[mid] = at
    plan_out = []
    if run_variant == "pipeline":  # P 組的版面是撰稿之後才寫的
        previous_time = max([previous_time, *(_utc(r.called_at) + timedelta(seconds=1) for r in records if r.run_variant == "pipeline")])
    layout_calls = pool.get((None, "layout_editor")) or []
    for index, plan in enumerate(plans):
        slots = plan.slots or {}
        front = slots.get("front") or {}
        summary = {
            "version": plan.plan_version, "decided_by": plan.decided_by_message_id,
            "front": {"lead": front.get("lead"), "second": list(front.get("second") or []),
                      "briefs": list(front.get("briefs") or [])},
            "sections": {key: [{"story_id": (e.get("story_id") if isinstance(e, dict) else e),
                                "display": (e.get("display") if isinstance(e, dict) else "full")} for e in entries or []]
                         for key, entries in (slots.get("sections") or {}).items()},
        }
        plan_out.append(summary)
        if plan.decided_by_message_id in message_at:
            at = message_at[plan.decided_by_message_id] + EPS
            why = "總編輯的決定寫成新一版版面"
        elif recorded:
            at, why = _utc(plan.created_at), "依各版提案排出的版面"
        elif layout_calls and run_variant == "mas":
            at = _utc(layout_calls[0].called_at) - timedelta(milliseconds=layout_calls[0].latency_ms or 0) - EPS
            why = "依各版提案排出的版面"
        else:
            at, why = previous_time + EPS * (index + 1), "程式選題排出的版面" if run_variant == "pipeline" else "依各版提案排出的版面"
        lead = name_of(front.get("lead")) if front.get("lead") else "（沒有主稿）"
        timeline.add(at, {
            "phase": "layout", "kind": "plan", "actor": "eic" if plan.decided_by_message_id else "system", "mode": "board",
            "title": f"版面計畫 v{plan.plan_version}", "say": f"版面計畫 v{plan.plan_version}：{why}。頭版主稿《{_short(lead, 28)}》",
            "detail": {"plan_version": plan.plan_version, "decided_by_message_id": plan.decided_by_message_id},
            "state": {"plan": index},
        })
    del plan_time

    # P 組沒有訊息：稿件版本直接列出來（程式檢查後就是 checked）
    if run_variant == "pipeline":
        pipeline_end = max((_utc(r.called_at) for r in records if r.run_variant == "pipeline"), default=previous_time)
        order = 0
        for story_id, rows in versions.items():
            for version in rows:
                order += 1
                timeline.add(pipeline_end + EPS * order, {
                    "phase": "pipeline", "kind": "version", "actor": "pipeline", "mode": "stamp", "story_id": story_id,
                    "title": "流水線稿件", "say": f"《{_short(version.headline, 30)}》程式檢查後 {version.status}",
                    "state": version_state(version, version.status),
                    "detail": {"version": version.version, "headline": version.headline, "body": _clip(version.body, 1200)},
                })

    # ⑦b 真人核准（同一個人同一分鐘的併成一步）
    published = _utc(edition.published_at) if edition is not None and edition.published_at else None
    approvals: dict[tuple, list[StoryVersion]] = defaultdict(list)
    for rows in versions.values():
        for version in rows:
            if version.approved_by and version.approved_at:
                approvals[(version.approved_by, _utc(version.approved_at).replace(second=0, microsecond=0))].append(version)
    for (who, minute), rows in sorted(approvals.items(), key=lambda kv: kv[0][1]):
        at = max(_utc(v.approved_at) for v in rows)
        late = published is not None and at > published
        note = "（已經過了發行時間，當天讀者只收到標題短訊）" if late else ""
        timeline.add(at, {
            "phase": "approve", "kind": "approve", "actor": "human", "mode": "stamp", "late": late,
            "title": f"真人核准｜{who}", "say": f"{who} 核准 {len(rows)} 篇{note}",
            "detail": {"by": who, "stories": [{"story_id": v.story_id, "title": v.headline, "version": v.version} for v in rows]},
            "state": {"stories": {str(v.story_id): {"status": "approved", "version": v.version} for v in rows}},
        })

    # ⑧ 發行
    if published is not None and (run_variant == "mas" or stats.get("run_variant") != "mas"):
        on_time = sum(1 for rows in versions.values() if rows[-1].approved_at and _utc(rows[-1].approved_at) <= published)
        written = len(versions)
        if run_variant == "mas":
            say = f"發行：網頁報紙＋Telegram。發行當下已核准 {on_time}／{written} 篇，沒核准的只發標題。"
        else:
            say = "發行：網頁報紙＋Telegram。"
        timeline.add(published, {
            "phase": "publish", "kind": "publish", "actor": "system", "mode": "publish", "title": "發行", "say": say,
            "detail": {"status": edition.status, "approved_at_publish": on_time, "written": written},
        })
    elif run_variant == "pipeline" and edition is not None:
        timeline.add(max(published or previous_time, pipeline_end + timedelta(seconds=1)) + EPS, {
            "phase": "publish", "kind": "publish", "actor": "pipeline", "mode": "publish", "title": "影子版",
            "say": "P 組是對照組：影子版只存檔（site/daily/shadow/），不發行。", "detail": {},
        })

    beats = timeline.beats()
    stories_out = {}
    final_plan = plan_out[-1] if plan_out else None
    front_ids = []
    if final_plan:
        front_ids = [i for i in [final_plan["front"]["lead"], *final_plan["front"]["second"], *final_plan["front"]["briefs"]] if i]
    for story_id, rows in versions.items():
        story = story_rows[story_id]
        stories_out[str(story_id)] = {
            "id": story_id, "section": story.section, "section_label": SECTION_LABELS.get(story.section, story.section),
            "kind": story.kind, "score": round(story.score or 0, 1), "headline": rows[-1].headline,
            "source_title": source_titles.get(story_id, ""), "final_status": rows[-1].status,
            "versions": len(rows), "front": story_id in front_ids, "lead": bool(final_plan and final_plan["front"]["lead"] == story_id),
        }
    role_calls: dict[str, int] = defaultdict(int)
    for rec in records:
        if rec.run_variant == run_variant:
            role_calls[rec.role or "?"] += 1
    return {
        "date": edition_date.isoformat(), "variant": run_variant,
        "timing": "recorded" if recorded else "reconstructed",
        "phases": [{"id": key, "label": label} for key, label in PHASES if any(b["phase"] == key for b in beats)],
        "roles": ROLE_LABELS, "stories": stories_out, "plans": plan_out, "beats": beats,
        "summary": {
            "collected": totals["new"], "fetch_runs": totals["runs"], "fetch_failed": totals["failed"],
            "sources": totals["sources"], "candidates": candidates, "written": len(versions),
            "messages": len(messages), "llm_calls": dict(role_calls),
            "degraded": stats.get("degraded") or [], "published_at": published.astimezone(TAIPEI).strftime("%m-%d %H:%M") if published else "",
            "edition_status": edition.status if edition is not None else "沒有這一期",
        },
    }
