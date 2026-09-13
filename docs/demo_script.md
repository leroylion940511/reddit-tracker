# Reddit Tracker — Demo 講稿

對應 [`demo_slides.md`](demo_slides.md)，每張投影片配一段口白。
預計總長度 **10 ± 1 分鐘**（不含 5 分鐘 Live Demo）。
用斜線 `/` 表示可省略的句子，視時間刪減。

---

## Slide 1 — Cover
各位老師、同學好，我們這組的期末專題是 **Reddit Tracker — 素人爆文發現、追蹤與問答系統**。

---

## Slide 2 — 1.1 研究動機

其實我一開始是想做一個由一群ai agent所經營的公司，在學期初的時候這個想法還不像現在這樣已經蠻多人實現了。因為這其實是畢業專題（我想說可以共用，畢竟資工系的專題一定會用到資料庫），所以我和老師討論過後決定開一間ai新聞公司，一開始我是想參考史丹佛大學的ai小鎮，做一個2d的前端來讓我可以用上帝視角觀查我的公司，第一次demo的時候我是先用一個網頁前端做成像google一樣的搜索筐，使用者主動輸入想看的新聞主題後ai員工們就會開始做出一篇新聞，但是這其實就是一個很單純的用爬蟲抓google搜尋的前幾筆資料全部喂給大語言模型然後產出一篇文章而已。後來老師給的意見是不應該由使用者自己搜尋，應該是主動推送新聞給使用者，所以專案方向就轉成這樣。
我的出發點很單純——我們大家可能都有過這種經驗：滑社群（尤其是thrades）滑到一篇素人意外爆紅的貼文（像是爆料出軌、或是奇人異士等），可能不是一次性的故事，所以看完當下覺得「哇好精彩，想知道後續」，但程式也沒有提供相關工具讓你可以追蹤特定貼文的後續，你可能也不想追蹤他這個人（因為他可能發其他和這件事不相關的文章你沒興趣或其他原因不想追蹤），**所以你可能永遠錯過後續發展**。

我提出的核心需求是：**能不能用一條自動化流水線，把「素人爆文 → 後續事件 → 重量 context 問答(就是我希望可能傳連結給我這個工具，他能自己找到所有事件脈絡，包括:前後的相關貼文、熱門留言、相關知識等)」這條鏈整段打通？**

這條鏈拆開來就是四個子問題：探索（從哪裡挑）、評分（怎麼判斷會爆）、追蹤（怎麼偵測後續）、問答（累積到的資料能不能用 LLM 開放回答）。這四題就構成了我們整個系統的骨幹。

---

## Slide 3 — 1.2 研究目標

把命題拆成四個主目標：

**第一**，自動化探索 + 評分流水線。每天從 15 個 subreddit、5 中 10 英，加 20 個雙語 keyword 種子，自動產出 Top 5 候選。

**第二**，每日推送。我們做了一個 Telegram Bot，把候選用 inline button 推給使用者——三選一：❤️ 收藏、👎 不感興趣、🔕 靜音作者。

**第三**，長期追蹤 + 四類後續偵測。一旦收藏，貼文就進入追蹤池，系統會自動偵測作者新貼、作者留言、高分回應、被 crosspost 引用這四種後續事件。

**第四**，對話式問答。輸入 `/ask <id>` 就能對任何收藏的貼文開啟多輪問答，LLM 拿到的 context 包含原貼、時間軸快照、完整 comment tree、所有 related events——這就是我們講的「重量 context」。

次要目標有三個，主要是研究演算法評分跟人類收藏行為的相關性、評估 LLM 在大 context 下的回答品質、還有建立中英對照的爆文資料集。

---

## Slide 5 — 系統架構


### 1 探索層：Subreddit /new 為主 + 關鍵字補充

#### 主策略：Subreddit pool 輪詢

維護 12–20 個目標 subreddit，每 60 分鐘掃描每個 sub 的 `/new` 最近 50 篇。優先初始名單：

**繁中（4–6 個）**

