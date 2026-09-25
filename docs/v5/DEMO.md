# AI Newsroom 離線 Demo

在專案根目錄執行：

```bash
uv run python -m reddit_tracker.newsroom.demo --open
```

它會建立新的 `/tmp/reddit-newsroom-demo-*.html` 與相鄰的 SQLite 檔，然後開啟 HTML。終端機同時會印出未發送的 Telegram preview。

## Demo 展示什麼

1. 讀者偏好 → 前一個台灣日曆日的候選池。
2. 學習、讀者檔案、採訪、選題、脈絡查核、撰稿、總編輯共七個可見 agent artifact。
3. 6 則短報、2 篇多來源專題；每篇含繁中 headline、原帖標題與可點的 Reddit source。
4. Telegram 版面 preview 與 ❤️／🚫／👀 回饋設計。

## 安全邊界

- 使用 10 則代表性 demo source，不讀目前 `reddit_tracker.db`。
- 不呼叫 Reddit、Gemini、ChatGPT、Telegram，也不啟動／停止 launchd service。
- demo writer 固定使用 deterministic template fallback；production 路徑另有 Gemini batch writer 與 source-transparent fallback。Demo 本身仍不會發 Telegram。

## 目前與下一步

這是可展示編輯室產品體驗的 demo，不是 production 資料的替代品。Gemini adapter、Telegram callback／08:30 scheduler 與本機 dashboard 已完成程式整合，且 production 已於 2026-09-18 安全部署；目前以七日試刊檢驗內容品質與穩定性。Telegram callback receiver 仍需另行啟用。
