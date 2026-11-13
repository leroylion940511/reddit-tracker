"""實驗一結果計算（手冊 8.1 第 6、7 點；步驟 9b）。

只做算術，不碰 DB、不呼叫 LLM。輸入是標註員交回的 CSV 與抽樣時寫下的私有對照表
（`annotation/exp1/_private/exp1_key.csv`，裡面的 `a_merged`／`c_merged` 是抽樣 commit 上兩個方法
對這一組的判斷；抽樣 commit 就是 tag `exp1-frozen`，所以不重跑聚合）。

統計量都用標準函式庫自己算，公式與手冊指定的套件相同：
- Wilson 區間＝`statsmodels.stats.proportion.proportion_confint(k, n, method="wilson")`
- exact McNemar＝`statsmodels.stats.contingency_tables.mcnemar(table, exact=True)`（雙尾二項檢定）
- Cohen's κ＝`sklearn.metrics.cohen_kappa_score`
- F1 區間＝對配對重抽 2,000 次取第 2.5／97.5 百分位
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path

YES, NO, UNSURE = "是", "不是", "不確定"
LABELS = (YES, NO, UNSURE)
BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20261122
PAIR_COLUMNS = [
    "pair_id", "split", "kind", "stratum", "a_merged", "c_merged",
    "label_a", "label_b", "final", "標題 1", "標題 2",
]


class Exp1InputError(ValueError):
    pass


@dataclass(frozen=True)
class Pair:
    pair_id: str
    split: str  # dev／test
    kind: str  # same（同語言）／cross（中英）
    stratum: str
    a_merged: bool
    c_merged: bool
    label_a: str
    label_b: str  # 沒複標是空字串
    final: str
    title_1: str = ""
    title_2: str = ""


# ── 讀檔 ──────────────────────────────────────────────────────────────────


def read_csv(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _labels(rows: list[dict], who: str, column: str = "判斷") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        pair_id = (row.get("pair_id") or "").strip()
        label = (row.get(column) or "").strip()
        if not pair_id:
            continue
        if label not in LABELS:
            raise Exp1InputError(f"{who} 的 {pair_id} 判斷是 {label!r}，只能是 是／不是／不確定")
        if pair_id in out:
            raise Exp1InputError(f"{who} 的 {pair_id} 出現兩次")
        out[pair_id] = {**row, "_label": label}
    return out


def build_pairs(key_rows: list[dict], a_rows: list[dict], b_rows: list[dict], final_rows: list[dict] | None = None) -> list[Pair]:
    """把對照表、A、B、討論後的最終答案併成一張表。

    最終答案：沒複標的用 A；A、B 一致的用該答案；不一致的必須出現在 `final_rows`（欄位 pair_id、final）。
    """
    a = _labels(a_rows, "A")
    b = _labels(b_rows, "B")
    final = _labels(final_rows or [], "最終答案", "final")
    keys = {row["pair_id"]: row for row in key_rows}
    if set(a) != set(keys):
        raise Exp1InputError(f"A 的配對與對照表不同：多 {sorted(set(a) - set(keys))[:5]}、少 {sorted(set(keys) - set(a))[:5]}")
    should_double = {pid for pid, row in keys.items() if row["b_double"] == "True"}
    if set(b) != should_double:
        raise Exp1InputError(f"B 的配對與對照表的複標名單不同：多 {sorted(set(b) - should_double)[:5]}、少 {sorted(should_double - set(b))[:5]}")
    pairs, unresolved = [], []
    for pid, row in keys.items():
        la = a[pid]["_label"]
        lb = b[pid]["_label"] if pid in b else ""
        if lb and lb != la:
            if pid not in final:
                unresolved.append(pid)
                continue
            decided = final[pid]["_label"]
        else:
            decided = final[pid]["_label"] if pid in final else la
        pairs.append(Pair(
            pair_id=pid, split=row["split"], kind=row["kind"], stratum=row["stratum"],
            a_merged=row["a_merged"] == "True", c_merged=row["c_merged"] == "True",
            label_a=la, label_b=lb, final=decided,
            title_1=a[pid].get("標題 1", ""), title_2=a[pid].get("標題 2", ""),
        ))
    if unresolved:
        raise Exp1InputError(f"A、B 不一致但沒有討論後的最終答案（--final）：{sorted(unresolved)}")
    return sorted(pairs, key=lambda p: p.pair_id)


def write_pairs_csv(pairs: list[Pair], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PAIR_COLUMNS)
        for p in pairs:
            writer.writerow([p.pair_id, p.split, p.kind, p.stratum, p.a_merged, p.c_merged,
                             p.label_a, p.label_b, p.final, p.title_1, p.title_2])


# ── 統計 ──────────────────────────────────────────────────────────────────


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """b、c 是兩個方法「一對一錯」的兩格。雙尾 exact：2 × P(X ≤ min(b,c))，X ~ Binomial(b+c, 0.5)，上限 1。"""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def cohen_kappa(first: list[str], second: list[str]) -> float | None:
    n = len(first)
    if n == 0 or n != len(second):
        return None
    observed = sum(x == y for x, y in zip(first, second)) / n
    expected = sum((first.count(v) / n) * (second.count(v) / n) for v in set(first) | set(second))
    if expected == 1:
        return None  # 兩人全部給同一個答案，κ 沒有定義
    return (observed - expected) / (1 - expected)


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        return 2 * self.tp / (2 * self.tp + self.fp + self.fn) if 2 * self.tp + self.fp + self.fn else None

    @property
    def false_merge_rate(self) -> float | None:
        return self.fp / (self.fp + self.tn) if self.fp + self.tn else None


def truth_of(pair: Pair, unsure: str) -> bool | None:
    """unsure：exclude（主分析）／yes／no。"""
    if pair.final == UNSURE:
        return {"exclude": None, "yes": True, "no": False}[unsure]
    return pair.final == YES


def confusion(pairs: list[Pair], method: str, unsure: str = "exclude") -> Confusion:
    tp = fp = fn = tn = 0
    for pair in pairs:
        truth = truth_of(pair, unsure)
        if truth is None:
            continue
        merged = pair.a_merged if method == "A" else pair.c_merged
        tp += truth and merged
        fp += (not truth) and merged
        fn += truth and not merged
        tn += (not truth) and not merged
    return Confusion(tp, fp, fn, tn)


def bootstrap_f1(pairs: list[Pair], method: str, unsure: str = "exclude",
                 rounds: int = BOOTSTRAP_ROUNDS, seed: int = BOOTSTRAP_SEED) -> tuple[float, float] | None:
    usable = [p for p in pairs if truth_of(p, unsure) is not None]
    if not usable:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(rounds):
        f1 = confusion(rng.choices(usable, k=len(usable)), method, unsure).f1
        if f1 is not None:
            values.append(f1)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(math.ceil(0.975 * (len(values) - 1)))]


def mcnemar_a_vs_c(pairs: list[Pair], unsure: str = "exclude") -> tuple[int, int, float]:
    """回傳（只有 A 對、只有 C 對、p 值）。"""
    only_a = only_c = 0
    for pair in pairs:
        truth = truth_of(pair, unsure)
        if truth is None:
            continue
        a_ok, c_ok = pair.a_merged == truth, pair.c_merged == truth
        only_a += a_ok and not c_ok
        only_c += c_ok and not a_ok
    return only_a, only_c, mcnemar_exact(only_a, only_c)


def agreement(pairs: list[Pair]) -> dict:
    """討論前的原始答案；「不確定」併成「不是」。"""
    double = [p for p in pairs if p.label_b]
    fold = lambda label: NO if label == UNSURE else label  # noqa: E731
    first, second = [fold(p.label_a) for p in double], [fold(p.label_b) for p in double]
    agree = sum(x == y for x, y in zip(first, second))
    return {"n": len(double), "agree": agree, "raw": agree / len(double) if double else None,
            "kappa": cohen_kappa(first, second)}


# ── 報告 ──────────────────────────────────────────────────────────────────


def _rate(value: float | None, ci: tuple[float, float] | None = None, frac: str = "") -> str:
    if value is None:
        return "—（分母 0）"
    text = f"{value:.2f}"
    if ci:
        text += f"（{ci[0]:.2f}–{ci[1]:.2f}）"
    return f"{text} {frac}".strip()


def _table(pairs: list[Pair], unsure: str) -> list[str]:
    cross = [p for p in pairs if p.kind == "cross"]
    lines = [
        "| 方法 | Precision | Recall | F1 | 錯誤合併率 | 中英配對 Recall | TP／FP／FN／TN |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for method in ("A", "C"):
        c = confusion(pairs, method, unsure)
        x = confusion(cross, method, unsure)
        lines.append(
            f"| {method} "
            f"| {_rate(c.precision, wilson(c.tp, c.tp + c.fp), f'{c.tp}/{c.tp + c.fp}')} "
            f"| {_rate(c.recall, wilson(c.tp, c.tp + c.fn), f'{c.tp}/{c.tp + c.fn}')} "
            f"| {_rate(c.f1, bootstrap_f1(pairs, method, unsure))} "
            f"| {_rate(c.false_merge_rate, wilson(c.fp, c.fp + c.tn), f'{c.fp}/{c.fp + c.tn}')} "
            f"| {_rate(x.recall, wilson(x.tp, x.tp + x.fn), f'{x.tp}/{x.tp + x.fn}')} "
            f"| {c.tp}／{c.fp}／{c.fn}／{c.tn} |"
        )
    return lines


def _mcnemar_line(pairs: list[Pair], unsure: str = "exclude") -> str:
    only_a, only_c, p = mcnemar_a_vs_c(pairs, unsure)
    return f"exact McNemar：只有 A 判對 {only_a} 組、只有 C 判對 {only_c} 組，p = {p:.3f}"


def render_report(pairs: list[Pair], *, frozen_commit: str, annotators: str, generated: str) -> str:
    test = [p for p in pairs if p.split == "test"]
    dev = [p for p in pairs if p.split == "dev"]
    unsure_n = sum(p.final == UNSURE for p in test)
    agree = agreement(pairs)
    kappa = "—（沒有定義）" if agree["kappa"] is None else f"{agree['kappa']:.2f}"
    out = [
        "# 實驗一結果：事件聚合（方法 A vs C）",
        "",
        f"- 產生時間：{generated}；腳本 `scripts/exp1_results.py`",
        f"- `exp1-frozen`：`{frozen_commit}`（抽樣也在這個 commit，A、C 對每一組的判斷取自抽樣時的私有對照表，沒有重跑）",
        f"- 標註：{annotators}",
        f"- 配對：共 {len(pairs)} 組（dev {len(dev)}、test {len(test)}）。以下數字只用 test；「合併」為正。",
        "- 這些配對是依兩個方法意見是否一致分層抽的，正負比例是刻意安排的，數字只能比較方法，不能當成線上真實錯誤率。",
        "- 括號內是 95% 信賴區間：Precision、Recall、錯誤合併率用 Wilson 法，F1 用 bootstrap 2,000 次。",
        "",
        f"## 主分析（test，排除「不確定」{unsure_n} 組）",
        "",
        *_table(test, "exclude"),
        "",
        _mcnemar_line(test),
        "",
    ]
    for kind, name in (("same", "同語言"), ("cross", "中英")):
        layer = [p for p in test if p.kind == kind]
        out += [f"### {name}（{len(layer)} 組）", "", *_table(layer, "exclude"), "", _mcnemar_line(layer), ""]
    out += ["## 「不確定」的兩個版本", ""]
    if unsure_n == 0:
        out += ["test 沒有「不確定」的配對，兩個版本與主分析相同。", ""]
    else:
        for mode, name in (("yes", "全當「是」"), ("no", "全當「不是」")):
            out += [f"### 不確定{name}", "", *_table(test, mode), "", _mcnemar_line(test, mode), ""]
    out += [
        "## 標註一致程度",
        "",
        f"B 複標 {agree['n']} 組，用討論前的原始答案、「不確定」併成「不是」："
        + (f"直接一致 {agree['agree']}/{agree['n']}＝{agree['raw']:.2f}，Cohen's κ = {kappa}。" if agree["n"] else "沒有複標資料。"),
        "",
        "## 錯誤分析",
        "",
        "方法 C 在 test 判錯的配對如下。**請開發者從中挑 3 個，各寫一段為什麼錯**（手冊要求，腳本不代寫）。",
        "",
        "| pair_id | 語言 | 真實 | C | A | 標題 1 | 標題 2 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    wrong = [p for p in test if truth_of(p, "exclude") is not None and p.c_merged != truth_of(p, "exclude")]
    for p in wrong:
        cell = lambda text: text.replace("|", "／").replace("\n", " ")[:60]  # noqa: E731
        out.append(
            f"| {p.pair_id} | {'中英' if p.kind == 'cross' else '同語言'} | {p.final} "
            f"| {'合併' if p.c_merged else '沒合併'} | {'合併' if p.a_merged else '沒合併'} | {cell(p.title_1)} | {cell(p.title_2)} |"
        )
    if not wrong:
        out.append("| （C 在 test 沒有判錯的配對） | | | | | | |")
    out += ["", "1. （待寫）", "2. （待寫）", "3. （待寫）", ""]
    return "\n".join(out)
