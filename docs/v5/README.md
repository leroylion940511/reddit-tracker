# v5 AI Newsroom

v5 將 v4 的「Reddit 候選 → 單篇通知」轉為「Reddit 候選 → 多 agent 編採 → 個人化每日報紙」。

這些文件是 v5 的實作契約；開始任何 v5 程式變更前，先依序閱讀：

1. [產品定義](PRODUCT_BRIEF.md)
2. [Agent 契約](AGENT_CONTRACTS.md)
3. [架構與資料遷移](ARCHITECTURE.md)
4. [里程碑](ROADMAP.md)
5. [協作準則](WORKING_AGREEMENT.md)
6. [離線 Demo](DEMO.md)
7. [來源登錄表規格](SOURCE_REGISTRY.md)（v2.0 多來源綜合日報）
8. [多來源收集層規格](COLLECTION.md)
9. [事件聚合規格](CLUSTERING.md)

## 已確認的產品決策

- 試刊讀者只有專案擁有者；資料模型仍須支援未來多使用者。
- 來源為中英文 Reddit；所有成品為繁體中文，且保留原帖標題與連結。
- 每天 08:30 Asia/Taipei 發 Telegram 報紙。
- 主體採前一個日曆日（00:00–23:59 Asia/Taipei）候選，可插入當日早晨的重要快訊。
- 每期 8–10 則：6–8 則單帖短報、1–2 篇多帖專題。
- 網頁是偏好設定、歷史報紙與編輯室看板；Telegram 是主要閱讀介面。

## 現階段邊界

v5 已部署至 production SQLite，並在 2026-09-19 至 2026-09-25 完成七日試刊 gate：每天 08:30 實際發行 8 則、每則均有來源。日常運作維持 candidate discovery（90 分鐘）、05:30 編採與 08:30 Telegram 發行；控制台會保留試刊通過紀錄，並顯示近七日營運狀態。

日後若有 schema 變更，使用 `deploy/install_launchd.sh newsroom-deploy` 會建立 online backup、執行 Alembic upgrade 並只重載 newsroom；它不會重新啟用舊 v4 scheduler。Telegram callback receiver 已於 2026-09-25 依使用者明確授權啟用，Telegram 與網頁回饋都可正常使用。
