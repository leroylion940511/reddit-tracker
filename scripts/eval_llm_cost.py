"""M7.9 — LLM 成本對帳 (SCHEDULE.md 7.9)。

切分:
    - 依 provider / model / purpose
    - 依月份 (called_at)
    - per-call 統計 (avg input/output tokens, avg cost)

對企劃書 §八 預估比較 (人工填在 baseline.md, 這支只算實際值).

用法:
    uv run python scripts/eval_llm_cost.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from reddit_tracker.db import session_scope  # noqa: E402
from reddit_tracker.models import LLMRecord, ScoringRecord  # noqa: E402


def _money(x: float | Decimal) -> str:
    return f"${float(x):.4f}"


def main() -> None:
    """整合兩個成本來源:
    1. llm_records — QA layer (services/qa.py 寫進)
    2. scoring_records (stage='haiku').cost_usd — scoring layer
       (M3 設計上應該也寫 llm_records 但實際沒寫, 暫時用 scoring_records 補)
    """
    with session_scope() as s:
        llm_rows = s.execute(
            select(
                LLMRecord.provider,
                LLMRecord.model,
                LLMRecord.purpose,
                LLMRecord.input_tokens,
                LLMRecord.output_tokens,
                LLMRecord.cost_usd,
                LLMRecord.called_at,
            )
        ).all()

        scoring_haiku_rows = s.execute(
            select(
                ScoringRecord.cost_usd,
                ScoringRecord.scored_at,
            ).where(
                ScoringRecord.stage == "haiku",
                ScoringRecord.cost_usd.isnot(None),
            )
        ).all()

        # 用 namespace tuple 統一介面: (provider, model, purpose, in, out, cost, called_at)
        class _Row:
            __slots__ = ("provider", "model", "purpose", "input_tokens",
                         "output_tokens", "cost_usd", "called_at")
            def __init__(self, **kw):
                for k, v in kw.items(): setattr(self, k, v)

        rows = []
        for r in llm_rows:
            rows.append(_Row(
                provider=r.provider, model=r.model, purpose=r.purpose,
                input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                cost_usd=r.cost_usd, called_at=r.called_at,
            ))
        # scoring 沒記 token 數 — 只能補 cost. 推測 provider/model: 看 config 是 minimax
        from reddit_tracker.config import get_settings
        cfg = get_settings()
        scoring_provider = cfg.llm_provider
        scoring_model = cfg.minimax_model if cfg.llm_provider == "minimax" else "unknown"
        for r in scoring_haiku_rows:
            rows.append(_Row(
                provider=scoring_provider, model=scoring_model, purpose="scoring",
                input_tokens=0, output_tokens=0,
                cost_usd=r.cost_usd, called_at=r.scored_at,
            ))

        if not rows:
            print("沒有 LLM 成本資料 (llm_records + scoring_records 都空)。")
            return

        print(
            f"# M7.9 LLM 成本對帳 ({len(rows)} 筆 call — "
            f"{len(llm_rows)} from llm_records + {len(scoring_haiku_rows)} from scoring_records)\n"
        )

        # 整體
        total_cost = sum((r.cost_usd or Decimal("0")) for r in rows)
        total_in = sum((r.input_tokens or 0) for r in rows)
        total_out = sum((r.output_tokens or 0) for r in rows)
        print(
            f"**整體**：{len(rows)} call · in={total_in:,} tok · out={total_out:,} tok · "
            f"cost={_money(total_cost)}"
        )

        # 依 provider × model × purpose
        agg: dict[tuple[str, str, str], dict] = defaultdict(
            lambda: {"n": 0, "in": 0, "out": 0, "cost": Decimal("0")}
        )
        for r in rows:
            key = (r.provider, r.model, r.purpose)
            a = agg[key]
            a["n"] += 1
            a["in"] += r.input_tokens or 0
            a["out"] += r.output_tokens or 0
            a["cost"] += r.cost_usd or Decimal("0")

        print("\n### 依 provider / model / purpose\n")
        print(
            "| provider | model | purpose | calls | in tok | out tok | total cost | avg cost/call |"
        )
        print("|---|---|---|---:|---:|---:|---:|---:|")
        for (prov, model, purp), a in sorted(agg.items(), key=lambda x: -float(x[1]["cost"])):
            avg = float(a["cost"]) / a["n"] if a["n"] else 0
            print(
                f"| {prov} | {model} | {purp} | {a['n']} | "
                f"{a['in']:,} | {a['out']:,} | {_money(a['cost'])} | {_money(avg)} |"
            )

        # 依月
        per_month: dict[str, dict] = defaultdict(
            lambda: {"n": 0, "cost": Decimal("0"), "in": 0, "out": 0}
        )
        for r in rows:
            key = r.called_at.strftime("%Y-%m") if r.called_at else "unknown"
            m = per_month[key]
            m["n"] += 1
            m["in"] += r.input_tokens or 0
            m["out"] += r.output_tokens or 0
            m["cost"] += r.cost_usd or Decimal("0")

        print("\n### 依月份\n")
        print("| 月份 | calls | in tok | out tok | cost |")
        print("|---|---:|---:|---:|---:|")
        for ym in sorted(per_month):
            m = per_month[ym]
            print(
                f"| {ym} | {m['n']} | {m['in']:,} | {m['out']:,} | {_money(m['cost'])} |"
            )

        # 依 purpose
        per_purpose: dict[str, dict] = defaultdict(
            lambda: {"n": 0, "cost": Decimal("0")}
        )
        for r in rows:
            p = per_purpose[r.purpose]
            p["n"] += 1
            p["cost"] += r.cost_usd or Decimal("0")

        print("\n### 依 purpose (彙整)\n")
        print("| purpose | calls | cost | per-call avg |")
        print("|---|---:|---:|---:|")
        for purp in sorted(per_purpose):
            p = per_purpose[purp]
            avg = float(p["cost"]) / p["n"] if p["n"] else 0
            print(f"| {purp} | {p['n']} | {_money(p['cost'])} | {_money(avg)} |")

        # 月成本投影
        # 假設目前流量代表性: 拿最後一個完整月的 cost 直接列；若不足一月, 線性外推
        if per_month:
            latest = sorted(per_month)[-1]
            latest_cost = float(per_month[latest]["cost"])
            print(
                f"\n_最後一個有資料的月份 {latest}_：{_money(latest_cost)}（partial — "
                "scheduler 6/2 啟動, 不是完整月）"
            )


if __name__ == "__main__":
    main()
