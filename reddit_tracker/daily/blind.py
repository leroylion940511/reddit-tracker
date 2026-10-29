"""盲計匯出、抽查表、實驗二抽樣。對照表只留 SHA-256，不把組別寫進給標註員的文字。"""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SourceItem, Story, StoryVersion
from .store import MAS, PIPELINE

BLIND_SEED = 20261201
EXP2_SEED = 20261211

SECTION_LABELS = {
    "taiwan": "台灣",
    "world": "國際",
    "tech": "科技",
    "front": "頭版",
}
_CITE = re.compile(r"\[(?:S)?(\d+)\]")


def _latest_agent_version(session: Session, story_id: int) -> StoryVersion | None:
    versions = session.scalars(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version.desc())
    ).all()
    for version in versions:
        if version.sender != "human":
            return version
    return versions[0] if versions else None


def _sources(session: Session, version: StoryVersion) -> list[tuple[str, str, str]]:
    ids = list(version.source_ids or [])
    if not ids:
        return []
    rows = session.scalars(select(SourceItem).where(SourceItem.id.in_(ids))).all()
    by_id = {row.id: row for row in rows}
    found = []
    for item_id in ids:
        row = by_id.get(item_id)
        if row is None:
            continue
        found.append((row.source_id, row.title or "", (row.summary or "")[:400]))
    return found


def _plain(session: Session, story: Story, version: StoryVersion) -> str:
    label = SECTION_LABELS.get(story.section, story.section)
    body = _CITE.sub(lambda match: f"[S{match.group(1)}]", version.body or "")
    lines = [f"版：{label}", f"標題：{version.headline}", "正文：", body, "來源："]
    sources = _sources(session, version)
    if not sources:
        lines.append("- （無）｜｜")
    for outlet, title, summary in sources:
        lines.append(f"- {outlet}｜{title}｜{summary}")
    return "\n".join(lines)


def export_blind_count(
    session: Session, dates: list[date], *, seed: int = BLIND_SEED,
) -> tuple[str, dict, str]:
    """回傳（給標註員的純文字, 對照表, 對照表 SHA-256）。兩組混在一起、隨機編號。"""
    items: list[tuple[str, dict]] = []
    for edition_date in dates:
        for variant in (PIPELINE, MAS):
            stories = session.scalars(
                select(Story).where(Story.edition_date == edition_date, Story.run_variant == variant)
            ).all()
            for story in stories:
                version = _latest_agent_version(session, story.id)
                if version is None:
                    continue
                items.append((
                    _plain(session, story, version),
                    {
                        "edition_date": edition_date.isoformat(),
                        "story_id": story.id,
                        "variant": variant,
                    },
                ))
    order = list(range(len(items)))
    random.Random(seed).shuffle(order)
    blocks = []
    mapping: dict[str, dict] = {}
    for number, index in enumerate(order, start=1):
        text, meta = items[index]
        blocks.append(f"#{number}\n{text}")
        mapping[str(number)] = meta
    sheet = _count_sheet(len(mapping))
    document = "\n\n".join(blocks + [sheet]) if blocks else sheet
    digest = mapping_digest(mapping)
    return document, mapping, digest


def mapping_digest(mapping: dict) -> str:
    blob = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _count_sheet(count: int) -> str:
    lines = ["編號,第1類,第2類,第3類,第4類,你猜這篇是哪一組（P／M／不知道）"]
    for number in range(1, count + 1):
        lines.append(f"{number},,,,,")
    return "\n".join(lines)


def spot_check_sheet(session: Session, edition_date: date, *, seed: int = BLIND_SEED) -> str:
    """M 組頭版主稿，加上隨機 1 篇。用核准前的版本（sender 不是 human）。"""
    stories = session.scalars(
        select(Story).where(Story.edition_date == edition_date, Story.run_variant == MAS)
    ).all()
    lead = _front_lead(session, edition_date)
    others = [story for story in stories if lead is None or story.id != lead.id]
    picked = None
    if others:
        picked = random.Random(seed).choice(others)
    parts = [f"# 抽查 {edition_date.isoformat()}", "用送人工核准之前的版本。只能記錄，不能改稿。"]
    for title, story in (("頭版主稿", lead), ("隨機一則", picked)):
        parts.append(f"## {title}")
        if story is None:
            parts.append("（沒有）")
            continue
        version = _latest_agent_version(session, story.id)
        parts.append(_plain(session, story, version) if version else "（沒有稿）")
    return "\n\n".join(parts)


def _front_lead(session: Session, edition_date: date) -> Story | None:
    from ..models import PagePlan

    plan = session.scalar(
        select(PagePlan)
        .where(PagePlan.edition_date == edition_date, PagePlan.run_variant == MAS)
        .order_by(PagePlan.plan_version.desc())
    )
    if plan is None:
        return None
    lead_id = (plan.slots.get("front") or {}).get("lead")
    return session.get(Story, lead_id) if lead_id else None


def sample_exp2(session: Session, dates: list[date], *, seed: int = EXP2_SEED, k: int = 25) -> list[int]:
    """從指定日期的 M 組稿用固定種子抽 k 篇，給標註員 A 再挑 15 篇。"""
    ids = []
    for edition_date in dates:
        ids.extend(session.scalars(
            select(Story.id).where(Story.edition_date == edition_date, Story.run_variant == MAS)
        ).all())
    if len(ids) <= k:
        return list(ids)
    return random.Random(seed).sample(list(ids), k)


def analyze_blind(labels: dict[str, dict], mapping: dict) -> dict:
    """labels：編號 → {class1..class4 的 0/1}。依對照表分成 P／M 後加總。"""
    totals = {PIPELINE: [0, 0, 0, 0], MAS: [0, 0, 0, 0]}
    counts = {PIPELINE: 0, MAS: 0}
    for number, meta in mapping.items():
        variant = meta["variant"]
        counts[variant] = counts.get(variant, 0) + 1
        mark = labels.get(str(number)) or {}
        bucket = totals.setdefault(variant, [0, 0, 0, 0])
        for index in range(4):
            bucket[index] += int(mark.get(f"class{index + 1}") or 0)
    return {"counts": counts, "errors": totals}
