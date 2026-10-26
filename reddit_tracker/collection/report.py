"""七天收集驗收用的 Markdown 報表（Asia/Taipei 日曆日）。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SourceFetchRun, SourceItem
from ..seeds.news_sources import SourceRegistry
from .collector import COLLECTABLE_METHODS, as_utc

TAIPEI = ZoneInfo("Asia/Taipei")


def _day(dt: datetime) -> date:
    return as_utc(dt).astimezone(TAIPEI).date()


def build_collection_report(
    session: Session, registry: SourceRegistry, *, days: int = 7, now: datetime | None = None
) -> str:
    now = now or datetime.now(timezone.utc)
    last_day = _day(now)
    day_list = [last_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    window_start = datetime.combine(day_list[0], time.min, TAIPEI).astimezone(timezone.utc)

    items = session.execute(
        select(
            SourceItem.source_id,
            SourceItem.section,
            SourceItem.first_seen_at,
            SourceItem.duplicate_of_id,
            SourceItem.published_at_estimated,
        ).where(SourceItem.first_seen_at >= window_start)
    ).all()
    unique_by_section_day: Counter = Counter()
    total_by_day: Counter = Counter()
    duplicate_by_day: Counter = Counter()
    unique_by_source: Counter = Counter()
    estimated = 0
    for source_id, section, seen, duplicate_of, is_estimated in items:
        day = _day(seen)
        total_by_day[day] += 1
        estimated += bool(is_estimated)
        if duplicate_of is None:
            unique_by_section_day[(section, day)] += 1
            unique_by_source[source_id] += 1
        else:
            duplicate_by_day[day] += 1

    runs_by_source: dict[str, list[SourceFetchRun]] = defaultdict(list)
    for run in session.scalars(
        select(SourceFetchRun)
        .where(SourceFetchRun.started_at >= window_start)
        .order_by(SourceFetchRun.started_at)
    ):
        runs_by_source[run.source_id].append(run)

    lines = [
        f"# 多來源收集報表（{day_list[0]} 至 {last_day}，Asia/Taipei）",
        "",
        f"產生時間：{now.astimezone(TAIPEI):%Y-%m-%d %H:%M}。唯一項目＝`duplicate_of_id IS NULL`，依首次收錄日分組。",
        "",
        "## 各版每日唯一項目",
        "",
        "| 板塊 | " + " | ".join(f"{d:%m/%d}" for d in day_list) + " | 合計 |",
        "| --- | " + " | ".join("---:" for _ in day_list) + " | ---: |",
    ]
    for key, label in registry.sections.items():
        counts = [unique_by_section_day[(key, d)] for d in day_list]
        lines.append(f"| {label} | " + " | ".join(str(c) for c in counts) + f" | {sum(counts)} |")
    lines.append(
        "| **全站收錄（含重複）** | " + " | ".join(str(total_by_day[d]) for d in day_list)
        + f" | {sum(total_by_day.values())} |"
    )
    lines.append(
        "| **其中重複** | " + " | ".join(str(duplicate_by_day[d]) for d in day_list)
        + f" | {sum(duplicate_by_day.values())} |"
    )
    total = len(items)
    lines += [
        "",
        f"發布時間為推估值的比例：{estimated}/{total}" + (f"（{estimated / total:.1%}）" if total else ""),
        "",
        "## 各來源健康",
        "",
        "| 來源 | 板塊 | 抓取次數 | 成功率 | 最後成功 | 連續失敗 | 唯一項目 | 最近錯誤 |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for source in registry.enabled():
        if source.method not in COLLECTABLE_METHODS:
            continue
        runs = runs_by_source.get(source.id, [])
        ok_runs = [run for run in runs if run.ok]
        streak = 0
        for run in reversed(runs):
            if run.ok:
                break
            streak += 1
        last_ok = (
            f"{as_utc(ok_runs[-1].started_at).astimezone(TAIPEI):%m/%d %H:%M}" if ok_runs else "—"
        )
        rate = f"{len(ok_runs) / len(runs):.0%}" if runs else "—"
        last_error = next((run.error for run in reversed(runs) if run.error), "")
        lines.append(
            f"| `{source.id}` | {registry.sections[source.section]} | {len(runs)} | {rate} | {last_ok} "
            f"| {streak} | {unique_by_source[source.id]} | {(last_error or '')[:80].replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"
