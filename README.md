# Reddit Tracker

個人化 Reddit AI 每日報紙 — 將中英文 Reddit 討論編採為附來源、繁體中文的每日報紙，於每天 08:30（Asia/Taipei）送達 Telegram。

> 目前為 v5 AI Newsroom，已於 2026-09-19 至 2026-09-25 通過七日試刊 gate。v4 的探索、收藏追蹤與問答程式仍保留，但舊 scheduler／Bot 維持 disabled，避免重複推播。

> **本分支策略**（`no-reddit-api`）：不申請 Reddit OAuth、不用 PRAW。
> 主走 public JSON endpoint；5/29 起 .json anonymous 被擋後 fallback 到 RSS（Plan C）。
> 月成本實測 **$1.5**（企劃預估 $15–36，便宜 10×）。

## 核心架構

目前主產品是新聞室；v4 的 daily Top-5、收藏追蹤與問答則保留為既有模組，不參與日常新聞室排程。

```
候選探索（Subreddit RSS，90 分鐘）
    ↓
前一個台灣日曆日候選 → reader profile → scout／assignment
    ↓
evidence／繁中 writing／chief editing（05:30，保存 draft）
    ↓
Telegram 每日報紙（08:30）＋網頁編輯室／回饋
```

## 技術棧

- Python 3.12 / `uv`
- Reddit data：`scrapers/json_public.py`（public JSON）+ `scrapers/rss.py`（Plan C fallback）；OAuth `praw_oauth.py` 留著未啟用
- python-telegram-bot
- LLM：預設 Gemini Developer API（M3：Gemini 3.5 Flash-Lite；M6：Gemini 3.5 Flash），含免費額度保護與 browser fallback；也保留手動登入網頁、Anthropic、MiniMax、Fake 相容實作
- APScheduler / SQLAlchemy 2.0 / Alembic
- 預設 SQLite，可切 Postgres（`DATABASE_URL`）

## 快速開始

```bash
# 1. 依賴（包含測試工具）
uv sync --all-groups

# 2. 環境變數（複製 .env.example → .env 後填值）
cp .env.example .env

# 3. 建 DB schema
uv run alembic upgrade head

# 4. 離線驗證完整新聞室流程（不讀 production DB、不送 Telegram）
uv run python -m reddit_tracker.newsroom.demo --open

# 5. 完整測試
uv run --group dev python -m pytest -q
```

正式新聞室以 launchd 執行 candidate discovery（90 分鐘）、05:30 編採與 08:30 發行。涉及 production schema 的部署必須使用 `deploy/install_launchd.sh newsroom-deploy`，它會先建立 SQLite backup；詳見 [`docs/v5/ARCHITECTURE.md`](docs/v5/ARCHITECTURE.md)。

## 本機控制台

啟動控制台後會自動開啟瀏覽器；它只監聽 `127.0.0.1:8765`，不會把資料庫、
Telegram 對話或服務控制功能暴露到網路。

```bash
uv run python -m reddit_tracker.web
```

控制台可查看每日報紙、來源健康、可檢視 agent artifact、讀者偏好、網頁 ❤️／🚫／👀 回饋與服務日誌；服務控制只會操作 v5 新聞室。舊 v4 scheduler 維持停用。Telegram callback receiver 已於 2026-09-25 依明確授權啟用，因此 Telegram 按鈕與網頁回饋都會寫入同一份 reader feedback ledger。

## Gemini Free Tier API（預設）

將 key 只寫進本機 `.env`，不應提交或貼進文件。M3 與 M6 共用保守的跨 process
額度保護：評分每日 450 次、QA 每日 50 次、每分鐘 5 次；日界線採 Gemini 的 Pacific
time。API 回傳 429 時會最多重試兩次，仍受限才改走下方已登入的 browser provider。

```bash
# .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...            # 僅本機 .env
GEMINI_SCORING_MODEL=gemini-3.5-flash-lite
GEMINI_QA_MODEL=gemini-3.5-flash
GEMINI_FALLBACK_PROVIDER=web
```

實際 Free Tier RPM／TPM／RPD 以 Google AI Studio 專案頁面為準；若確認有餘裕，再從
控制台提高每日限制。不要一次重跑所有舊評分紀錄。

## 已登入網頁 LLM fallback

此做法參考 [Multi-AI Chat Desktop](https://github.com/teddashh/multi-ai-chat-desktop)：由使用者在官方網頁手動登入，再透過本機瀏覽器工作階段處理 prompt，而不是呼叫付費 API。它不會讀取帳密或 cookie、不會自動登入、也不會繞過 CAPTCHA、帳號限制或免費額度。

```bash
# 先開隔離的 Chrome profile，並在開出的分頁手動登入 ChatGPT 或 Gemini。
open -na "Google Chrome" --args --remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222 --user-data-dir="$HOME/.reddit-tracker-llm-profile"

# Gemini 額度耗盡時使用的 fallback。也可單獨設 LLM_PROVIDER=web。
WEB_LLM_PROVIDER=chatgpt # 或 gemini
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
| N0–N5 | v5 AI Newsroom foundation、編採、發行、控制台 | ✅ 已部署並具備來源可追溯與安全 fallback |
| N6 | v5 七日試刊 | ✅ 2026-09-19 至 2026-09-25 7/7 準時出刊、來源完整 |

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
| [`docs/v5/README.md`](docs/v5/README.md) | v5 AI Newsroom 規格、運作狀態與文件入口 |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | AI agent 協作規範 |

## OAuth 申請狀態

`no-reddit-api` 分支不申請 OAuth；但 `praw_oauth.py` 實作留著，待 Reddit Data Access Request 通過後可一行切換。詳見 [`docs/m1_public_endpoints_probe.md`](docs/m1_public_endpoints_probe.md)。

申請動機與後續計畫：[M7 Reddit Data Access Request 已申請中](PROGRESS.md)（等回覆，可解鎖 7.8 QA 自評 / dislike 樣本累積）。
