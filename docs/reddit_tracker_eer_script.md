# reddit_tracker EER 圖 — 報告講解稿

> 對著 `docs/reddit_tracker_eer.drawio` 一邊指、一邊唸即可。
> 全圖共 **12 個 entity**（藍色方框）、**10 個 relationship**（綠色菱形），分成 **4 個語意分區**。
> 講解順序刻意跟著資料流走：**探索 → 評分推送 → 收藏追蹤 → LLM 問答**。

---

## 0. 開場：先講整張圖在做什麼

> 「老師，這張 EER 是 reddit_tracker 的資料模型。整個系統的資料流是：
> **每天從 Reddit 抓貼文 → 用 LLM 評分 → 推前 N 名給使用者 → 使用者收藏後做後續追蹤與問答**。
> 圖上分成四個語意分區，左上角是入口（Discovery），順時針依序是評分推送、QA、收藏追蹤。
> 顏色慣例：藍色方框是 entity（會對應到一張資料表），綠色菱形是 relationship，白色橢圓是 attribute，底線代表 PK。實線是有 FK 的硬連結，虛線是 soft link。」

---

## 1. 區塊一 │ 探索層 Discovery（左上角）

包含 3 個 entity：`SubredditSource`、`KeywordSeed`、`CandidatePost`，以及兩個 `YIELDS` 關係。

### 1-1 SubredditSource — 我們監控哪些 subreddit

- **PK**: `id`
- 代表性欄位：`name`（subreddit 名稱）、`enabled`（是否啟用輪詢）、`last_polled_at`（上次抓取時間）
- 講法：
  > 「這張表是 seed 名單，告訴排程器要去哪些 subreddit 撈貼文。`last_polled_at` 是為了做 incremental polling — 不要每次都從零撈。」

### 1-2 KeywordSeed — 我們關心哪些主題關鍵字

- **PK**: `id`
- 代表性欄位：`keyword`、`category`（分類，例如 LLM/政策/科技）、`lang`（語言）
- 講法：
  > 「另一條 discovery 路徑：除了固定 subreddit，也用關鍵字搜尋，可以跨 subreddit 抓到主題型貼文。`category` 是後面 scoring 也會用到的標籤。」

### 1-3 CandidatePost — 抓回來的候選池（核心 entity）

- **PK**: `id`，另有 `reddit_post_id`（Reddit 上的 unique ID，去重用）
- 其他欄位：`subreddit`、`title`、`posted_at`、`initial_score`、`upvote_ratio`、`lang`
- 講法：
  > 「**這是整個系統的中樞 entity**。所有從 Reddit 抓回來、還沒被評分或推送的貼文都先進這裡。
  > 注意 `reddit_post_id` — Reddit 自己有一個 t3_xxx 的 ID，我們用它做唯一性檢查，避免同一篇貼文被抓兩次。」

### 1-4 兩個 YIELDS 關係（N:M）

- `SubredditSource —N:M→ CandidatePost`：一個 subreddit 可以產出多篇 candidate；一篇 candidate 也可以同時屬於多個 source（例如同時被 subreddit 巡邏與關鍵字搜尋抓到）。
- `KeywordSeed —N:M→ CandidatePost`：同理。
- 講法：
  > 「這兩條都是 N:M，因為一篇貼文可能同時透過 subreddit 巡邏跟關鍵字搜尋兩條路被收進來，所以實作上會有一張中介表記錄『這篇 candidate 是被哪個 source / keyword 拉進來的』。」

---

## 2. 區塊二 │ 評分推送 Scoring · Push · Feedback（右上區）

包含 3 個 entity：`ScoringRecord`、`DailyPush`、`Feedback`，全部都掛在 `CandidatePost` 後面。

### 2-1 ScoringRecord — LLM 評分紀錄

- **PK**: `id`
- 代表性欄位：`stage`（哪一階段的分數，例如 rule / haiku / opus）、`score`、`cost_usd`
- 關係：**`CandidatePost 1 : N ScoringRecord`**（SCORED_BY）
- 講法：
  > 「一篇 candidate 可能被多階段評分 — 先用便宜的規則打底分、再用 haiku 細評，必要時才用更貴的模型。所以是 1:N。`cost_usd` 是我們監控成本用的。」

### 2-2 DailyPush — 每日推送名單

- **PK**: `id`
- 代表性欄位：`push_date`、`push_type`（每日 / 加碼）、`rank`（在當日推送中的名次）
- 關係：**`CandidatePost 1 : N DailyPush`**（PUSHED_AS）
- 講法：
  > 「同一篇貼文可能在不同日期都被推送（隔天如果分數還是高、或被加碼推），所以同一個 candidate 對多筆 DailyPush。`rank` 是當天前 N 名的排名。」

### 2-3 Feedback — 使用者回饋

- **PK**: `id`
- 代表性欄位：`user_id`、`action`（按讚 / 收藏 / 略過）、`acted_at`
- 關係：**`CandidatePost 1 : N Feedback`**（RECEIVES）
- 講法：
  > 「使用者收到推送之後的動作都進這張表，作為後續 ranking 模型再訓練的訊號。同樣 1:N，因為一篇貼文可以被很多使用者各自回饋。」

---

## 3. 區塊三 │ 收藏追蹤 Tracking（中下區）

包含 3 個 entity：`TrackedPost`、`PostSnapshot`、`RelatedPost`。
這一區的入口是 `CandidatePost —1:1→ TrackedPost`（PROMOTED_TO）。

### 3-1 PROMOTED_TO — 從候選晉升為追蹤對象（1:1）

