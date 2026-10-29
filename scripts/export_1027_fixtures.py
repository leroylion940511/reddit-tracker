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

重編會讓 cluster_id 重新編號，之後的回歸測試請用素材 id 比對。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

EDITION_DATE = "2026-10-27"
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
    print(f"clusters={meta['cluster_count']} items={meta['item_count']} merges={len(merges)}")
    print(json.dumps(meta["e01"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
