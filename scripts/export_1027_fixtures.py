"""從 10/27 唯讀母本匯出回歸集用的分組與跨語言合併 fixture（手冊步驟 0）。

用法：
    uv run python scripts/export_1027_fixtures.py [--db data/snapshots/2026-10-27.db]
        [--out tests/regression/fixtures]

母本只用 SQLite URI `mode=ro&immutable=1` 開，絕不寫入。輸出三個檔：

- `1027_groups.json`：`{cluster_id: [source_item_id, ...]}`。母本是 10/29 才從
  production 複製的，之後的素材也會被聚合進同一個 cluster，所以只收
  `first_seen_at` 不晚於 10/27 那期 `prepared_at`（台北 06:00）的素材，也就是
  那期編輯會議看到的分組；沒有任何這種素材的 cluster 不收。聚合本來就只處理
  72 小時窗內的稿，全部收進來約 2.8k 個 cluster、3.9k 篇，不必再縮窗。
- `1027_merges.json`：那期 `daily_editions.stats.merged_groups` 逐組轉成素材 id
  `[[source_item_id, ...], ...]`，順序與原本的組一一對應（原組是 LLM 回傳的
  兩兩配對，可能重疊，`apply_merges` 依序處理，所以不先求連通分量）。
- `1027_meta.json`：追溯資訊，含母本 sha256、截止時間、cluster id 版本的
  merged_groups、刊出稿用到的 cluster，以及 E01（美式足球素材）的查證結果。
- `1027_items.json.xz`（步驟 2）：回歸集離線重編用的素材子集＝截止前收到、
  `published_at` 在第一次聚合的 72 小時窗內的素材（不含 cluster_id，重編時重算），
  以及線上當時的聚合時間表 `cluster_runs_utc`：第一次聚合是 10/26 22:53（台北，
  見 PROGRESS「事件聚合上線」），之後每輪收集完立刻聚合，所以取每輪收集素材的
  最晚 `first_seen_at`。重編照這個時間表逐輪聚合，才重現得出當期的分組。
  摘要截到 400 字（聚合用 300、證據包用 400），根素材不在窗內的重複稿不收；
  `canonical_url` 一律等於 `canonicalize_url(url)`（匯出時驗證），所以不存。
  xz 壓縮輸出穩定，重跑逐位元相同。
- `1027_edition.json`（步驟 2）：10/27 實際刊出的 42 則（版別、標題、正文、出處）
  與數據欄，回歸集用它證明每個案例的條件確實抓得到當期的錯。

重編會讓 cluster_id 重新編號，之後的回歸測試請用素材 id 比對。
"""

from __future__ import annotations

import argparse
import lzma
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reddit_tracker.collection.normalize import canonicalize_url  # noqa: E402