| Subreddit | 偏向 |
|-----------|------|
| r/Taiwan | 在地時事、工作職場、人際 |
| r/HongKong | 在地時事、移民、社會議題 |
| r/translator | 求助型短文（多語混雜，需語言過濾） |
| r/ChineseLanguage | 中文相關討論 |
| r/Cantonese | 粵語使用者敘事 |
| r/China_irl | 海外華人敘事 |

**英文 storytelling（8–14 個）**

| Subreddit | 偏向 |
|-----------|------|
| r/TIFU | 自爆糗事 / 失誤敘事 |
| r/AmItheAsshole | 道德兩難敘事 |
| r/relationship_advice | 感情困境 |
| r/MaliciousCompliance | 反諷職場 / 制度 |
| r/ProRevenge / r/pettyrevenge | 報復敘事 |
| r/legaladvice | 法律困境（多有後續） |
| r/JUSTNOMIL / r/raisedbynarcissists | 家庭敘事 |
| r/entitledparents | 衝突敘事 |
| r/IDontWorkHereLady | 服務業敘事 |
| r/HFY / r/MaliciousCompliance | 高互動 narrative |

Subreddit 列表寫入 `subreddit_sources` 表，可動態啟用 / 停用、紀錄產出量與收藏轉換率。

#### 輔助策略：關鍵字跨 sub 搜尋

每 6 小時跑一次 Reddit search API（`subreddit=all`），用「事件感」關鍵字補抓主策略漏掉的 viral post。

| 類型 | 中文 keyword | 英文 keyword |
|------|--------------|--------------|
| 後續暗示 | 「更新」「後來」「結果是」 | update, follow up, year later |
| 求助共鳴 | 「該怎麼辦」「請問各位」 | what should I do, AITA |
| 事件性 | 「老闆」「主管」「分手」 | fired me, broke up, quit my job |
| 情緒爆發 | 「氣死」「崩潰」「真的不行」 | I can't believe, finally happened |

關鍵字種子池規模較 v3 縮減（20 個 vs v3 的 30 個），因為主軸已改為 subreddit。

#### 預估候選量

| 來源 | 每日量 |
|------|--------|
| Subreddit /new × 16 sub × 50 篇 × 24 次 | 19200（重疊去重後 ~4000） |
| Keyword search × 20 詞 × 4 次/天 × 20 篇 | 1600（重疊去重後 ~800） |
| **合計（去重後）** | **~4800 篇/日** |

略高於 v3，因為 Reddit API 不收費，可開大水龍頭。

### 2 評分層：三層篩選

#### 第一層 硬規則

| 規則 | v3 (Threads) | v4 (Reddit) |
|------|--------------|-------------|
| 互動速度 | likes/h > 30 | (ups + comments × 2) / age_hours > 5 |
| 作者粉絲 | follower < 10000 | account_karma < 10000 |
| 帳號年齡 | — | account_created > 30 天前（過濾水軍） |
| 語言 | 繁中 | 繁中 OR 英文（lang detect）|
| 長度 | 30–500 字 | 100–3000 字（Reddit 文長較長） |
| 業配 / 公告 | 黑名單字串 | 同 + 過濾 `stickied=True`、`distinguished=mod` |

預估通過率 8–12%。

#### 第二層 Haiku 語意判斷

完全沿用 v3 的五軸 prompt：`story_potential` / `emotional_pull` / `grassroots` / `novelty` / `authenticity` + `verdict ∈ {track, skip}`。

僅 prompt 微調：
- `grassroots` 評估改為「作者 karma 是否符合素人輪廓」（v3 是 follower count）
- 新增提示：「英文輸入時請以同樣標準評分，不因平台或語言而放寬」

預估通過率 30%。

#### 第三層 綜合分數

```
final_score = 0.4 × interaction_velocity_normalized
            + 0.3 × semantic_score          # (story + emotional) / 2
            + 0.2 × grassroots_score
            + 0.1 × novelty_score
```

每小時取 Top N（N=10）寫入候選池。

### 3 候選排程層：每日 Top 5 = 3 已爆 + 2 早期

完全沿用 v3 設計：

| 類型 | 數量 | 條件 |
|------|------|------|
| 已爆 | 3 | 互動速度排名前 3，且發文時間 ≥ 6 小時 |
| 早期 | 2 | 發文時間 < 3 小時，semantic_score 排名前 2 |

