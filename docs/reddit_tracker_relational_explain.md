# Relational Schema 講稿 — reddit_tracker

> 對照圖：`docs/reddit_tracker_relational.drawio`
> 目的：對著圖向助教口頭報告，照本文順序講即可。
> 圖的閱讀規則：**底線欄位 = PK（主鍵）**，**箭頭從 FK 指向被參照的 PK**。

---

## 0. 開場（30 秒）

> 「這張是 reddit_tracker 的關聯式 schema，總共 **12 張表**，分成四大群：
> **(1) 探索層**、**(2) 評分與推送層**、**(3) 收藏追蹤層**、**(4) LLM 與問答層**。
> 整個資料流是線性的：Reddit 上的貼文先進 `candidate_posts` → 經過 `scoring_records` 評分 → 上 `daily_pushes` 推給使用者 →
> 使用者按收藏後升格成 `tracked_posts` → 之後的時序變化、相關討論、QA 對話都掛在 `tracked_posts` 底下。」

四群對應的開發里程碑（順便提一下）：

| 群組 | 表 | 對應 milestone |
|------|----|----|
| 探索層 | `candidate_posts` / `subreddit_sources` / `keyword_seeds` | M2 |
| 評分推送層 | `scoring_records` / `daily_pushes` / `feedback` | M3 + M4 |
| 收藏追蹤層 | `tracked_posts` / `post_snapshots` / `related_posts` | M5 |
| LLM 與問答層 | `llm_records` / `qa_sessions` / `qa_messages` | M3 + M6 |

---

## 1. 探索層（圖上最上面三張表）

### 1.1 `candidate_posts`（候選貼文，全系統的核心事實表）

> 「這張是整個系統的中心，所有後面四張表的 FK 最終都指向這裡的 `id`。」

| 欄位 | 說明 |
|------|------|
| **id** (PK) | 內部代理鍵 |
| reddit_post_id | Reddit 自己的 submission id，**有 UNIQUE 索引**用來去重 |
| subreddit | 出處板塊（例如 `r/Taiwan`） |
| title / selftext / permalink | 標題、內文、原始連結 |
| author_username / author_karma / author_created_utc | 作者資訊，用於後續評分（新帳號、karma 太低會被扣分） |
| posted_at | 貼文在 Reddit 上發布的時間 |
| discovered_at | 我們**第一次抓到**這篇貼文的時間 |
| discovery_source | 來源來自 subreddit 還是 keyword，格式為 `subreddit:Taiwan` 或 `keyword:房價` |
| initial_score / initial_num_comments / upvote_ratio | 抓到那一刻的熱度快照（之後熱度變化會記在 post_snapshots） |
| lang | 語言判定（`zh-Hant` / `en` …），影響後續 prompt 與評分權重 |
| metadata (JSON) | 完整的 PRAW raw payload，當作備援 |

> 「**discovered_at 跟 posted_at 是兩件事**，前者是『我們發現它的時間』，後者是『它在 Reddit 上發出來的時間』，
> 兩者的差距會被當作『早期投注（early bet）』的指標。」

### 1.2 `subreddit_sources`（板塊種子表）

> 「這張記的是『我們在追哪些 subreddit』，相當於探索層的 config + 統計面板。」

關鍵欄位：

- `name` UNIQUE — 板塊名（例如 `Taiwan`、`China_irl`）
- `lang_hint` — 預期語言（zh / en / mixed）
- `enabled` — 開關，方便臨時關掉某個板塊
- `last_polled_at` — 上次輪詢時間，排程依據
- `total_candidates_yielded / total_promoted / total_collected` — 累積統計，用來衡量這個板塊「值不值得繼續追」

### 1.3 `keyword_seeds`（關鍵字種子表）

> 「跟 subreddit_sources 是對稱的，但探索的是『關鍵字搜尋』而不是板塊。」

欄位幾乎一樣，多了 `category`（分類，例如 `房地產`、`AI`）跟 `lang`。

> 「**這兩張表跟 candidate_posts 之間沒有 FK 直連**，是用 `discovery_source` 字串軟連結，
> 設計上故意鬆耦合，因為一篇貼文可能同時從『關鍵字』跟『板塊』兩條路被發現。」

---

## 2. 評分與推送層

### 2.1 `scoring_records`（評分歷史，FK1）

> 「**FK1：`scoring_records.candidate_post_id → candidate_posts.id`**。
> 一篇貼文會經過**多階段評分**，每一階段都寫一筆，所以 candidate : scoring 是 **1 : N**。」

| 欄位 | 說明 |
|------|------|
| stage | `rules` / `haiku` / `final` — 三階段評分 pipeline |
| passed | 該階段是否通過門檻 |
| score | 分數 |
| details (JSON) | 該階段的細節（例如哪個 rule 不過、LLM 的 raw output） |
| cost_usd | 該階段的 LLM 花費（rules 階段為 0） |

