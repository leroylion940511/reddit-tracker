"""盲計匯出、抽查表、實驗二抽樣。對照表只留 SHA-256，不把組別寫進給標註員的文字。"""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AgentMessage, SourceItem, Story, StoryVersion
from .store import MAS, PIPELINE

BLIND_SEED = 20261201
EXP2_SEED = 20261211
BLIND_PER_DAY = 8
ERROR_CLASSES = 7  # 手冊 9.4 的七類
MAIN_CLASSES = 5  # 主指標只算第 1–5 類（手冊 8.3）

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


def _held_before_approval(session: Session, story_id: int) -> bool:
    """送核准前就被 HOLD：有一則非真人發出、生效的 HOLD 訊息（查核員來回 2 輪、查核員停擺等）。

    不看 story_versions.status：真人 HOLD（`hold_story`）會直接改最新版的 status，
    事後重匯出就分不出是誰擋的。
    """
    return session.scalar(
        select(func.count()).select_from(AgentMessage).where(
            AgentMessage.story_id == story_id,
            AgentMessage.type == "HOLD",
            AgentMessage.sender_role != "human",
            AgentMessage.status.not_in(("rejected", "expired")),
        )
    ) > 0


def _written(session: Session, edition_date: date, variant: str) -> dict[int, tuple[Story, StoryVersion]]:
    """keeper_cluster_id → (story, 送核准前最新版)。只收有正文的稿；P 的標題短訊不是 story，本來就不在這裡。"""
    found: dict[int, tuple[Story, StoryVersion]] = {}
    stories = session.scalars(
        select(Story).where(Story.edition_date == edition_date, Story.run_variant == variant).order_by(Story.id)
    ).all()
    for story in stories:
        version = _latest_agent_version(session, story.id)
        if version is None or not (version.body or "").strip():
            continue
        found.setdefault(story.keeper_cluster_id, (story, version))
    return found


def sample_day(session: Session, edition_date: date, *, seed: int = BLIND_SEED, k: int = BLIND_PER_DAY) -> dict:
    """手冊 8.3 公平原則第 7 點：P、M 都有寫的事件抽 k 個，一半拿 P 的版本、一半拿 M 的版本。

    - 同一事件：兩組的 story 有相同的 `keeper_cluster_id`。P 影子與 M 從同一份 `daily_snapshots` 開始，
      快照裡每個候選的 cluster 集合（keeper ∪ merged_cluster_ids）互不重疊，所以 keeper 相同 ⇔ 同一事件。
    - 都有寫：兩組都有送核准前、正文非空的版本（`sender != "human"` 的最新版）。M 被 HOLD 的稿照樣算。
    - 種子：`random.Random(f"{seed}-{YYYY-MM-DD}")`，每天不同、同一天重跑一樣。共同事件先依 keeper 排序再抽。
    - 分組：抽到 n 個，P 拿 n // 2 個；n 是奇數時多出的那一篇用同一個 rng 決定給 P 或 M。
      不按版別分層（手冊沒要求；一天 8 篇再分三層，每層只剩 2–3 篇，只會讓抽樣更不隨機）。

    回傳 {"edition_date", "common": 共同事件數, "items": [{story, version, variant, hold}]}。
    """
    rng = random.Random(f"{seed}-{edition_date.isoformat()}")
    pipeline = _written(session, edition_date, PIPELINE)
    mas = _written(session, edition_date, MAS)
    common = sorted(set(pipeline) & set(mas))
    picked = rng.sample(common, min(k, len(common)))
    p_count = len(picked) // 2
    if len(picked) % 2 and rng.random() < 0.5:
        p_count += 1
    variants = [PIPELINE] * p_count + [MAS] * (len(picked) - p_count)
    rng.shuffle(variants)
    items = []
    for keeper, variant in zip(picked, variants):
        story, version = (pipeline if variant == PIPELINE else mas)[keeper]
        items.append({
            "story": story,
            "version": version,
            "variant": variant,
            "hold": variant == MAS and _held_before_approval(session, story.id),
        })
    return {"edition_date": edition_date, "common": len(common), "items": items}


def export_blind_count(
    session: Session, dates: list[date], *, seed: int = BLIND_SEED,
) -> tuple[str, dict, str]:
    """回傳（給標註員的純文字, 對照表, 對照表 SHA-256）。

    每天各自用 `sample_day` 抽樣，再把所有天的稿混在一起用 `random.Random(f"{seed}-order-{日期,…}")` 隨機編號。
    沒有任何稿時純文字是空字串、對照表是 {}。
    """
    items: list[tuple[str, dict]] = []
    notes: list[str] = []
    for edition_date in dates:
        day = sample_day(session, edition_date, seed=seed)
        if len(day["items"]) < BLIND_PER_DAY:
            notes.append(
                f"{edition_date.isoformat()} 只有 {len(day['items'])} 篇"
                f"（兩組都有寫的事件只有 {day['common']} 個，不足 {BLIND_PER_DAY} 個）"
            )
        for item in day["items"]:
            story, version = item["story"], item["version"]
            items.append((
                _plain(session, story, version),
                {
                    "edition_date": edition_date.isoformat(),
                    "story_id": story.id,
                    "variant": item["variant"],
                    "version": version.version,
                    "keeper_cluster_id": story.keeper_cluster_id,
                    "merged_cluster_ids": list(story.merged_cluster_ids or []),
                    "section": story.section,
                    "hold": bool(item["hold"]),
                },
            ))
    if not items:
        return "", {}, mapping_digest({})
    order = list(range(len(items)))
    random.Random(f"{seed}-order-{','.join(d.isoformat() for d in dates)}").shuffle(order)
    header = [f"# 盲計 {'、'.join(d.isoformat() for d in dates)}｜共 {len(items)} 篇", *(f"注意：{note}" for note in notes)]
    blocks = ["\n".join(header)]
    mapping: dict[str, dict] = {}
    for number, index in enumerate(order, start=1):
        text, meta = items[index]
        blocks.append(f"#{number}\n{text}")
        mapping[str(number)] = meta
    document = "\n\n".join(blocks + [_count_sheet(len(mapping))]) + "\n"
    return document, mapping, mapping_digest(mapping)


