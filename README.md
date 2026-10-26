# Reddit Tracker — AI 綜合日報

多來源中英文新聞 → 事件聚合 → Gemini 編採 → 繁體中文綜合日報，每天 08:35（Asia/Taipei）以 Telegram 發行（文字精選＋完整 HTML 報紙）。

> 2026-10-27 起只保留 v2.0 綜合日報。v4（Reddit 探索／評分／收藏追蹤／問答 bot）與 v5 Reddit 早報的程式已移除，舊程式碼留在 git 歷史（`ff15181` 之前）；資料表與 migration 保留不動。

## 核心架構

```
來源登錄表（RSS／本機 RSSHub，seeds/news_sources.yaml）
    ↓ 每 15 分鐘 tick，各來源依 interval 收集 → source_items
事件聚合（TF-IDF＋餘弦相似度）→ story_clusters
    ↓ 06:00
程式評分與各版選題 → Gemini 編輯會議／撰稿／數字核對（失敗走模板稿）
    ↓ 08:35
Telegram 發行 ＋ site/daily/<date>.html
```

| 套件 | 職責 |
|------|------|
| `reddit_tracker/collection/` | 收集、正規化、去重、事件聚合、來源健康報表 |
| `reddit_tracker/daily/` | 評分選題、證據、撰稿、渲染、發行 |
| `reddit_tracker/llm/gemini.py` | Gemini REST client＋跨 process 額度保護 |
| `reddit_tracker/newsroom/scheduler.py` | launchd 常駐 scheduler（收集＋日報） |
| `reddit_tracker/newsroom/deploy.py` | 部署前 SQLite online backup |
| `reddit_tracker/web.py` | 本機日報檢視器（127.0.0.1:8765） |

## 快速開始

```bash
uv sync --all-groups
cp .env.example .env          # 填 GEMINI_API_KEY、TELEGRAM_*、RSSHUB_ACCESS_KEY
uv run alembic upgrade head
uv run python -m pytest -q
```

常用指令：

```bash
uv run python -m reddit_tracker.collection run [--only id1,id2] [--force]
uv run python -m reddit_tracker.collection report --days 1
uv run python -m reddit_tracker.collection clusters --top 30
uv run python -m reddit_tracker.daily prepare      # 只編不發
uv run python -m reddit_tracker.web                # 看日報
PYTHONPATH=. uv run python scripts/probe_news_sources.py --only id1,id2
```

## 部署（launchd）

```bash
deploy/install_launchd.sh newsroom-deploy   # 備份 → migration → 重載 scheduler
deploy/install_launchd.sh newsroom-reload   # 只重載 scheduler
deploy/install_launchd.sh rsshub-install    # 本機 RSSHub（只綁 127.0.0.1:1200）
deploy/install_launchd.sh status
```

scheduler 每次 tick 重新讀登錄表，新增或停用來源不需重載。

## 專案文件

| 檔案 | 用途 |
|------|------|
| [`PROGRESS.md`](PROGRESS.md) | 跨 session 單一狀態真相 |
| [`docs/AI_NEWS_COMPANY_PROPOSAL.md`](docs/AI_NEWS_COMPANY_PROPOSAL.md) | v2.0 企劃書 |
| [`docs/v5/README.md`](docs/v5/README.md) | 規格入口（來源登錄表、收集、聚合、日報） |
| [`docs/sources_probe_2026-10-26.md`](docs/sources_probe_2026-10-26.md) | 來源實測結果 |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | AI agent 協作規範 |

`SCHEDULE.md`、`reddit_tracker_proposal*.md`、`docs/m*_*.md`、`docs/v4_schema.md`、`docs/report.md` 是 v4 時期的歷史文件，對應的程式已移除。