> 「設計重點：**我們不覆蓋舊評分**，每階段都留一筆，方便事後分析『為什麼這篇沒被推上來』。」

### 2.2 `daily_pushes`（每日推播，FK2）

> 「**FK2：`daily_pushes.candidate_post_id → candidate_posts.id`**。
> 評分通過的貼文每天被排進這張表，這是給使用者看的 daily digest。」

| 欄位 | 說明 |
|------|------|
| push_date | 哪一天的推播 |
| push_type | `already_hot`（已經很熱）/ `early_bet`（早期下注）/ `breaking`（突發）|
| rank | 那天的排名（通常每天 Top 5） |
| pushed_at | 實際推送時間 |

索引 `(push_date, rank)` 讓「給我今天 Top 5」這種查詢很快。

### 2.3 `feedback`（使用者反饋，FK3）

> 「**FK3：`feedback.candidate_post_id → candidate_posts.id`**。
> 使用者對推播的反應：`collect`（收藏，會觸發升格）/ `dislike`（不喜歡）/ `mute_author`（封鎖該作者）。」

`acted_at` 記錄時間，`user_id` 留 hook 給未來多使用者（目前是單機系統，固定值）。

---

## 3. 收藏追蹤層（這是系統最有特色的部分）

### 3.1 `tracked_posts`（被追蹤的貼文，FK4）

> 「**FK4：`tracked_posts.candidate_post_id → candidate_posts.id`**。
> 當 `feedback.action = 'collect'` 時，這篇貼文就會被**升格（promote）** 進 tracked_posts，
> 從『一次性候選』變成『長期追蹤對象』。」

| 欄位 | 說明 |
|------|------|
| promoted_at | 升格時間 |
| polling_tier | `hot` / `warm` / `cold` — **分級輪詢**，熱的常去看，冷的久久才去 |
| last_polled_at | 上次去 Reddit 看它的時間 |
| status | `active` / `paused` / `archived` |
| initial_summary | 升格當下 LLM 產的初版摘要，給使用者首屏看 |

> 「`polling_tier` 是設計重點：被追蹤的貼文有些瞬間爆紅、有些慢慢發酵，
> 我們不希望對冷門貼文也每 5 分鐘去 ping 一次 Reddit API，所以用分級輪詢來分配輪詢預算。」

### 3.2 `post_snapshots`（時序快照，FK5）

> 「**FK5：`post_snapshots.tracked_post_id → tracked_posts.id`**。
> 這張表是**時序資料**，每次輪詢都寫一筆，記錄該貼文的熱度演變。」

| 欄位 | 說明 |
|------|------|
| captured_at | 這筆快照的時間 |
| score / num_comments / upvote_ratio | 那一刻的熱度三件套 |
| new_comments (JSON) | **delta**：跟上一筆快照相比，新增了哪些留言 |

> 「之所以存 delta，是因為 Reddit 一篇貼文可能有上千則留言，
> 全量存太貴，存 delta 後續要拼回去也容易。」

### 3.3 `related_posts`（相關後續，FK6）

> 「**FK6：`related_posts.tracked_post_id → tracked_posts.id`**。
> 這張表記的是『追蹤貼文衍生出的相關內容』，包含四種：」

| relation_type | 意思 |
|---------------|------|
| `author_followup` | 原作者又發了新貼文 |
| `author_reply` | 原作者在這串底下回了留言 |
| `hot_reply` | 該串底下出現了很熱的回覆 |
| `crosspost` | 被別人轉貼到其他板塊 |

| 欄位 | 說明 |
|------|------|
| reddit_post_id | `t1_xxx` 是留言、`t3_xxx` 是貼文 |
| relevance_score | LLM 評估的相關度 |
| is_milestone | 是不是「里程碑」事件（例如熱度突破某閾值），是的話要推播 |
| content / posted_at / discovered_at / notified_at | 內容、時間、發現時間、通知時間 |

---

## 4. LLM 與問答層

### 4.1 `qa_sessions`（問答 session，FK7）

> 「**FK7：`qa_sessions.tracked_post_id → tracked_posts.id`**。
> 使用者可以對某篇追蹤中的貼文發起 `/ask` 對話，每次 `/ask` 開一個 session。」

欄位：`user_id`、`started_at`、`ended_at`、`state`（`active` / `closed` / `timed_out`）。

### 4.2 `qa_messages`（問答訊息，FK8）

> 「**FK8：`qa_messages.qa_session_id → qa_sessions.id`**。
> session 裡的多輪對話，每則訊息一筆。」

| 欄位 | 說明 |
|------|------|
| role | `user` / `assistant` |
| content | 訊息內容 |
| input_tokens / output_tokens / cost_usd | 該訊息的 token 用量與花費 |
| sent_at | 時間 |

> 「token 跟 cost 存在每則 message，是為了**精準歸因成本**：
> 知道每個 session、每個使用者、每則對話花了多少錢。」

