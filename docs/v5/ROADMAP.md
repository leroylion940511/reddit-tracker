# v5 開發里程碑

每一項都要有程式、測試與可觀察的完成證據；未通過 gate 不進入下一項。

| 里程碑 | 交付內容 | 驗收 gate |
| --- | --- | --- |
| N0 Foundation | v5 規格、agent contracts、domain models、共同工作準則 | contracts tests + existing suite green；不觸碰 live service |
| N1 Reader + edition schema | ✅ Alembic migration、reader profile／feedback／edition ledger repository | migration up/down 在複本 DB 過；可建立一位讀者與空版次 |
| N2 Editorial planning | ✅ calendar window、偏好解讀、scout／assignment agent，能產生 8–10 則版面 plan | fixture candidates 產生多樣、可追溯的 plan；無來源項目被拒絕 |
| N3 Evidence + writing | ✅ evidence brief、繁中 template／Gemini batch writer、content safety gate | 每則稿件有 Reddit source、事實／觀點標記、敏感提示 tests |
| N4 Publish + feedback | 🟡 production `newsroom-deploy` 已於 2026-09-18 完成；Telegram newspaper、❤️／🚫／👀 callback、05:30 編採／08:30 scheduler 與失敗停損已完成。callback Bot receiver 仍待另行 enable | preview 不送訊息；送出後可回填 feedback 與 message ref |
| N5 Newsroom dashboard | ✅ FastAPI 控制台整合版次、文章來源、artifact timeline、讀者偏好與網頁 feedback | 可從 edition 點到每項可見 artifact，沒有 token／private prompt 洩漏 |
| N6 Seven-day pilot | 🟡 控制台已可逐日檢視出刊、來源完整與 ❤️ 正向回饋；尚待連續七日實機出報、每日品質回顧與調整 prompt／來源 | 7/7 editions、無未標示 source、讀者每日有「有意思」內容 |

## 近期工作順序

1. 完成 N0（本次）。
2. 先做 N1 schema 與 seed reader，**再**開始 agent prompt 或 Telegram formatter。
3. N2 必須優先修正候選新鮮度：按 edition window 優先處理，而不是沿用 v4 FIFO scoring backlog。
4. 以 dry-run 產出第一期，確認報紙品質後才接 Telegram 發送。
