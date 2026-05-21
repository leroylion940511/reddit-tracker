"""讀 docs/m3_annotations.json，計算 Haiku/Minimax verdict vs manual_verdict 的指標。

輸出：
- accuracy = (manual == verdict) / N
- precision (track) = TP / (TP + FP)
- recall (track) = TP / (TP + FN)
- confusion matrix
- 錯誤模式聚焦：把 mismatch 那幾筆獨立列出（subreddit / Haiku reason / manual reason）

用法：
    uv run python scripts/m3_compute_baseline.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


ZH_SUBS = {"Taiwan", "HongKong", "China_irl", "taipei", "ChineseLanguage"}


def main() -> int:
    path = Path("docs/m3_annotations.json")
    data = json.loads(path.read_text())
    total = len(data)
    annotated = [d for d in data if d.get("manual_verdict") in ("track", "skip")]
    if len(annotated) < total:
        print(f"⚠️  {total - len(annotated)} 篇尚未標記")
    if not annotated:
        print("沒有已標記資料，先去填 manual_verdict")
        return 1

    n = len(annotated)
    tp = tn = fp = fn = 0
    matches: list[dict] = []
    mismatches: list[dict] = []

    for d in annotated:
        m = d["manual_verdict"]
        h = d["haiku"]["verdict"]
        if m == "track" and h == "track":
            tp += 1; matches.append(d)
        elif m == "skip" and h == "skip":
            tn += 1; matches.append(d)
        elif m == "skip" and h == "track":
            fp += 1; mismatches.append(d)
        elif m == "track" and h == "skip":
            fn += 1; mismatches.append(d)

    acc = (tp + tn) / n
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    zh = [d for d in annotated if d["subreddit"] in ZH_SUBS]
    en = [d for d in annotated if d["subreddit"] not in ZH_SUBS]
    zh_acc = sum(1 for d in zh if d["manual_verdict"] == d["haiku"]["verdict"]) / len(zh) if zh else 0.0
    en_acc = sum(1 for d in en if d["manual_verdict"] == d["haiku"]["verdict"]) / len(en) if en else 0.0

    print(f"N = {n}")
    print(f"accuracy  = {acc:.3f}")
    print(f"precision = {precision:.3f}    (track)")
    print(f"recall    = {recall:.3f}    (track)")
    print(f"f1        = {f1:.3f}    (track)")
    print()
    print("Confusion matrix (manual / scorer):")
    print(f"                scorer=track   scorer=skip")
    print(f"  manual=track  {tp:>5} (TP)   {fn:>5} (FN)")
    print(f"  manual=skip   {fp:>5} (FP)   {tn:>5} (TN)")
    print()
    print(f"by language:  zh n={len(zh)} acc={zh_acc:.3f}    en n={len(en)} acc={en_acc:.3f}")
    print()
    if mismatches:
        print(f"--- {len(mismatches)} mismatches ---")
        for d in mismatches:
            print(
                f"  #{d['candidate_id']:>4}  r/{d['subreddit']:<22}  "
                f"manual={d['manual_verdict']:<5} scorer={d['haiku']['verdict']:<5}  "
                f"score={d.get('score')} c={d.get('num_comments')}"
            )
            print(f"      title: {d['title'][:80]}")
            print(f"      scorer reason: {d['haiku'].get('reason', '')[:100]}")
            print(f"      manual reason: {d.get('manual_reason', '')[:100]}")
            print()

    # JSON dump 便於 doc 引用
    summary = {
        "n": n,
        "accuracy": round(acc, 4),
        "precision_track": round(precision, 4),
        "recall_track": round(recall, 4),
        "f1_track": round(f1, 4),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "zh_n": len(zh), "zh_acc": round(zh_acc, 4),
        "en_n": len(en), "en_acc": round(en_acc, 4),
    }
    Path("docs/m3_baseline_summary.json").write_text(json.dumps(summary, indent=2))
    print("→ wrote docs/m3_baseline_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