def mapping_bytes(mapping: dict) -> bytes:
    """對照表的標準位元組：UTF-8 的 `json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。

    `_private/mapping.json` 就是寫這串位元組（不加換行），所以 `shasum -a 256 mapping.json` 等於 `mapping.sha256`。
    """
    return json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def mapping_digest(mapping: dict) -> str:
    return hashlib.sha256(mapping_bytes(mapping)).hexdigest()


def _count_sheet(count: int) -> str:
    classes = ",".join(f"第{index}類" for index in range(1, ERROR_CLASSES + 1))
    lines = [f"編號,{classes},你猜這篇是哪一組（P／M／不知道）"]
    for number in range(1, count + 1):
        lines.append(f"{number}" + "," * (ERROR_CLASSES + 1))
    return "\n".join(lines)


def spot_check_sheet(session: Session, edition_date: date, *, seed: int = BLIND_SEED) -> str:
    """M 組頭版主稿，加上隨機 1 篇（手冊步驟 11 第 2 點、8.4、9.5）。

    都用送人工核准前的版本（sender 不是 human），附來源媒體、標題、摘要。
    隨機那篇從當期 M 組其餘有正文的稿（含 HOLD）依 story id 排序後，用
    `random.Random(f"{seed}-spot-{YYYY-MM-DD}")` 抽，每天不同、同一天重跑一樣。
    """
    lead = _front_lead(session, edition_date)
    others = [story for story, _ in sorted(_written(session, edition_date, MAS).values(), key=lambda pair: pair[0].id)
              if lead is None or story.id != lead.id]
    picked = random.Random(f"{seed}-spot-{edition_date.isoformat()}").choice(others) if others else None
    parts = [f"# 抽查 {edition_date.isoformat()}", "用送人工核准之前的版本。只能記錄，不能改稿。"]
    for title, story in (("頭版主稿", lead), ("隨機一則", picked)):
        parts.append(f"## {title}")
        if story is None:
            parts.append("（沒有）")
            continue
        version = _latest_agent_version(session, story.id)
        parts.append(_plain(session, story, version) if version else "（沒有稿）")
    return "\n\n".join(parts) + "\n"


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


def _rate(errors: int, count: int) -> float | None:
    return round(errors / count * 10, 3) if count else None


def analyze_blind(labels: dict[str, dict], mapping: dict) -> dict:
    """labels：編號 → {"class1".."class7": 0/1, "guess": "P"／"M"／"不知道"}（只有 class1–4 的舊格式也能讀）。

    依對照表分成 P／M 後加總：
    - errors：每類錯誤數；main_per_10：第 1–5 類錯誤 ÷ 篇數 × 10（主指標，手冊 8.3）；第 6、7 類另列在 errors。
    - hold_blocked：敏感度版本，把 M 送核准前被 HOLD 的稿算成「已擋下、不計錯」（篇數照算，錯誤記 0）。
    - guess：B 猜組別的正確數；「不知道」與空白不算猜。
    """
    variants = (PIPELINE, MAS)
    counts = dict.fromkeys(variants, 0)
    errors = {variant: [0] * ERROR_CLASSES for variant in variants}
    blocked = {variant: 0 for variant in variants}
    guessed = correct = unsure = 0
    letter = {PIPELINE: "P", MAS: "M"}
    for number, meta in mapping.items():
        variant = meta["variant"]
        counts[variant] = counts.get(variant, 0) + 1
        mark = labels.get(str(number)) or {}
        marks = [int(mark.get(f"class{index + 1}") or 0) for index in range(ERROR_CLASSES)]
        bucket = errors.setdefault(variant, [0] * ERROR_CLASSES)
        for index, value in enumerate(marks):
            bucket[index] += value
        if not (meta.get("hold") and variant == MAS):
            blocked[variant] = blocked.get(variant, 0) + sum(marks[:MAIN_CLASSES])
        guess = str(mark.get("guess") or "").strip().upper()
        if guess in ("P", "M"):
            guessed += 1
            correct += guess == letter.get(variant)
        else:
            unsure += 1
    main = {variant: sum(bucket[:MAIN_CLASSES]) for variant, bucket in errors.items()}
    return {
        "counts": counts,
        "errors": errors,
        "main_errors": main,
        "main_per_10": {variant: _rate(main[variant], counts.get(variant, 0)) for variant in errors},
        "hold_count": sum(1 for meta in mapping.values() if meta.get("hold") and meta["variant"] == MAS),
        "hold_blocked": {
            "main_errors": blocked,
            "main_per_10": {variant: _rate(blocked[variant], counts.get(variant, 0)) for variant in blocked},
        },
        "guess": {"guessed": guessed, "correct": correct, "unsure": unsure,
                  "accuracy": round(correct / guessed, 3) if guessed else None},
    }