EDITION_DATE = "2026-10-27"
CLUSTER_WINDOW_HOURS = 72  # 與 collection/clustering.py 的 WINDOW 一致
FIRST_CLUSTER_RUN_UTC = "2026-10-26 14:53:00.000000"  # 聚合首次上線 22:53（台北）
ITEM_SUMMARY_CHARS = 400  # 與 daily/evidence.py 的 EVIDENCE_SUMMARY_CHARS 一致
ITEM_FIELDS = (
    "id", "source_id", "section", "tier", "url", "canonical_url", "title", "summary", "lang",
    "published_at", "published_at_estimated", "first_seen_at", "duplicate_of_id",
)
E01_TITLE_PATTERN = "%Smith-Njigba%"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export(db_path: Path) -> tuple[dict, list, dict]:
    conn = _connect_readonly(db_path)
    edition_id, prepared_at, window_start, stats_text = conn.execute(
        "SELECT id, prepared_at, window_start, stats FROM daily_editions WHERE edition_date = ?",
        (EDITION_DATE,),
    ).fetchone()
    stats = json.loads(stats_text)

    groups: dict[str, list[int]] = {}
    for item_id, cluster_id in conn.execute(
        "SELECT id, cluster_id FROM source_items"
        " WHERE cluster_id IS NOT NULL AND first_seen_at <= ? ORDER BY cluster_id, id",
        (prepared_at,),
    ):
        groups.setdefault(str(cluster_id), []).append(item_id)

    merged_groups = stats.get("merged_groups", [])
    merges = [[item for cid in group for item in groups.get(str(cid), [])] for group in merged_groups]

    articles = []
    for cluster_id, section, headline, signals, sources in conn.execute(
        "SELECT cluster_id, section, headline, signals, sources FROM daily_articles"
        " WHERE edition_id = ? ORDER BY id",
        (edition_id,),
    ):
        merged_ids = json.loads(signals or "{}").get("merged_cluster_ids", [])
        articles.append(
            {
                "cluster_id": cluster_id,
                "merged_cluster_ids": merged_ids,
                "section": section,
                "headline": headline,
                "source_urls": [s["url"] for s in json.loads(sources or "[]")],
            }
        )

    referenced = {a["cluster_id"] for a in articles} | {i for a in articles for i in a["merged_cluster_ids"]}
    referenced |= {i for g in merged_groups for i in g}
    missing = sorted(i for i in referenced if str(i) not in groups)
    if missing:
        raise SystemExit(f"這些 cluster 在截止時間前沒有素材，fixture 不完整：{missing}")
    # 驗證截止時間選得對：每則刊出稿的出處都要落在它（含併入）的 cluster 分組裡
    url_of = dict(conn.execute("SELECT id, url FROM source_items WHERE first_seen_at <= ?", (prepared_at,)))
    for article in articles:
        cluster_ids = [article["cluster_id"], *article["merged_cluster_ids"]]
        urls = {url_of[i] for cid in cluster_ids for i in groups[str(cid)]}
        stray = [u for u in article["source_urls"] if u not in urls]
        if stray:
            raise SystemExit(f"cluster {article['cluster_id']} 的刊出出處不在截止時間前的分組裡：{stray}")

    meta = {
        "edition_date": EDITION_DATE,
        "snapshot": str(db_path),
        "snapshot_sha256": _sha256(db_path),
        "cutoff_first_seen_at_utc": prepared_at,
        "edition_window_start_utc": window_start,
        "cluster_count": len(groups),
        "item_count": sum(len(v) for v in groups.values()),
        "merged_groups_cluster_ids": merged_groups,
        "articles": [{k: v for k, v in a.items() if k != "source_urls"} for a in articles],
        "e01": _trace_e01(conn, articles, merged_groups, groups),
    }
    conn.close()
    return groups, merges, meta


def export_items(db_path: Path) -> dict:
    """離線重編需要的素材：截止前收到、發布時間在聚合窗內。"""
    conn = _connect_readonly(db_path)
    (prepared_at,) = conn.execute(
        "SELECT prepared_at FROM daily_editions WHERE edition_date = ?", (EDITION_DATE,)
    ).fetchone()
    (window_start,) = conn.execute(
        "SELECT strftime('%Y-%m-%d %H:%M:%f', ?, ?)", (FIRST_CLUSTER_RUN_UTC, f"-{CLUSTER_WINDOW_HOURS} hours")
    ).fetchone()
    # 收集每輪的素材 first_seen_at 落在同一分鐘內；首輪（回補）在聚合上線前就收好了。
    runs = [FIRST_CLUSTER_RUN_UTC] + [
        last
        for (last,) in conn.execute(
            "SELECT max(first_seen_at) FROM source_items WHERE first_seen_at > ? AND first_seen_at <= ?"
            " GROUP BY substr(first_seen_at, 1, 16) ORDER BY 1",
            (FIRST_CLUSTER_RUN_UTC, prepared_at),
        )
    ]
    rows = conn.execute(
        f"SELECT {', '.join(ITEM_FIELDS)} FROM source_items"
        " WHERE first_seen_at <= ? AND published_at >= ? ORDER BY id",
        (prepared_at, window_start),
    ).fetchall()
    conn.close()
    items = [dict(zip(ITEM_FIELDS, row)) for row in rows]
    ids = {item["id"] for item in items}
    kept = []
    for item in items:
        if item["duplicate_of_id"] is not None and item["duplicate_of_id"] not in ids:
            continue  # 根素材不在窗內：聚合本來就不會替它指派事件
        if canonicalize_url(item["url"]) != item.pop("canonical_url"):
            raise SystemExit(f"source_item {item['id']} 的 canonical_url 不能由 url 重算，fixture 要改存")
        item["summary"] = (item["summary"] or "")[:ITEM_SUMMARY_CHARS] or None
        item["published_at_estimated"] = bool(item["published_at_estimated"])
        kept.append(item)
    return {
        "edition_date": EDITION_DATE,
        "now_utc": prepared_at,
        "window_start_utc": window_start,
        "cluster_runs_utc": runs,
        "items": kept,
    }


