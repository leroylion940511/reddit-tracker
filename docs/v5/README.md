# v5 AI Newsroom → v2.0 綜合日報

**2026-10-27 起只剩 v2.0 綜合日報在運作。** v4 與 v5 Reddit 早報的程式已從程式庫移除（最後保留於 commit `ff15181`），資料表與 Alembic migration 不動。

開始程式變更前，先讀現行規格：

1. [來源登錄表規格](SOURCE_REGISTRY.md)
2. [多來源收集層規格](COLLECTION.md)
3. [事件聚合規格](CLUSTERING.md)
4. [綜合日報編採與發行規格](DAILY_EDITION.md)
5. [協作準則](WORKING_AGREEMENT.md)

產品方向見 [企劃書](../AI_NEWS_COMPANY_PROPOSAL.md)。

## 歷史文件（v5 Reddit 早報，程式已移除）

[產品定義](PRODUCT_BRIEF.md)、[Agent 契約](AGENT_CONTRACTS.md)、[架構與資料遷移](ARCHITECTURE.md)、[里程碑](ROADMAP.md)、[離線 Demo](DEMO.md)。v5 曾於 2026-09-19 至 2026-09-25 通過七日試刊 gate，之後每天 08:30 發行，2026-10-27 停刊。

## 現階段邊界

- 線上只有兩個 LaunchAgent：`com.leroy.reddit-tracker.newsroom`（`reddit_tracker.newsroom.scheduler`：每 15 分鐘收集＋聚合、06:00 準備、08:35 發行）與 `com.leroy.reddit-tracker.rsshub`。
- Telegram 只用來發行，沒有常駐 bot、沒有指令或按鈕回饋。
- schema 變更使用 `deploy/install_launchd.sh newsroom-deploy`（online backup → Alembic upgrade → 重載 scheduler）。