#### 即時破例推送

候選池中出現「發文 1 小時內互動速度 Top 1%（Reddit 換算 ups_per_hour > 100 + comments_per_hour > 30）且 Haiku verdict=track 且 semantic_score > 0.85」，立即推送。每日上限 2 則。

### 4 推送層：每日 09:00 + inline button

訊息格式（中英文 subreddit 通用）：

```
🔥 今日推薦 (3/5)

r/MaliciousCompliance · 3h ago · 1.2k ⬆️ · 340 💬
"Boss said 'never come back without approval', so I didn't"

@anon_user_123 | karma 850 | 帳號 8 個月
類型：職場敘事 | 情緒：反諷、暢快 | 分數：0.84

[Opus 摘要 80–120 字（中文）]
原 PO 描述新主管要求所有出差需事前簽核，但拒簽急件...

[ ❤️ 收藏 ]  [ 👎 不感興趣 ]  [ 🔕 靜音作者 ]
```

按鈕語意與指令清單沿用 v3：

| 指令 | 功能 |
|------|------|
| `/feed` | 重看最近 7 天推送過的清單 |
| `/saved` | 列出我收藏的事件 |
| `/timeline <id>` | 看單一事件時間軸 |
| `/ask <id>` | 進入問答模式 |
| `/exit` | 離開問答模式 |
| `/digest` | 立即拉今日彙整 |
| `/settings` | 推播時間 / 是否接收破例推送 / 偏好語言 |

### 5、6 收藏與追蹤層

使用者點 ❤️ 後，候選貼文升格進入 `tracked_posts`，啟動分級輪詢。

#### 分級輪詢

| 階段 | 頻率 | 抓取項目 |
|------|------|---------|
| 收藏後 0–24h | 每 15 分鐘 | 留言樹、作者新貼文 |
| 收藏後 1–7 天 | 每 1 小時 | 全項目 + crosspost |
| 收藏後 7–30 天 | 每 6 小時 | 全項目 |
| 30 天無新動態 | 自動歸檔 | — |

#### 後續事件四類（Reddit 對應）

| 類型 | Reddit 對應實作 | 備註 |
|------|----------------|------|
| `author_followup` | `reddit.redditor(name).submissions.new(limit=20)` 比對 | 跨 sub 也抓 |
| `author_reply` | `submission.comments.list()` 過濾 `comment.author == submission.author` | 含後續編輯（PRAW 提供 `edited` 欄位） |
| `hot_reply` | `submission.comments.replace_more()` 後依 `score` 排序 | 設閾值（score > 50 或 比第二名 top reply 高 30%） |
| `quote / crosspost` | `submission.duplicates()` | **Reddit 原生支援，v3 在 Threads 上無解** |

每類偵測到都寫入 `related_posts`，並由 Haiku 判斷「是否構成事件重大進展」。

### 7 後續推送

預設整合至每日彙整（追加在當日 5 篇推薦之後，標題改「📌 你收藏的事件有更新」）。
例外：Haiku 判定「重大進展」（例如當事人現身、結局揭曉）→ 即時推送。

### 8 問答層：對話模式

使用者輸入 `/ask <id>` 進入該事件的問答模式，後續所有訊息都被視為對該事件的提問，直到輸入 `/exit`。

#### Context 範圍（預設：重量）

| 區塊 | 內容 | 估計 token |
|------|------|-----------|
| 原貼文 | title + selftext + flair + subreddit context | ~800 |
| 系統摘要 | 最新 `EvolutionSummary`（事件主體、當前狀態、待解問題、預期後續） | ~600 |
| 完整留言樹 | 至此抓到所有留言（含 nested reply 結構，標註層級） | 8k–30k |
| 作者背景 | 作者近 30 篇 submission + karma 分布 + 帳號齡 | 2k–5k |
| 後續事件 | `related_posts` 全部（含 crosspost）| 1k–10k |

預估每次 `/ask` 開場 12k–45k input tokens，後續每輪追問 +500 output。Opus 4.7 cache 命中後實際支出可控。


保留輕量 / 中量模式作為旗標：`/ask <id> --light <問題>` 只給原文 + 摘要。

