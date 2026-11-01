"""七天收集驗收用的 Markdown 報表（Asia/Taipei 日曆日）。

來源健康表列出現在啟用的來源；報表第一天之後才第一次抓取的來源標「MM/DD 加入」，還沒抓過的標「尚未抓取」。現在已停用、但報表期間內
有抓取紀錄的來源另列一表（含登錄表備註），驗收期間中途停用的失敗來源不會從報表消失。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
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
    ]
    first_run = dict(
        session.execute(select(SourceFetchRun.source_id, func.min(SourceFetchRun.started_at)).group_by(SourceFetchRun.source_id)).all()
    )

    def joined(source_id: str) -> str:
        """報表第一天之後才第一次抓取＝期間中途加入（數字不滿整段期間）。"""
        first = first_run.get(source_id)
        if first is None:
            return "（尚未抓取）"
        return f"（{_day(first):%m/%d} 加入）" if _day(first) > day_list[0] else ""

    collectable = [s for s in registry.sources if s.method in COLLECTABLE_METHODS]
    enabled = [s for s in collectable if s.enabled]
    disabled = [s for s in collectable if not s.enabled and runs_by_source.get(s.id)]
    new_ids = [s.id for s in enabled if joined(s.id)]  # 含尚未抓取
    lines += [
        f"啟用 {len(enabled)} 個來源，其中 {len(new_ids)} 個在報表期間中途加入"
        + (f"（{'、'.join(f'`{i}`' for i in new_ids)}）" if new_ids else "")
        + f"；另有 {len(disabled)} 個現已停用、但期間內有抓取紀錄，列在下方「停用來源」。",
        "",
        "| 來源 | 板塊 | 抓取次數 | 成功率 | 最後成功 | 連續失敗 | 唯一項目 | 最近錯誤 |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for source in enabled:
        lines.append("| " + " | ".join(_health(source, registry, runs_by_source, unique_by_source, joined(source.id))) + " |")
    if disabled:
        lines += [
            "",
            "## 停用來源（報表期間內有抓取紀錄）",
            "",
            "現在登錄表 `enabled: false`；下列數字是停用前在報表期間內的抓取。",
            "",
            "| 來源 | 板塊 | 抓取次數 | 成功率 | 最後成功 | 連續失敗 | 唯一項目 | 最近錯誤 | 最後抓取 | 登錄表備註 |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: | --- | --- | --- |",
        ]
        for source in disabled:
            runs = runs_by_source[source.id]
            cells = _health(source, registry, runs_by_source, unique_by_source, joined(source.id))
            cells += [_ts(runs[-1].started_at), (source.notes or "").replace("|", "/")]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _ts(dt: datetime) -> str:
    return f"{as_utc(dt).astimezone(TAIPEI):%m/%d %H:%M}"


def _health(source, registry: SourceRegistry, runs_by_source, unique_by_source, joined: str) -> list[str]:
    """來源健康表的前 8 欄：來源、板塊、抓取次數、成功率、最後成功、連續失敗、唯一項目、最近錯誤。"""
    runs = runs_by_source.get(source.id, [])
    ok_runs = [run for run in runs if run.ok]
    streak = 0
    for run in reversed(runs):
        if run.ok:
            break
        streak += 1
    last_ok = _ts(ok_runs[-1].started_at) if ok_runs else "—"
    rate = f"{len(ok_runs) / len(runs):.0%}" if runs else "—"
    last_error = next((run.error for run in reversed(runs) if run.error), "")
    return [
        f"`{source.id}`{joined}", registry.sections[source.section], str(len(runs)), rate, last_ok, str(streak),
        str(unique_by_source[source.id]), (last_error or "")[:80].replace("|", "/"),
    ]