- 講法：
  > 「使用者按下『收藏』之後，這篇 candidate 就會被『晉升』成 TrackedPost。為什麼要分兩張表？因為 candidate 量很大、生命週期短；tracked 是長期觀察的子集，欄位也不同（多了輪詢層級、狀態）。1:1 關係。」

### 3-2 TrackedPost — 長期追蹤的貼文

- **PK**: `id`
- 代表性欄位：`user_id`（哪位使用者收藏的）、`polling_tier`（輪詢頻率層級，例如 hot/warm/cold）、`status`（active / paused / archived）
- 講法：
  > 「`polling_tier` 是成本控制的關鍵 — 剛收藏的高互動貼文每小時抓，幾天後降到一天一次，最後封存。`status` 對應目前的觀察生命週期。」

### 3-3 PostSnapshot — 隨時間變化的快照（1:N）

- **PK**: `id`
- 代表性欄位：`captured_at`、`score`、`num_comments`
- 關係：**`TrackedPost 1 : N PostSnapshot`**（HAS_SNAPSHOT）
- 講法：
  > 「每次輪詢都產生一筆 snapshot，記錄當下的分數和留言數。這樣就能畫出貼文熱度隨時間的曲線。」

### 3-4 RelatedPost — 相關貼文 / 里程碑事件（1:N）

- **PK**: `id`
- 代表性欄位：`relation_type`（同主題 / 後續討論 / 反方意見）、`relevance_score`、`is_milestone`
- 關係：**`TrackedPost 1 : N RelatedPost`**（HAS_RELATED）
- 講法：
  > 「當追蹤的貼文出現重要關聯事件 — 比如同主題的另一篇爆紅、或事件後續發展 — 就紀錄一筆 RelatedPost。`is_milestone` 標示是不是值得通知使用者的『里程碑』。」

---

## 4. 區塊四 │ LLM 與問答 LLM · QA（右下區）

包含 3 個 entity：`QASession`、`QAMessage`、`LLMRecord`。

### 4-1 QASession — 使用者針對某篇 TrackedPost 開啟的問答 session

- **PK**: `id`
- 代表性欄位：`user_id`、`started_at`、`state`（active / closed）
- 關係：**`TrackedPost 1 : N QASession`**（HAS_QA）
- 講法：
  > 「使用者可以對任何收藏的貼文開啟 QA session，問模型『這篇在討論什麼』、『有什麼後續』。同一篇 tracked post 可以有多個 session（不同時間或不同問題）。」

### 4-2 QAMessage — session 內的訊息（1:N）

- **PK**: `id`
- 代表性欄位：`role`（user / assistant / system）、`content`、`sent_at`
- 關係：**`QASession 1 : N QAMessage`**（CONTAINS）
- 講法：
  > 「就是標準的 chat schema — role + content + 時間戳。重播一個 session 就把它的 messages 依時間排出來。」

### 4-3 LLMRecord — 所有 LLM 呼叫的稽核紀錄

- **PK**: `id`
- 代表性欄位：`provider`（anthropic / minimax）、`model`、`purpose`（scoring / qa / summary）、`called_at`、`cost_usd`
- 關係：**虛線 soft link → TrackedPost**（`context_ref`）
- 講法：
  > 「這張表是『所有 LLM 呼叫的總帳本』，無論是 scoring、QA 還是摘要都會留一筆 — 用來算每天的 token 成本、做模型比較。
  > 為什麼跟 TrackedPost 是**虛線**？因為 LLMRecord 不一定每筆都對應到一個固定 entity（例如 scoring 階段時還只是 candidate），所以用 `context_ref` 字串去軟連結，不下 FK。這在實務上是常見取捨：強型別 vs. 寫入彈性。」

---

## 5. 設計重點總結（最後 30 秒收尾）

報告完畢之前，挑 3 個設計決策強調一下，讓老師看到「不是隨便畫的」：

1. **CandidatePost 與 TrackedPost 分開**
   - 不同生命週期 / 不同欄位 / 不同 polling 成本，硬合併會讓 candidate 表暴漲。
   - 1:1 PROMOTED_TO 關係維持可追溯性。

2. **ScoringRecord / LLMRecord 分兩層**
   - ScoringRecord 是『業務語意』的分數（給 ranking 用）。
   - LLMRecord 是『系統稽核』的呼叫紀錄（給成本與 debug 用）。
   - 一個關心「為什麼這篇被推」，一個關心「今天花了多少錢」。

3. **soft link（虛線）的取捨**
   - LLMRecord ⇢ TrackedPost 用字串而不是 FK，是因為呼叫情境太雜（candidate / tracked / 系統內部），FK 反而會綁死。
   - 代價是 referential integrity 要靠應用層維護。

> 「以上是整張圖的設計理由。完整欄位定義在 `reddit_tracker/models.py`，這張 EER 只挑代表性 attribute 呈現以保持可讀性。謝謝老師。」

---

## 附：講解時的指圖路線（建議手指/雷射筆順序）

1. 左上 SubredditSource → KeywordSeed
2. 兩條 YIELDS 菱形 → 落到中間的 CandidatePost
3. 從 CandidatePost 往右上拉三條：SCORED_BY、PUSHED_AS、RECEIVES
4. 從 CandidatePost 往下一條 PROMOTED_TO → TrackedPost
5. 從 TrackedPost 往左下：HAS_SNAPSHOT、HAS_RELATED
6. 從 TrackedPost 往右下：HAS_QA → QASession → CONTAINS → QAMessage
7. 最後指右下角 LLMRecord，沿虛線回到 TrackedPost，講 soft link 取捨
8. 收尾：指圖例 Legend 區，說明顏色 / 線型約定