#### 對話狀態管理（沿用 v3）

- 每個使用者同時只能進入一個事件的問答模式
- `/exit` 或 5 分鐘無訊息自動結束
- 對話歷史寫入 `qa_sessions` 與 `qa_messages`

#### 問題類型（預期）

事件結論型 / 輿情整理型 / 人物背景型 / 跨貼文連結型（crosspost 是天然素材）/ 細節考據型。

---

## Slide 6 — 限制與未來工作

> 老實講目前還有三個限制：
>
> **第一是 OAuth 沒通過**——這直接導致 picker 在 Plan C 期間 already_hot 收藏率掉 38 個百分點。我們已經申請了，在等 Reddit 回。
>
> **第二是案例樣本不足**——只 1 unique tracked，所以報告 Ch7「案例分析」目前是樁，等 OAuth 通過 + 連續運轉 14 天後再展開三個生命週期。
>
> **第三是 scoring 漏寫 LLMRecord**——成本只記在 scoring_records.cost_usd，跨表對帳要 sum 兩處，這是已知技術債。
>
> 短期 backlog 是 M7.6 retune 跑 A/B 驗證、M7.8 QA 自評層、M5 偵測規則重評。中長期想擴展案例分析跟多 user 場景——in-memory session 換 Redis、owner 模型改成 user × candidate 多對一。

---

## Slide 18 — Live Demo（5 分鐘，視時間決定要不要跳）

> 接下來如果時間允許，我們做 5 分鐘的 live demo。
>
> Demo 路徑：
> 第一步跑 `scripts/m2_smoke.py` 把 15 sub + 20 keyword 載進去、跑一輪 discovery。
> 第二步看 Telegram，我們預錄了一份 5 篇 picks 的 screenshot（避免 demo 時 LLM API 卡）。
> 第三步在 Telegram 按 ❤️，看 DB 寫入 feedback、升格成 tracked。
> 第四步打 `/saved` 看收藏列表——可以看到 tier emoji、snapshot 數、related 數。
> 第五步打 `/timeline <id>` 看時間軸——快照變化跟四類事件。
> 第六步打 `/ask <id>` 進問答——問「這位作者後來怎麼了？」，看 LLM 拿到完整 context 怎麼答。
> 最後 `/exit` 結束 session。

---

## 📱 手機 Telegram Demo Cheatsheet（2026-06-25 下午）

> **場景**：助教只看你手機 Telegram，不用 Mac、不用投影 terminal。
> **狀態**：bot launchd job 已重啟（PID 19876, 2026-06-24 21:36 起），scheduler 維持暫停。
> **預計時長**：3–5 分鐘。

### 戰前 30 秒檢查（demo 開始前在手機做）

1. 打開 Telegram → 找 `@<你的 bot>` 對話
2. 打 `/start` — 應該即時回「歡迎使用 Reddit Tracker！…」（沒回 = bot 沒活，回桌機 `launchctl list | grep reddit` 看）
3. 打 `/saved` — 應該看到 9 篇收藏列表，**第 7 條** AITA newborn 標 `related=29（★ 9）`

### Demo 主流程（順序固定）

| # | 在手機打 | TA 會看到什麼 | 講什麼 |
|---|---|---|---|
| 1 | (往上 scroll) | 過往 daily push 訊息 — 🔥 已爆貼 / ⚡ 早期下注 兩種 header，下面三按鈕 ❤️ 👎 🔕 | 「這是系統每天 09:00 自動推送的 Top 5」 |
| 2 | `/saved` | 9 篇收藏列表，含 tier emoji（🔴 hot / 🟠 cooling）+ snapshot/related 數 + 每行末尾的 `/timeline N` 連結 | 「使用者按 ❤️ 後，候選升格成 tracked，這是分級輪詢 + 後續事件統計」 |
| 3 | `/timeline 3` | r/amitheasshole AITA newborn 的 28 天時間軸：5 個快照 + 29 條相關事件（原作回覆 + 高熱度留言，★ 標 milestone） | 「分級輪詢 15min/1h/6h 抓 snapshot；偵測層發現 OP 回覆、爆贊留言、crosspost、作者新貼」 |
| 4 | `/ask 3` | 「✅ 已進入 #3 的問答模式，system_tokens~2885…」 | 「QA 層拿到原貼 + snapshots + 29 related events 組重量 context」 |
| 5 | 直接打字：`這位作者最後決定要不要去幫姐姐顧姪子？社群留言主流立場為何？請用 3-4 句中文摘要。` | MiniMax 回 3–4 句中文摘要（實測 ~3s, $0.0005/次） | 「LLM 不靠記憶、純依 context 回答；月成本實測 $1.5 vs 企劃預估 $15–36」 |
| 6 | `/exit` | 「已離開問答模式」 | （可省略，5min idle sweep 也會自動關） |

