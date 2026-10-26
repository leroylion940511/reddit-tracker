# 多來源收集層規格（v2.0 綜合日報）

把 [來源登錄表](SOURCE_REGISTRY.md) 中 `rss`／`rsshub` 來源的新項目收進 `source_items`，並記錄每次抓取的健康狀況。事件聚合、評分與選題是下一層，不在這裡做。

## 範圍

| 處理 | 不處理 |
| --- | --- |
| `method: rss`、`rsshub` 的來源 | `reddit`：沿用既有 `candidate_posts` 收集（Reddit RSS 限速嚴，不重複打） |
| 書目資訊：標題、摘要、連結、時間、作者、分類 | 全文：只在選題後針對入選事件讀取，且不長期保存（企劃 5.5） |
| 完全相同的重複（同網址、同標題） | 「不同媒體寫同一件事」的事件聚合（下一層） |
| | `json`／`csv` 數據欄來源（另做） |

## 資料表

### `source_items`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | int PK | |
| `source_id` | str(64), index | 登錄表 `id` |
| `section` | str(32), index | 收錄當下的登錄表板塊 |
| `tier` | str(2) | 收錄當下的登錄表層級 |
| `item_key` | str(40) | `sha1(guid 或正規化網址)`；`(source_id, item_key)` 唯一 |
| `url` | text | feed 給的原始連結 |
| `canonical_url` | text, index | 正規化網址（見下） |
| `title` | text | |
| `summary` | text | 純文字、最多 1,000 字；不存全文 |
| `lang` | str(8) | 登錄表 `lang` |
| `published_at` | datetime(tz), index | UTC；不可信時以 `first_seen_at` 代替 |
| `published_at_estimated` | bool | true 表示 `published_at` 是推估值 |
| `first_seen_at` | datetime(tz), index | 第一次收錄的 UTC 時間 |
| `title_fingerprint` | str(40), nullable, index | 正規化標題的 sha1；標題正規化後短於 8 字則為 null |
| `duplicate_of_id` | FK → `source_items.id`, nullable, index | 指向最早收錄的同一篇；null 表示這是「唯一項目」 |
| `metadata` | JSON | `author`、`categories` |

### `source_fetch_runs`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | int PK | |
| `source_id` | str(64), index | |
| `started_at` / `finished_at` | datetime(tz) | `started_at` 有 index |
| `ok` | bool | HTTP 2xx／304 且能解析 |
| `http_status` | int, nullable | |
| `not_modified` | bool | 304 |
| `items_returned` / `items_new` / `items_duplicate` | int | 本次回傳數、新收錄數、新收錄中屬重複者 |
| `etag` / `last_modified` | str, nullable | 供下次條件式請求 |
| `error` | text, nullable | 已遮蔽 RSSHub key |
| `elapsed_ms` | int | |

## 規則

- **正規化網址：** scheme 與 host 小寫、去掉 `www.`、去 fragment、去掉 `utm_*`／`fbclid`／`gclid`／`ref`／`from` 等追蹤參數、其餘參數排序、去掉結尾 `/`。
- **發布時間：** feed 時間早於 2000 年（例如聯合新聞網的 epoch 0）或晚於現在 1 小時以上視為不可信，改用 `first_seen_at` 並標 `published_at_estimated=true`。登錄表可用 `time_offset_hours` 修正已知時區錯誤（三立為 `-8`）。
- **重複：** 新項目若與既有項目 `canonical_url` 相同，或 `title_fingerprint` 相同且發布時間相差 72 小時內（機關常重用同一標題，見央行新聞稿），`duplicate_of_id` 指向最早那筆的根項目。同一來源重複出現的項目不新增。
- **抓取時機：** 每次 tick 只抓「距上次抓取已超過 `interval_min`」的來源；有上次的 ETag／Last-Modified 就送條件式請求。
- **並行：** HTTP 以 8 個 thread 並行；DB 寫入在呼叫端單一 thread 依序進行。RSSHub 逾時 90 秒，其他 30 秒。

## 介面

```python
# reddit_tracker/collection/normalize.py
canonicalize_url(url: str) -> str
title_fingerprint(title: str | None) -> str | None
resolve_published_at(parsed: datetime | None, seen_at: datetime, offset_hours: float = 0) -> tuple[datetime, bool]

# reddit_tracker/collection/collector.py
collect_due_sources(session, registry, *, now=None, only: set[str] | None = None, force=False,
                    fetcher=fetch_source) -> list[SourceCollectStats]
fetch_source(source: NewsSource, previous: SourceFetchRun | None) -> FetchOutcome

# reddit_tracker/collection/report.py
build_collection_report(session, registry, *, days=7, now=None) -> str  # Markdown
```

CLI：

```bash
uv run python -m reddit_tracker.collection run [--only id1,id2] [--force]
uv run python -m reddit_tracker.collection report [--days 7]
```

## 排程

newsroom scheduler 新增 `newsroom_source_collection`，每 `news_collection_tick_minutes`（預設 15）分鐘執行一次；只有 `NEWS_COLLECTION_ENABLED=true` 時才註冊，預設關閉，避免部署程式碼就改變線上行為。

## 七天收集驗收用的統計

`report` 依 Asia/Taipei 日曆日輸出：

- 每版每日新增的唯一項目數（`duplicate_of_id IS NULL`，以 `first_seen_at` 分日）
- 全站每日新增總數、重複率
- 每個來源的抓取次數、成功率、最後成功時間、連續失敗次數與近 7 日新增數
- 發布時間推估比例

**首日回補：** 第一次抓某來源時，feed 會一次回傳既有的 10–500 筆（央行一次 500 筆、多年舊稿），所以啟用當天的收錄量偏高。七天驗收從啟用後的第一個完整日曆日起算。

## 試跑紀錄（2026-10-26，production DB 複本）

- 第一輪：107 個來源 106 個成功，新增 4,525 筆、判為重複 233 筆，耗時約 100 秒。
- 第二輪（立即強制重抓）：只新增 20 筆真正的新稿；23 個來源回 304；沒有重複寫入。
- 天下 `/cw/today` 被上游 429，已把它和其他逐篇抓全文的 RSSHub 路由調為 120–240 分鐘一次。
