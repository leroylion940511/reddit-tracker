# 編輯室 Agent 契約

每個 agent 都必須輸入可追溯資料、輸出結構化 artifact，並記錄簡短的可讀決策摘要。`reddit_tracker.newsroom.contracts` 是程式層的共同模型。

| Stage | Agent | 輸入 | 可見產出 | 不可做的事 |
| --- | --- | --- | --- | --- |
| `reader_profile` | 讀者檔案 agent | 偏好、訂閱、❤️／🚫／👀 回饋 | `ReaderBrief`：今日優先／排除／理由 | 臆測敏感身份或將偏好視為永久 |
| `scout` | 採訪 agent | 日曆候選池、ReaderBrief | `StoryPitch` 清單：beat、來源、推薦原因 | 無來源選題或重寫原帖內容 |
| `assignment` | 選題主編 | pitches、版面配額 | `EditionPlan`、採用／未採用摘要 | 只看排名，不處理多樣性與重複 |
| `verification` | 脈絡查核 agent | 入選來源、原始文字 | `EvidenceBrief`：claim、分類、可信度、待確認事項 | 宣稱匿名貼文已被外部證實 |
| `writing` | 撰稿 agent | plan、evidence、source refs | `StoryDraft`：繁中稿、原標題／連結、提醒 | 省略來源、杜撰引用、扭曲不確定性 |
| `chief_editing` | 總編輯 agent | drafts、版面規格 | `Edition` 與發布摘要 | 更改來源事實、隱藏風險標記 |
| `learning` | 學習 agent | 回饋、發行結果 | 下一期 profile adjustment | 不依單次 feedback 做劇烈偏好漂移 |

N2 的讀者檔案、採訪與選題主編先使用 deterministic baseline，驗證時間窗、偏好、來源與版面多樣性；N3 起才用 LLM 產生查核與繁中稿件。

## Artifact 可見性

網頁編輯室顯示 artifact 的 `summary`、`source_refs`、`reason_codes`、`confidence`、`warnings` 與時間；不顯示模型的 private reasoning 或未經整理的 prompt chain。

## 成功與失敗語意

- `succeeded`：產出通過該 stage 的結構與來源驗證。
- `needs_review`：有可交付產出，但包含可信度、敏感內容、來源不足或多樣性風險。
- `failed`：沒有可靠 artifact；後續 stage 必須跳過或走明確 fallback，不能把錯誤當成空白成功。

任何 agent 失敗都要保留 run record，讓編輯室能回答「今天為什麼少一篇」而不是默默降級。
