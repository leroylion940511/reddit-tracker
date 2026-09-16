# v5 架構與切換策略

## 決策：沿用 repo，不 fork、不重建

v4 已有四項高價值能力：RSS／Reddit 擷取、SQLite + Alembic、Gemini LLM adapter、Telegram bot + FastAPI dashboard。v5 應保留這些 infrastructure，替換舊的 scoring/feed/promotion 產品流。獨立 Git branch `codex/ai-newsroom-foundation` 提供切換隔離；不需要維護第二個 repo 或同步 fork。

## 目標資料流

```text
Reddit/RSS → candidate_posts → calendar-window builder
     → ReaderProfile → scout pitches → assignment plan
     → evidence briefs → story drafts → edition → Telegram
                                      └→ web newsroom ledger
feedback → profile adjustment → next edition
```

## 可重用與替換邊界

| 保留／延伸 | 取代／退役於 v5 上線後 |
| --- | --- |
| `scrapers/`, `services/discovery.py`, `CandidatePost`, `SubredditSource`, `db.py`, `config.py`, LLM factory, Telegram transport, FastAPI 基礎 | `services/feed.py` 的 Top-5 picker、`DailyPush` 為中心的呈現、收藏追蹤／QA 作為主產品流程 |

舊 M5/M6 模組不是第一版新聞室的依賴；在 v5 穩定前保留程式與資料，避免不必要的破壞性移除。

## 新資料模型（migration 設計，尚未執行）

| Table | 用途 |
| --- | --- |
| `reader_profiles` | 一位或多位讀者的自然語言偏好、主題、來源、排除項與時區 |
| `reader_feedback` | ❤️／🚫／👀，可連到 edition item 與 candidate |
| `newsroom_editions` | 發行日期、讀者、狀態、Telegram message ref、版面摘要 |
| `edition_items` | brief／feature／breaking 的順序、稿件、來源、可信度與 warnings |
| `agent_runs` | 一次 stage 執行的狀態、輸入版本、時間、錯誤 |
| `agent_artifacts` | 可公開檢視的結構化 artifact JSON、摘要、來源引用 |

`candidate_posts` 繼續作為不可變來源快取。每期必須儲存所用 candidate id，確保日後可重現。

## 每日排程

| 時間（Asia/Taipei） | 動作 |
| --- | --- |
| 00:05 | 鎖定昨天 00:00–23:59 的候選 window |
| 05:30–08:10 | profile → scout → assignment → verification → writing → chief editing |
| 08:10–08:25 | 允許一次早報快訊判定與品質 gate |
| 08:30 | 發行 Telegram edition，寫入發行與 artifact ledger |

初期採同步、可重跑的 orchestrator；每 stage 以 DB run record 做 idempotency key `(edition_id, stage, attempt)`。在單機 SQLite 下，版次的寫入由單一 orchestrator 序列化，避免重演 v4 的多 process lock 問題。

## 轉換安全程序

1. 在新 branch 完成單元、整合與 dry-run 測試。
2. 使用控制台停止 v4 scheduler 和 bot，確認沒有 `reddit_tracker` worker process。
3. 建立帶時間戳的 SQLite backup，執行 Alembic migration，檢查 `PRAGMA integrity_check`。
4. 先跑一個指定日期的 dry-run edition，不送 Telegram；在網頁檢閱 artifacts。
5. 人工確認一份 Telegram preview 後，才啟用 v5 edition scheduler。
6. 保留 v4 DB backup 與 rollback 指令；不在未備份的 running DB 上試 migration。
