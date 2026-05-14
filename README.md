# Reddit Tracker

素人爆文發現、追蹤與問答系統 — 基於 Reddit 官方 API（PRAW）的自動化探索 / 評分 / 收藏追蹤 / 對話式問答流水線。

> v4。前身為 Threads Tracker (v1–v3)，因 Threads 第三方 scraper 月成本 $246 與 cookie 認證風險過高，重建到 Reddit 官方 API（月成本估 $15–36，降幅 ~90%）。研究命題不變，僅換資料源與抽取邏輯。

## 核心架構

雙環：每日推送主環 + 收藏追蹤副環。

```
探索層 (Subreddit /new + 關鍵字, 60 min)
    ↓
評分層 (硬規則 → Haiku 五軸 → 加權)
    ↓
候選排程層 (每日 09:00 Top 5 = 3 已爆 + 2 早期)
    ↓
推送層 (Telegram + inline button)
    ↓ ❤️ 收藏
追蹤層 (分級輪詢 15min/1h/6h)
    ↓ 四類後續事件：作者新貼 / 作者留言更新 / 高分回應 / crosspost
後續推送 + 問答層 (/ask <id> 重量 context 多輪對話)
```

## 技術棧

- Python 3.11 / `uv`
- PRAW（Reddit 官方 API wrapper）
- python-telegram-bot
- Anthropic SDK（Haiku 評分 / Opus 問答）
- APScheduler / FastAPI / SQLAlchemy / Alembic
- 預設 SQLite，可切 Postgres（`DATABASE_URL`）

## 快速開始

```bash
# 1. 依賴
uv venv
uv sync

# 2. 環境變數（複製 .env.example → .env 後填值）
cp .env.example .env

# 3. PRAW 連線測試
uv run python -c "import praw; r = praw.Reddit(client_id='...', client_secret='...', user_agent='reddit_tracker/0.1 by <reddit_username>'); print(r.read_only)"
```

申請 Reddit OAuth app（personal use script）：<https://www.reddit.com/prefs/apps>

## 專案文件

| 檔案 | 用途 |
|------|------|
| [`PROGRESS.md`](PROGRESS.md) | 跨 session 的單一狀態真相，里程碑 M1–M8 完成度 |
| [`SCHEDULE.md`](SCHEDULE.md) | 任務級里程碑清單 |
| [`reddit_tracker_proposal.md`](reddit_tracker_proposal.md) | 完整企劃書 v4 |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | AI agent 協作規範 |

## 狀態

剛 bootstrap，M1（Reddit API 可行性驗證）未啟動。詳見 [`PROGRESS.md`](PROGRESS.md)。
