# 規格入口：v2.0 綜合日報＋MAS 編輯室

**現行系統是 v2.0 綜合日報**：多來源收集 → 事件聚合 → 評分選題 → `DAILY_MODE=pipeline`（流水線）或 `mas`（六角色編輯室）→ 人工核可（mas）→ 08:35 Telegram 發行。LLM 走本機 Codex CLI（Gemini 只是備用 provider）。v4 與 v5 Reddit 早報的程式已從程式庫移除（最後保留於 commit `ff15181`），資料表與 Alembic migration 不動。目錄名 `docs/v5/` 沿用，不改名。

專案總覽與指令見 [根目錄 README](../../README.md)；目前狀態見 [`PROGRESS.md`](../../PROGRESS.md)。

開始程式變更前，先讀現行規格：

1. [來源登錄表規格](SOURCE_REGISTRY.md)
2. [多來源收集層規格](COLLECTION.md)
3. [事件聚合規格](CLUSTERING.md)
4. [綜合日報編採與發行規格](DAILY_EDITION.md)（含 MAS 流程、介面與 CLI）
5. [協作準則](WORKING_AGREEMENT.md)

產品方向見 [企劃書](../AI_NEWS_COMPANY_PROPOSAL.md)；老師的正式要求見 [執行手冊](../HANDBOOK_2026-10-28.md)，逐步實作與改編紀錄見 [HANDBOOK_ADAPTATION](../HANDBOOK_ADAPTATION.md)。

## 歷史文件（v5 Reddit 早報，程式已移除）

[產品定義](PRODUCT_BRIEF.md)、[Agent 契約](AGENT_CONTRACTS.md)、[架構與資料遷移](ARCHITECTURE.md)、[里程碑](ROADMAP.md)、[離線 Demo](DEMO.md)。v5 曾於 2026-09-19 至 2026-09-25 通過七日試刊 gate，之後每天 08:30 發行，2026-10-27 停刊。這些文件裡的 Gemini 撰稿、Reddit 候選、05:30／08:30 排程、`newsroom.contracts`、`newsroom.demo` 都已不存在；現行 MAS 角色見 DAILY_EDITION。

## 現階段邊界

- 線上只有兩個 LaunchAgent：`com.leroy.reddit-tracker.newsroom`（`reddit_tracker.newsroom.scheduler`：每 15 分鐘收集＋聚合、06:00 準備、08:35 發行）與 `com.leroy.reddit-tracker.rsshub`。
- Telegram 只用來發行，沒有常駐 bot、沒有指令或按鈕回饋。核可與 HOLD 用 CLI（`daily approve`／`daily hold`）或回放頁。
- schema 變更使用 `deploy/install_launchd.sh newsroom-deploy`（online backup → Alembic upgrade → 重載 scheduler）。
