# v5 AI Newsroom

v5 將 v4 的「Reddit 候選 → 單篇通知」轉為「Reddit 候選 → 多 agent 編採 → 個人化每日報紙」。

這些文件是 v5 的實作契約；開始任何 v5 程式變更前，先依序閱讀：

1. [產品定義](PRODUCT_BRIEF.md)
2. [Agent 契約](AGENT_CONTRACTS.md)
3. [架構與資料遷移](ARCHITECTURE.md)
4. [里程碑](ROADMAP.md)
5. [協作準則](WORKING_AGREEMENT.md)

## 已確認的產品決策

- 試刊讀者只有專案擁有者；資料模型仍須支援未來多使用者。
- 來源為中英文 Reddit；所有成品為繁體中文，且保留原帖標題與連結。
- 每天 08:30 Asia/Taipei 發 Telegram 報紙。
- 主體採前一個日曆日（00:00–23:59 Asia/Taipei）候選，可插入當日早晨的重要快訊。
- 每期 8–10 則：6–8 則單帖短報、1–2 篇多帖專題。
- 網頁是偏好設定、歷史報紙與編輯室看板；Telegram 是主要閱讀介面。

## 現階段邊界

本次 foundation 只建立規格、可驗證的 domain contract、工作流程與開發分支；不會修改正在執行的 v4 scheduler、Telegram bot 或 production SQLite schema。資料庫 migration 前必須先依 `ARCHITECTURE.md` 的切換程序停服與備份。
