# 來源登錄表規格（v2.0 綜合日報）

多來源收集的單一設定來源。檔案：`reddit_tracker/seeds/news_sources.yaml`；loader：`reddit_tracker/seeds/news_sources.py`；探測：`scripts/probe_news_sources.py`。

## 檔案結構

```yaml
version: 1
sections:            # 板塊 key → 顯示名稱
  taiwan: 台灣
  ...
sources:
  - {id: cna-politics, name: 中央社 政治, section: taiwan, tier: T2, method: rsshub, url: /cna/aipl, lang: zh-Hant}
```

## `sources[]` 欄位

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| `id` | str | ✅ | 全域唯一、kebab-case；日後寫入 `source_items.source_id` |
| `name` | str | ✅ | 顯示名稱 |
| `section` | str | ✅ | 必須是 `sections` 中的 key |
| `tier` | `T1`／`T2`／`T3`／`T4` | ✅ | T1 官方一手、T2 專業媒體、T3 專業社群與資料、T4 大眾社群（企劃 5.2） |
| `method` | `rss`／`rsshub`／`json`／`csv`／`reddit` | ✅ | 取得方式 |
| `url` | str | ✅ | `rss`／`json`／`csv`：完整 https 網址；`rsshub`：以 `/` 開頭的路由；`reddit`：subreddit 名稱 |
| `lang` | str | ✅ | `zh-Hant`、`zh`、`en`、`ja` |
| `interval_min` | int | | 抓取間隔（分鐘），預設 60 |
| `enabled` | bool | | 預設 true；停用時必須在 `notes` 寫原因與日期 |
| `requires_key` | str | | 需要的 `.env` 變數名（只寫名稱，不寫值） |
| `time_offset_hours` | float | | 修正已知時區錯誤，加到解析出的發布時間上；預設 0 |
| `general_feed` | bool | | 綜合 feed（各類新聞混在一起）；`section` 只是預設值，不參與事件板塊投票。預設 false |
| `notes` | str | | 停用原因、資料品質備註 |

## Loader 介面

```python
load_registry(path=DEFAULT_REGISTRY_PATH) -> SourceRegistry
SourceRegistry.enabled() -> list[NewsSource]
SourceRegistry.general_source_ids() -> frozenset[str]
NewsSource.request_url(rsshub_base_url: str, rsshub_access_key: str | None) -> str
```

驗證規則：`id` 不可重複、`section` 必須已定義、各 `method` 的 `url` 形狀必須正確。

## 設定（`.env`）

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `RSSHUB_BASE_URL` | `http://127.0.0.1:1200` | 本機 RSSHub |
| `RSSHUB_ACCESS_KEY` | 無 | 與 `~/rsshub/.env` 的 `ACCESS_KEY` 相同；不得寫入登錄表、DB、log 或報告 |
| `NEWS_SOURCES_PATH` | `reddit_tracker/seeds/news_sources.yaml` | 登錄表路徑 |

## 本機 RSSHub

- 位置 `~/rsshub`（不放 `~/Documents`，避開 launchd 的 TCC 限制）；不併入本 repo（AGPL-3.0）。
- 安裝：`npx -y pnpm@<packageManager 版本> install && npx -y pnpm@<同版本> build`。
- `.env` 需 `ACCESS_KEY`、`CACHE_TYPE=memory`、`LISTEN_INADDR_ANY=0`。
- 常駐：launchd `com.leroy.reddit-tracker.rsshub`（2026-10-26 依使用者同意安裝），由 `deploy/install_launchd.sh rsshub-install`／`rsshub-uninstall` 管理；plist 內再次固定 `LISTEN_INADDR_ANY=0` 與 `NODE_ENV=production`，log 在 `~/rsshub/rsshub.log`。
- 更新 RSSHub：`git -C ~/rsshub pull`、重新 install／build，再執行 `deploy/install_launchd.sh rsshub-install`。
