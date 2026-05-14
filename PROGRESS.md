# Reddit Tracker — 專案進度（v4 / Reddit pivot 起始）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 完整企劃見 `reddit_tracker_proposal.md`、任務級里程碑見 `SCHEDULE.md`。
> 進度以里程碑（M1–M8）追蹤，不用週數。

**Last updated:** 2026-05-14（專案剛 bootstrap，所有里程碑未啟動）

---

## 緣由

前身為 Threads Tracker (v1–v3)。v3 進行到 M3 主幹完成後，重新評估發現 Threads 資料源（Apify Scraper）月成本 $246、且公開搜尋的 cookie 認證風險長期難解。決定整個改建到 Reddit：

- 官方 API（PRAW）免費，月成本估 $15–36，降幅 ~90%
- 留言原生樹狀結構，crosspost 一行 API 即可拿——v3 在 Threads 上 quote 抓不到的問題消失
- Subreddit 是天然主題容器，比關鍵字搜尋更穩定

研究命題與三段式互動（探索 → 推送 → 收藏追蹤 → 問答）完全沿用。

---

## v4 里程碑完成度

| 里程碑 | 主題 | 狀態 | 備註 |
|--------|------|------|------|
| M1 | Reddit API 可行性驗證 | ❌ | 申請 OAuth app、PRAW hello world、確認 100 QPM 額度 |
| M2 | 探索層 + DB 重構 | ❌ | Reddit schema、subreddit + keyword 雙 source、60 分鐘輪詢 |
| M3 | 評分層接 Reddit | ❌ | 硬規則 / Haiku 五軸 / 加權；30 篇人工標記驗證 |
| M4 | 候選排程 + 推送層 | ❌ | 每日 09:00 Top 5、inline button、即時破例 |
| M5 | 收藏追蹤層 | ❌ | 升格邏輯、分級輪詢、四類後續事件偵測（含 crosspost）|
| M6 | 問答層 | ❌ | `/ask` 對話模式、重量 context 組裝（comment tree）|
| M7 | 評估與調優 | ❌ | 收藏率、後續命中率、中英 subreddit 對照 |
| M8 | 報告與 demo | ❌ | 案例分析 + 問答自評 |

---

## 從舊 Threads Tracker 可移植的資產

**可整段移植（無需改）**：

| 舊檔 | 用途 |
|------|------|
| `config.py` / `db.py` / `cli.py` / `logging.py` | 基礎設施 |
| `llm/base.py` / `factory.py` / `opus.py` / `minimax.py` / `haiku.py` | LLM provider 抽象 + Haiku 評分入口 |
| `services/summarization.py` | EvolutionSummary + 24h cache |
| `services/scoring.py` | 三段式（rules → haiku → final），硬規則閾值要改 Reddit 欄位 |
| `services/polling.py` 的 tier_for_age + select_due_posts | 分級輪詢演算法 |
| `bot/handlers.py` 的 inline button callback 框架 | 三按鈕（❤️ / 👎 / 🔕）流程 |
| `tests/test_summarization.py` `test_llm.py` 大部分 | 改 mock 資料即可 |
| `scheduler.py` 的 job 結構 | 改 job 內部、頻率、新增 subreddit polling |

**需重寫**：

| 模組 | 原因 |
|------|------|
| `scrapers/apify.py` `watcher.py` `factory.py` | 整個刪掉，改寫 `scrapers/reddit.py`（PRAW wrapper） |
| `models.py` | schema 大改：`reddit_post_id`、`subreddit`、`author_karma`、`upvote_ratio`；新增 `subreddit_sources` 表 |
| `alembic/versions/*` | 重生 migration |
| `services/discovery.py` | 主軸由 keyword 改為 subreddit /new，keyword 降為輔助 |
| `services/detection.py` | 改用 PRAW comment tree + submission.duplicates() |
| `seeds/*` | 新增 subreddit 名單 + 中英文雙 keyword 種子池 |
| `tests/test_discovery.py` `test_smoke.py` | 跟著 schema 改 |

舊 repo 路徑：`/Users/leroy/Documents/Developer/Project/threads_tracker`（v3 已併入 master）。

---

## 下一步（單一優先）

**M1.1**：到 https://www.reddit.com/prefs/apps 註冊「personal use script」類型 app，取 `client_id` / `client_secret`，寫進新 repo 的 `.env`。

完整 M1 任務清單見 `SCHEDULE.md`。

---

## 環境檢查（新 repo 初始化用）

```bash
# 1. 建新 repo
mkdir reddit_tracker && cd reddit_tracker
git init
uv init --python 3.11

# 2. 加核心依賴
uv add praw python-telegram-bot anthropic apscheduler fastapi sqlalchemy alembic
uv add --dev pytest pytest-asyncio

# 3. 把這資料夾的 5 個 .md 移進新 repo 根目錄

# 4. PRAW 連線測試（M1.2）
uv run python -c "import praw; r = praw.Reddit(client_id='...', client_secret='...', user_agent='reddit_tracker/0.1 by <你的 Reddit username>'); print(r.read_only)"
```

---

## 沿用 v3 踩過的坑（直接記下避免重踩）

- SQLite BigInt PK 不會 auto-increment → `BigInteger().with_variant(Integer(), "sqlite")`
- alembic 自訂 type（`JSONField`）找不到 → `alembic/script.py.mako` 加 `import <pkg>.models`
- scraper factory 沒設 token 自動 fallback fake（Reddit 版可沿用此 pattern）
- 預設 SQLite，切 Postgres 改 `DATABASE_URL`
- APScheduler 排程頻率取 `poll_hot_minutes // 3`
- `LLMSummary.content` 存 JSON 字串（不開新欄位），`parse_evolution()` 還原
- summarization 24h cache 用「最新 evolution row 的 `generated_at`」判斷
- LLM provider 抽到 `llm/factory.py`，`LLM_PROVIDER=anthropic|minimax` 切
- LLM 回傳的 JSON 容忍 ` ```json ` fence

---

## v4 新引入的設計決策（待驗證）

- **Subreddit /new 為主、關鍵字為輔**：12–20 個目標 sub、每 60 分鐘掃；keyword 每 6 小時跑一次補事件性貼文
- **中英混合**：r/Taiwan、r/HongKong 等中文 sub + r/TIFU 等英文 storytelling sub；報告需做語言分布分析
- **每日推送 5 篇 = 3 已爆 + 2 早期**：固定配比，可由 config 調整
- **問答 context 比 v3 肥 50%**：Reddit comment tree 樹狀且更長，重量 context 預估 12k–45k input tokens（v3 是 8k–35k）
- **個位數使用者共用同一份每日推送**：先不做個人化
- **PRAW QPM 控制**：保持 < 60 QPM（保留 buffer，hard limit 是 100）

---

## 已知未驗證 / 風險

- Reddit API 政策變動（2023 Apollo 事件 precedent）— M1 註冊時選對類型即可，但長期需留意
- 中文 subreddit 樣本量不足（每日 50–100 篇）→ 英文 sub 作為主要樣本
- 重量 context 問答 token 成本（預估 $0.15/次）— M6 實測
- PRAW 對 deleted / removed 貼文的處理（content = `[deleted]` / `[removed]`）需在 scraper 層判斷
- 沒有推播 retry / rate limit 處理（沿用 v3 待補）