### 4.3 `llm_records`（LLM 呼叫總帳，**沒有 FK**）

> 「這張是**全系統 LLM 呼叫的總帳**，所有對 Anthropic / MiniMax 的呼叫都會在這裡留一筆。
> 注意它**沒有硬 FK**，是用 `context_ref` 這個 JSON 欄位做『軟連結』。」

| 欄位 | 說明 |
|------|------|
| provider / model | `anthropic` / `minimax` + 具體模型名 |
| purpose | `scoring` / `summarization` / `qa` |
| input_tokens / output_tokens / cached_tokens | 用量 |
| cost_usd | 花費 |
| context_ref (JSON) | 多型 FK，例如 `{"type":"scoring", "id": 42}` 或 `{"type":"qa_message", "id": 87}` |

> 「為什麼不用真 FK？因為一筆 LLM 呼叫可能來自三個層（評分、摘要、QA），
> 用一張表三個 FK 欄位 + 三個 nullable，不如用 JSON 軟連結乾淨。
> 代價是『不能用 JOIN 強制完整性』，必須在 application 層自己維護。」

---

## 5. FK 箭頭一覽（指著圖照唸）

| 編號 | 從 | 到 | 基數 |
|------|----|----|------|
| FK1 | `scoring_records.candidate_post_id` | `candidate_posts.id` | N : 1 |
| FK2 | `daily_pushes.candidate_post_id` | `candidate_posts.id` | N : 1 |
| FK3 | `feedback.candidate_post_id` | `candidate_posts.id` | N : 1 |
| FK4 | `tracked_posts.candidate_post_id` | `candidate_posts.id` | 1 : 1（升格關係） |
| FK5 | `post_snapshots.tracked_post_id` | `tracked_posts.id` | N : 1 |
| FK6 | `related_posts.tracked_post_id` | `tracked_posts.id` | N : 1 |
| FK7 | `qa_sessions.tracked_post_id` | `tracked_posts.id` | N : 1 |
| FK8 | `qa_messages.qa_session_id` | `qa_sessions.id` | N : 1 |

> 「整張圖看起來像兩個『放射狀』結構：
> **上半部所有箭頭指向 `candidate_posts`**，**下半部所有箭頭指向 `tracked_posts`**，
> 兩個 hub 之間靠 FK4（升格）連起來。」

---

## 6. 設計上幾個值得提的決定（如果助教追問）

1. **BigInt PK + SQLite 的相容性**
   SQLite 不會對 BigInt 自動遞增，所以實作上用 `BigInteger().with_variant(Integer(), "sqlite")`，
   開發機跑 SQLite、上 production 換 Postgres 不用改 schema。

2. **JSON 欄位**
   直接用 SQLAlchemy `JSON` type — Postgres 自動變 JSONB、SQLite 自動變 TEXT，省一層自定義。

3. **時間欄位全部 timezone-aware**
   全用 `DateTime(timezone=True)`，存 UTC，避開時區地雷。

4. **subreddit_sources / keyword_seeds 用軟連結而非 FK**
   一篇貼文可能同時從多個 source 被發現，用 FK 反而綁死。

5. **llm_records 用 `context_ref` 多型軟連結**
   避免一張表掛三個 nullable FK 欄位。

6. **scoring_records 不覆蓋舊評分**
   每階段都留歷史，方便事後 debug「為什麼這篇沒上榜」。

7. **post_snapshots 存 delta 而非全量留言**
   控制儲存成本，後續要復原也容易。

8. **重要索引**

   | 表 | 索引 | 為什麼 |
   |----|------|--------|
   | `candidate_posts` | `(reddit_post_id)` UNIQUE | 去重 |
   | `candidate_posts` | `(discovered_at)` | 發現時間排序 |
   | `candidate_posts` | `(subreddit, posted_at)` | 板塊統計 |
   | `scoring_records` | `(candidate_post_id, stage)` | 取最新階段 verdict |
   | `daily_pushes` | `(push_date, rank)` | 每日 Top N 查詢 |
   | `tracked_posts` | `(polling_tier, last_polled_at)` | 分級輪詢調度 |
   | `related_posts` | `(tracked_post_id, relation_type)` | 後續事件查詢 |

---

## 7. 收尾（30 秒）

> 「總結一下：這張 schema 的設計哲學是
> **『以 candidate_posts 為事實核心、以 tracked_posts 為長期追蹤錨點』**，
> 評分、推播、反饋都圍著前者，時序、相關事件、對話都圍著後者，中間用『升格』連起來。
> 鬆耦合的部分（subreddit/keyword、llm_records）用 JSON 軟連結，
> 換取彈性與多型支援；硬連結的部分用 FK 確保資料完整性。
> 整體在『單機 SQLite 開發 / 雲端 Postgres production』之間是零修改可移植的。」