def export_edition(db_path: Path) -> dict:
    """10/27 實際刊出的版面：回歸案例在原始錯誤上必須抓得到（證明條件有效）。"""
    conn = _connect_readonly(db_path)
    edition_id, stats_text = conn.execute(
        "SELECT id, stats FROM daily_editions WHERE edition_date = ?", (EDITION_DATE,)
    ).fetchone()
    fields = (
        "cluster_id", "section", "position", "is_front", "kind", "writer", "headline", "deck", "body",
        "why_it_matters", "sources", "review_notes",
    )
    articles = []
    for row in conn.execute(
        f"SELECT {', '.join(fields)} FROM daily_articles WHERE edition_id = ? ORDER BY id", (edition_id,)
    ):
        article = dict(zip(fields, row))
        article["is_front"] = bool(article["is_front"])
        article["sources"] = json.loads(article["sources"] or "[]")
        article["review_notes"] = json.loads(article["review_notes"] or "[]")
        articles.append(article)
    conn.close()
    return {"edition_date": EDITION_DATE, "market": json.loads(stats_text).get("market"), "articles": articles}


def _trace_e01(conn, articles, merged_groups, groups) -> dict:
    """找出 AP 美式足球素材原本的 cluster，以及它怎麼進到刊出稿。"""
    rows = conn.execute(
        "SELECT si.id, si.source_id, si.lang, si.title, si.cluster_id, sc.lang_group, sc.title"
        " FROM source_items si LEFT JOIN story_clusters sc ON sc.id = si.cluster_id"
        " WHERE si.title LIKE ?",
        (E01_TITLE_PATTERN,),
    ).fetchall()
    items = []
    for item_id, source_id, lang, title, cluster_id, lang_group, cluster_title in rows:
        url = conn.execute("SELECT url FROM source_items WHERE id = ?", (item_id,)).fetchone()[0]
        items.append(
            {
                "source_item_id": item_id,
                "source_id": source_id,
                "lang": lang,
                "title": title,
                "cluster_id": cluster_id,
                "cluster_lang_group": lang_group,
                "cluster_title": cluster_title,
                "cluster_items_at_cutoff": len(groups.get(str(cluster_id), [])),
                "merged_groups_containing_cluster": [g for g in merged_groups if cluster_id in g],
                "published_in_articles": [
                    {"cluster_id": a["cluster_id"], "headline": a["headline"]}
                    for a in articles
                    if url in a["source_urls"]
                ],
            }
        )
    return {"title_pattern": E01_TITLE_PATTERN, "items": items}


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("data/snapshots/2026-10-27.db"))
    parser.add_argument("--out", type=Path, default=Path("tests/regression/fixtures"))
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"找不到母本 {args.db}", file=sys.stderr)
        return 1
    groups, merges, meta = export(args.db)
    args.out.mkdir(parents=True, exist_ok=True)
    _dump(args.out / "1027_groups.json", groups)
    _dump(args.out / "1027_merges.json", merges)
    _dump(args.out / "1027_meta.json", meta)
    items = export_items(args.db)
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (args.out / "1027_items.json.xz").write_bytes(
        lzma.compress(payload, preset=9 | lzma.PRESET_EXTREME)
    )
    _dump(args.out / "1027_edition.json", export_edition(args.db))
    print(f"rebuild items={len(items['items'])} window_start={items['window_start_utc']}")
    print(f"clusters={meta['cluster_count']} items={meta['item_count']} merges={len(merges)}")
    print(json.dumps(meta["e01"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