### 三套備用問題（看 TA 反應換）

- 主推（事件結局型）：「這位作者最後決定要不要去幫姐姐顧姪子？社群留言主流立場為何？請用 3-4 句中文摘要。」
- 人物背景（容易展示 OP context）：「原 PO 跟她姐姐的關係如何？姐夫的工作狀況又是？」
- 留言觀點（凸顯 hot_reply 利用）：「最高分的反對留言講了什麼？最高分的支持留言又講了什麼？」

### 應變

| 情境 | 怎麼救 |
|---|---|
| `/saved` 沒反應 / 超過 5 秒 | bot 掛了。手機端跟 TA 說「網路有點不穩」，先跳到 slide 17 拖時間；私下開 Mac `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.leroy.reddit-tracker.bot.plist` 重起 |
| `/ask 3` 回「⚠️ 那篇已歸檔，無法提問」 | tracked 3 又被翻成 archived。`sqlite3 reddit_tracker.db "UPDATE tracked_posts SET status='active' WHERE id=3;"` 後重試 |
| `/ask 3` 等超過 10 秒 | MiniMax 慢，跟 TA 說「LLM 在思考」；如果 30 秒沒回，跳到 `/timeline 2` 用備胎（offmychest 26 related） |
| TA 想看「新推送」即時抵達 | 老實說：「scheduler 為了 demo 穩定暫停，每日推送是 09:00 cron 跑出來的」，scroll 看歷史 |

### Demo 結束後（明天晚上想做）

```bash
# 把 demo 時翻 active 的兩篇翻回 archived（可選；不翻也沒副作用）
sqlite3 reddit_tracker.db "UPDATE tracked_posts SET status='archived' WHERE id IN (2,3);"
# bot launchd job 要關（繼續跑也行，bot 本身很省）：
launchctl bootout gui/$(id -u)/com.leroy.reddit-tracker.bot
```

---

## 講者備忘 / 應變

**時間彈性策略**

| 剩餘時間 | 取捨 |
|---|---|
| **充裕（> 12 分鐘）** | 全講 + Live Demo 完整跑 |
| **正常（10 分鐘）** | Slide 13 技術棧縮短到 20 秒；Demo 跳到第 4–6 步 |
| **緊張（< 8 分鐘）** | 跳過 Slide 13 + Slide 17 主要貢獻；Demo 改放預錄影片 |

**可能的 Q&A 預演**

1. **「為什麼不直接申請 OAuth 就好？」** → 申請週期未知（已等 3 週），我們選擇先把命題用 Plan C 驗證能跑，OAuth 是 upgrade path 不是 prerequisite。
2. **「64% 收藏率怎麼算公平指標？」** → 樣本只有 14 筆是限制，所以我們強調 pre/post Plan-C 切分跟 push_type 細分，比較相對變化比絕對值有意義。
3. **「MiniMax 跟 Opus 差多少？」** → 還沒做 head-to-head 比較，目前只看成本跟整合工程。M7.8 的 LLM-as-judge 自評會跟 OAuth 一起做。
4. **「為什麼用 SQLite 不用 Postgres？」** → 個位數使用者規模 + 部署簡單（macOS launchd），WAL 模式並發夠用。schema 已預留 Postgres 切換（BigInt with_variant、JSON type 跨庫）。
5. **「為什麼 active tracked 後續命中 0%？」** → 樣本問題，3 篇平均追蹤期不到 5 天，達不到大部分 milestone 閾值；archived（追滿 30 天）的 80% 命中是更可靠的數字。
