# Reddit Tracker

素人爆文發現、追蹤與問答系統 — 透過 Reddit public JSON / RSS endpoint 做自動化探索、評分、收藏追蹤與對話式問答的流水線。

> v4。前身為 Threads Tracker (v1–v3)。Threads 第三方 scraper 月成本 $246 + cookie 認證風險高，整段重建到 Reddit。研究命題（素人爆文 → 後續事件 → 重量 context 問答）不變。

> **本分支策略**（`no-reddit-api`）：不申請 Reddit OAuth、不用 PRAW。
> 主走 public JSON endpoint；5/29 起 .json anonymous 被擋後 fallback 到 RSS（Plan C）。
> 月成本實測 **$1.5**（企劃預估 $15–36，便宜 10×）。

## 核心架構

雙環：每日推送主環 + 收藏追蹤副環。

```
探索層 (Subreddit /new RSS + 關鍵字 search, 90 min / 12 h)
    ↓
評分層 (硬規則 → Haiku 五軸 → 加權)
    ↓
候選排程層 (每日 09:00 Top 5 = 3 已爆 + 2 早期；Plan C fallback：主桶皆空時用 final_score top 5)
    ↓
推送層 (Telegram + inline button ❤️/👎/🔕)
    ↓ ❤️ 收藏
追蹤層 (分級輪詢 hot=15min / cooling=1h / archive=6h / >30d=終止)
    ↓ 四類後續事件偵測：作者新貼 / 作者留言 / 高分回應 / crosspost
後續推送 (milestone 即時 / digest 隨 daily push) + 問答層 (/ask <id> 重量 context 多輪)
```

## 技術棧

- Python 3.12 / `uv`
- Reddit data：`scrapers/json_public.py`（public JSON）+ `scrapers/rss.py`（Plan C fallback）；OAuth `praw_oauth.py` 留著未啟用
- python-telegram-bot
- LLM：預設 `web` provider，透過使用者手動登入的 ChatGPT 或 Gemini 網頁工作階段進行評分與問答（零 API key）；也保留 Anthropic / MiniMax / Fake 相容實作
- APScheduler / SQLAlchemy 2.0 / Alembic
- 預設 SQLite，可切 Postgres（`DATABASE_URL`）

## 快速開始

```bash
# 1. 依賴
uv sync

# 2. 環境變數（複製 .env.example → .env 後填值）
cp .env.example .env

# 3. 建 DB schema
uv run alembic upgrade head

# 4. 載 seeds（15 subreddit + 20 keyword）+ 跑一輪 discovery
uv run python scripts/m2_smoke.py

# 5. 連通性驗證（public JSON）
uv run python scripts/m1_hello.py

# 6. 持續運轉（scheduler 8 個 job）
uv run python -m reddit_tracker.scheduler
```

正式部署走 launchd（詳見 `deploy/`），caffeinate 確保 mac 不睡。

## 零 API-key LLM 設定（預設）

此做法參考 [Multi-AI Chat Desktop](https://github.com/teddashh/multi-ai-chat-desktop)：由使用者在官方網頁手動登入，再透過本機瀏覽器工作階段處理 prompt，而不是呼叫付費 API。它不會讀取帳密或 cookie、不會自動登入、也不會繞過 CAPTCHA、帳號限制或免費額度。

```bash
# 先開隔離的 Chrome profile，並在開出的分頁手動登入 ChatGPT 或 Gemini。
open -na "Google Chrome" --args --remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222 --user-data-dir="$HOME/.reddit-tracker-llm-profile"

# .env：LLM_PROVIDER=web，WEB_LLM_PROVIDER=chatgpt（或 gemini）
uv run python scripts/llm_web_session_doctor.py
```

`doctor` 回覆 `READY` 後，scheduler 的五軸評分與 Telegram `/ask` 會共用該工作階段，所有 API 成本記為 `$0`。為避免 scheduler 與 bot 同時寫入同一個網頁輸入框，請求會跨 process 序列化；免費帳號遇到速率／用量上限時，既有 pipeline 會記錄該筆失敗而非靜默改用付費 API。

## 里程碑完成度

| 里程碑 | 主題 | 狀態 |
|--------|------|------|
| M1 | Reddit data 可行性驗證 | ✅ public JSON 4 endpoint 80%+ 成功率 |
| M2 | 探索層 + DB 重構 | ✅ 12 表 schema / 雙 source / 5/5 tests |
| M3 | 評分層 | ✅ 三段式 + Haiku 對人工標記 accuracy 0.733 |
| M4 | 候選排程 + 推送層 | ✅ daily_push + breaking + Telegram 端到端 |
| M5 | 收藏追蹤層 | ✅ 升格 + tier polling + 四類偵測 + milestone |
| M6 | 問答層 | ✅ 多輪 chat + 重量 system prompt + idle sweep |
| M7 | 評估與調優 | 🟡 baseline + Plan C fallback + zh haiku retune；7.8 等 OAuth |
| M8 | 報告與 demo | 🟡 [`docs/report.md`](docs/report.md) 骨架 + Ch6 數據填中 |

詳細狀態：[`PROGRESS.md`](PROGRESS.md)（每次有進展更新）。

## 專案文件

| 檔案 | 用途 |
|------|------|
| [`PROGRESS.md`](PROGRESS.md) | 跨 session 單一狀態真相 |
| [`SCHEDULE.md`](SCHEDULE.md) | 任務級里程碑（M1–M8 細項） |
| [`reddit_tracker_proposal.md`](reddit_tracker_proposal.md) | 完整企劃書 v4 |
| [`docs/v4_schema.md`](docs/v4_schema.md) | 12 表 ER 圖 |
| [`docs/m1_public_endpoints_probe.md`](docs/m1_public_endpoints_probe.md) | M1 endpoint 可行性實測 |
| [`docs/m3_haiku_baseline.md`](docs/m3_haiku_baseline.md) | M3 Haiku verdict vs 人工標記對比 |
| [`docs/m7_baseline_2026-06-02.md`](docs/m7_baseline_2026-06-02.md) | M7 baseline 評估 |
| [`docs/m7_haiku_fail_analysis.md`](docs/m7_haiku_fail_analysis.md) | M7.6 zh prompt retune 診斷 |
| [`docs/report.md`](docs/report.md) | M8 期末報告（撰寫中） |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | AI agent 協作規範 |

## OAuth 申請狀態

`no-reddit-api` 分支不申請 OAuth；但 `praw_oauth.py` 實作留著，待 Reddit Data Access Request 通過後可一行切換。詳見 [`docs/m1_public_endpoints_probe.md`](docs/m1_public_endpoints_probe.md)。

申請動機與後續計畫：[M7 Reddit Data Access Request 已申請中](PROGRESS.md)（等回覆，可解鎖 7.8 QA 自評 / dislike 樣本累積）。
