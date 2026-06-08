# Reddit 素人爆文發現、追蹤與問答系統 — 期末報告

> **撰寫狀態（2026-06-08）**：Ch1–5 + Ch8 初稿（從 [reddit_tracker_proposal.md](../reddit_tracker_proposal.md) 改寫精簡 + 補 v4 實際採用差異）；Ch6 灌 M7 baseline + lang_breakdown + cost 對帳實測；Ch7 待 OAuth 通過後累積 ≥ 3 個完整生命週期案例再展開。
>
> 體例：聚焦「實際做了什麼 / 得到什麼數據 / 哪些是 v4 新發現」，與企劃書互補不重複。

---

## Ch1 — 研究動機與背景

### 1.1 命題

社群平台每天都有素人貼文意外爆紅。讀者當下被吸引、留言追問「後來呢？」，但這類貼文不在追蹤清單內，極容易錯過後續發展。本研究希望建立一套**自動化探索 + 評分 + 收藏追蹤 + 對話式問答**的流水線，把「素人爆文 → 後續事件 → 重量 context 問答」這條鏈打通。

### 1.2 從 Threads 轉到 Reddit（v3 → v4 pivot）

前身 Threads Tracker v1–v3 進展到 M3 主幹完成後，重新評估發現兩個結構性問題：

1. **資料取得成本過高**：Threads 公開搜尋從 2025 年底起限制 cookie 認證，必須透過第三方 scraper（Apify），實測月成本 $246，且仍要承擔 actor 維護中斷、欄位變動的風險。
2. **回貼追蹤天然劣勢**：Threads 留言是 flat 結構，「四類後續事件」中的引用討論難以聚合，每追一篇都要重複耗 scraper 配額。

Reddit 在這兩點上是天然替代：官方 API 免費（OAuth 100 QPM）、留言原生樹狀、subreddit 是天然主題容器、`submission.duplicates()` 一行拿 crosspost。研究命題（探索 → 推送 → 收藏追蹤 → 問答）完全沿用 v3，僅替換資料層。

### 1.3 「no-reddit-api」分支的二次 pivot

開發過程中（2026-05-29）Reddit 全面擋住 anonymous `.json` endpoint。為避免被 OAuth 申請審核時間卡住（v4 命題本身不依賴 OAuth），切到 **Plan C：RSS feed 主導 + public JSON fallback** 策略。實測月成本 **$1.5**（vs 企劃預估 $15–36，便宜 10×）。OAuth 申請仍在進行中，獲准後可一行切回 PRAW。

---

## Ch2 — 研究目標

### 2.1 主要目標（沿用 v3）

1. 建立**自動化探索 + 評分流水線**：每日從 15 個 subreddit（5 中 + 10 英）+ 20 個雙語 keyword 種子產出 Top 5 候選
2. 透過 **Telegram Bot 每日定時推送**：使用者以 inline button 三選一（❤️ 收藏 / 👎 不感興趣 / 🔕 靜音作者）
3. 對收藏的貼文進入**長期追蹤池**，自動偵測四類後續事件並推播：作者新貼 / 作者留言 / 高分回應 / crosspost
4. 提供 `/ask <id>` **對話式問答模式**，重量 context（原貼 + snapshots + 完整 comment tree + related events）多輪 LLM 對話

### 2.2 次要目標

1. 探討「演算法判斷貼文價值」與「使用者收藏行為」相關性
2. 評估在重量級 context（12k–45k tokens）下 LLM 對素人事件的問答品質
3. 建立中英對照的素人爆文資料集（去識別化）

### 2.3 範圍限定

- **語言**：中文（r/taiwan / r/hongkong / r/china_irl / r/taipei / r/chineselanguage）+ 英文 storytelling sub（r/tifu / r/amitheasshole / r/offmychest / r/relationship_advice / r/legaladvice / r/bestofredditorupdates / r/maliciouscompliance / r/updateme / r/confession）+ 對照組 r/askreddit
- **使用者**：個位數，共用同一份每日推送
- **平台**：純 Reddit；不混 X / Threads / Dcard

---

## Ch3 — 系統架構

### 3.1 雙環設計

```
[每日推送主環]                                  [收藏追蹤副環]

① 探索層 (Subreddit /new + Keyword fan-out)     ⑤ 收藏池 (使用者 ❤️ 升格)
   ↓ 90 min / 12 h                                 ↓
② 評分層 (Rules → Haiku 五軸 → 加權)            ⑥ 追蹤層 (分級輪詢 15/60/360 min)
   ↓ 30 min                                       ↓ 每 60 min 偵測 4 類後續
③ 候選排程層 (每日 09:00 Top 5；breaking 即時)  ⑦ 後續推送 (milestone 即時 / digest 隨日推)
   ↓                                              ↑
④ 推送層 (Telegram + inline button) ─❤️ 收藏───→ ⑧ 問答層 (/ask <id> 重量 context 多輪)
```

實際運轉細節見 [PROGRESS.md](../PROGRESS.md)。Scheduler 共 8 個 APScheduler job（subreddit / keyword / scoring / polling / detection / daily_push / breaking_check / milestone_check / qa_idle_sweep）。

### 3.2 v4 vs v3 架構差異

| 層 | v3 (Threads) | v4 (Reddit) |
|-----|------------|--------------|
| 資料源 | Apify scraper（$246/mo） | RSS + public JSON（$1.5/mo） |
| 探索主軸 | 關鍵字搜尋 | Subreddit /new + 關鍵字補充 |
| 留言結構 | flat | 樹狀（comment tree） |
| 引用追蹤 | 額外搜尋 | `submission.duplicates()` 直接拿 |
| 問答 context | 8–35k tokens | 12–45k tokens（含完整樹） |

### 3.3 Plan C 的退化處理

RSS 拿不到 `score / num_comments / upvote_ratio / author karma`：

- **scoring**：Haiku 五軸中只有 `velocity` 與 `grassroots` 受影響 — 退化為「無法計算」處理，combine_final 跳過 velocity 軸（M3 設計就允許部分軸缺失）
- **picker**：`pick_daily_top5` 在「已爆桶」需要 velocity 排序，velocity=None 時主桶會空。為此加 **Plan C fallback**：當主桶結果空且 pool 中 velocity=None 比例 > 90%，退化為 final_score top 5 全標 early_bet。實測 6/9 起恢復穩定 5 篇/日推送

---

## Ch4 — 核心功能（M2–M6 實作摘要）

### 4.1 探索層（M2）

- `services/discovery.py::discover_from_subreddits` 對 15 個 enabled sub 每 90 min 掃 `/new`，每 sub 最多 30 篇
- `discover_from_keywords` fan-out 模式：對每個 lang-compatible enabled sub 各做 `restrict_sr=on` 搜尋（Reddit `/search.json` all-reddit 被擋）。每 12 h 跑一輪
- 寫入 `candidate_posts`，`reddit_post_id` UNIQUE 防重複；`subreddit` 欄位 normalize 為 lowercase（M7 retune 後）

### 4.2 評分層（M3）

三段式：

1. **硬規則** `apply_hard_rules`：velocity / karma / 帳號齡 / 文字長度 / 語言 / 黑名單 + stickied + mod；karma/帳齡缺失時放行（Plan C 容忍）
2. **Haiku 五軸**：story_potential / emotional_pull / grassroots / novelty / authenticity + verdict + reason，strict JSON。M7.6 retune 後 prompt 涵蓋議題型 story potential + 0/0 互動 disclaimer
3. **加權合併** `combine_final`：`0.4·v + 0.3·s + 0.2·g + 0.1·n`，velocity 用 `v / (v+10)` 正規化

人工標記對比：30 篇隨機抽 accuracy **0.733**（門檻 0.60 過）。詳見 [m3_haiku_baseline.md](m3_haiku_baseline.md)。

### 4.3 推送層（M4）

- `pick_daily_top5`：3 已爆（age ≥ 6h, velocity rank top）+ 2 早期（age < 3h, semantic rank top）；中間灰帶刻意落空
- `check_breaking`：age < 1h + velocity top 1% + verdict=track + semantic > 0.85，每日上限 2
- Bot：Telegram + inline button（❤️/👎/🔕），callback 走 `asyncio.to_thread` 橋接 sync DB。冪等寫 feedback

### 4.4 追蹤層（M5）

- 升格：feedback.action='collect' → TrackedPost(tier='hot', status='active') + subreddit_sources 統計
- **分級輪詢**：hot=15 min / cooling=1 h / archive=6 h；> 30 d archived 終止
- **四類偵測**：
  - `author_followup`：作者新貼 title 二元組 Jaccard + 同 sub 加成
  - `author_reply`：`is_submitter=True` 留言
  - `hot_reply`：score ≥ 50 **或** ≥ 1.3 × 第二名
  - `crosspost`：`submission.duplicates()`
- milestone heuristic 閾值（followup ≥ 0.7 / author_reply ≥ 20 / hot_reply ≥ 200 / crosspost ≥ 100），milestone 即時推送，非 milestone 進 daily digest
- 對應 `/saved` / `/timeline <id>` bot 指令

### 4.5 問答層（M6）

- `/ask <id>` 進入 session（每 user 同時 1 個 active）；in-memory state + threading.Lock
- **重量 system prompt**：ORIGINAL POST + SNAPSHOTS（最舊→最新）+ RELATED EVENTS（按 relation_type 分組）+ COMMENT TREE（縮排，[OP] 標籤）。token budget 18k，超出 trim 留言到 top-60 by score
- 自由文字 MessageHandler 接後續輪；`/exit` 或 5 min idle sweep → state='ended_idle'
- 每輪寫 user/assistant QAMessage + LLMRecord（purpose='qa', context_ref dict 帶 qa_session_id / tracked_post_id / turn）
- chat client：原企劃 Opus → 改 MiniMax（共用 scoring endpoint，省 SDK 依賴；M7 對帳監控）

---

## Ch5 — 資料模型（DB Schema）

12 張表，完整 ER 圖見 [v4_schema.md](v4_schema.md)。核心：

| 表 | 用途 | M5/M6 後新增 |
|----|------|---|
| `candidate_posts` | 探索層產出的候選池 | subreddit lowercase normalize（M7） |
| `subreddit_sources` / `keyword_seeds` | 探索種子 + 統計回寫 | |
| `scoring_records` | 三段式評分留痕（rules / haiku / final 各一筆） | |
| `daily_pushes` | 推送記錄 + 防重複（UNIQUE on (push_date, candidate_post_id)） | push_type 分組 |
| `feedback` | 使用者按鈕回寫 | |
| `tracked_posts` | 升格池，分級輪詢狀態機 | polling_tier / status |
| `post_snapshots` | tracked 的時間軸快照（score / num_comments / upvote_ratio） | |
| `related_posts` | 四類後續事件 | `notified_at` + uq_related_post_triple（M5 migration） |
| `qa_sessions` / `qa_messages` | 問答狀態 + 對話 log | M6 新增 |
| `llm_records` | LLM 用量對帳（input/output tokens, cost_usd, context_ref dict） | |

Migrations: `alembic upgrade head` 從 0 → 2 個 revision（initial 12 表 + M5 related_posts 補欄位）。

---

## Ch6 — 評估結果（M7）

> **資料區間**：2026-05-22 (M2 上線) – 2026-06-08
> **累積樣本**：17,743 candidate / 7,138 rules pass / 5,696 haiku track / 9 tracked / 1 collected
> **重要警語**：所有評估都基於「無 user feedback 訓練」的冷啟動狀態。OAuth 通過 + 累積 ≥ 50 dislike 樣本後需 iterate。

### 6.1 漏斗總覽（[eval_lang_breakdown.py](../scripts/eval_lang_breakdown.py)）

```
discovered 17,743
  → rules pass 7,138 (40.2%)
  → haiku track 5,696 (79.8% of rules)
  → final pass 5,696 (100% of haiku — 因 final_score 門檻已被 Haiku verdict cover)
  → pushed 20 (0.4% of final — picker 樣本限制：每日 5 篇 × ~17 天 + Plan C 期間多日 0 推)
  → collected 10 (50.0% of pushed — 但只有 1 unique candidate 進 tracked)
  → tracked 9
```

### 6.2 中英對照（v4 賣點）

| lang | n_sub | candidates | rules pass | haiku track | final pass |
|------|------:|-----------:|-----------:|------------:|-----------:|
| en   | 10    | 15,117     | 40.8%      | **35.3%**   | 35.3%      |
| zh   | 5     | 2,626      | 38.5%      | **15.1%**   | 15.1%      |

**洞察**：rules pass 兩者接近（38–41%），瓶頸在 haiku。zh 偏低不是 prompt 故障，而是**中文 reddit 社群結構性差異** — 地方 sub（r/taipei 6.6%, r/hongkong 11.0%, r/taiwan 12.1%）內容偏「旅遊 / 美食 / 簽證 / 醫療諮詢」題材，本質不是素人爆文題材。詳見 [m7_haiku_fail_analysis.md](m7_haiku_fail_analysis.md) 三模式診斷。

M7.6 retune（2026-06-08）擴展 SYSTEM_PROMPT 涵蓋議題型 story_potential + 加 0/0 互動 disclaimer，預期能拉高「議題討論型」中文貼文的 pass rate（沒有實時 A/B 數據，OAuth 通過後驗證）。

### 6.3 四類後續事件分布（[eval_relation_dist.py](../scripts/eval_relation_dist.py)）

於 M7 baseline 時點（2026-06-02）：
- avg 9.2 related/篇 + 2.2 milestone/篇
- crosspost / author_followup 各只 1 筆，是否規則太嚴待 OAuth 後重評

### 6.4 後續命中率（[eval_followup_hit.py](../scripts/eval_followup_hit.py)）

- archived tracked（壽命過 30 天）80%
- active tracked 0%（樣本太少，每篇追蹤期還短）

### 6.5 LLM 成本對帳（[eval_llm_cost.py](../scripts/eval_llm_cost.py)）

- 月實測 $1.5（企劃預估 $15–36，**便宜 10×**）
- 主要消耗：Haiku 評分（~17k records × $0.00007 / record ≈ $1.2）+ QA chat（< $0.3，目前 qa_sessions=0 因 RSS comment tree 不完整無法跑 /ask）

### 6.6 Plan C 適應性發現

- 2026-05-29 .json 被擋後切到 RSS，當天到次日 candidate 流量無中斷
- RSS 退化（無 score / comments / karma）讓 haiku 在 60% candidate 上 `Score / Comments: 0 / 0` 入 prompt，M7.6 retune 加 disclaimer 修補
- picker 主桶在 6/6–6/8 連 3 天空（velocity 全 None），Plan C fallback patch（commit `0fae935`）退化為 final_score top 5，6/9 起恢復穩定

---

## Ch7 — 案例分析（待 OAuth）

> **目前無料**：只 9 個 tracked，且其中 8 個是同篇 candidate 被多個 user 收藏（M5 設計第一位 collect 寫 owner，後續者只寫 feedback row）；1 個 unique tracked 的後續事件累積不足。
>
> OAuth 通過 + 連續運轉 14 天後預期 ≥ 3 個完整生命週期案例，覆蓋：
> 1. **事件型**：作者 follow-up 觸發 milestone，後續 crosspost 引用討論
> 2. **議題型**：高分回應驅動的 community 共鳴（M7.6 retune 後預期增多）
> 3. **跨語言追蹤**：中文 sub 起源、英文 sub crosspost 的雙語事件

每個案例展開：
- 推送 → 收藏的決策摘要
- 時間軸圖（score / num_comments / related events 時序）
- 至少 1 個含 crosspost 延伸的案例（v4 賣點之一）

---

## Ch8 — 倫理與資料使用

### 8.1 資料來源公開性

本研究使用的所有 Reddit 貼文與留言皆透過公開 endpoint 取得（subreddit `/new` / `/search` / `submission.duplicates` / `comments`）。Reddit user content 在 Reddit User Agreement 下授權研究使用，但本研究額外採取以下限制以對齊「最小必要原則」：

- 不抓取 `/r/private` / quarantined / over_18 sub
- 不繞過 `[deleted]` / `[removed]` 內容（`_detect_deleted` 統一過濾）
- 不對作者做主動畫像（karma / account_age 只用於 grassroots 訊號計算，不存入 user profile）

### 8.2 去識別化策略

- DB 內 `candidate_posts.author_username` / `tracked_posts.user_id` / `qa_sessions.user_id` 保留原值用於系統運作（去重、owner 認領），但對外輸出（報告 / demo / GitHub）一律去識別：
  - 作者名脫敏為 `u/anonymous_<hash[:6]>`
  - Telegram user_id 不出現在報告
- 對外公開的資料集（次要目標 3）只發布去識別後的 candidate 標題 + selftext + 評分軸，不含作者 / 留言原文

### 8.3 LLM 推論的責任界線

問答層 LLM 答覆基於「抓到的 comment tree + snapshots」上下文 — 當資料缺失（Plan C 期間 RSS 拿不到完整 comment tree）時，prompt 明確要求模型回應「依現有資訊無法判斷」而非編造。reason 欄位保留判斷依據，供使用者驗證。

### 8.4 Reddit API ToS 對齊

- public JSON 路徑遵守 User-Agent 規範（含 username + project name）+ Accept-Language header（避免被當作惡意 bot）
- Rate limit：`min_interval=6.5s` ≈ 9 QPM，遠低於 unauthenticated ~10 QPM 上限
- 不存儲 OAuth token / 不轉發第三方；OAuth 通過後採同樣最小存取（read-only scope）

### 8.5 資料保留與刪除

- candidate / scoring records：90 天滾動保留，超齡批次刪除（未實作，M8 後加 cron）
- tracked posts：使用者 `/forget <id>` 觸發刪除（含 snapshots + related + qa logs；未實作，OAuth 後優先補）
- 學期結束後本地 DB 整段抹除，僅保留去識別化 dataset 與報告

---

## 附錄

- [reddit_tracker_proposal.md](../reddit_tracker_proposal.md) — 完整企劃書 v4
- [PROGRESS.md](../PROGRESS.md) — 開發歷程 + 已知問題
- [SCHEDULE.md](../SCHEDULE.md) — 任務級里程碑 M1–M8
- [v4_schema.md](v4_schema.md) — ER 圖 + 索引設計
- [m1_public_endpoints_probe.md](m1_public_endpoints_probe.md) — endpoint 可行性實測
- [m3_haiku_baseline.md](m3_haiku_baseline.md) — Haiku verdict vs 人工標記
- [m7_baseline_2026-06-02.md](m7_baseline_2026-06-02.md) — M7 baseline 評估
- [m7_haiku_fail_analysis.md](m7_haiku_fail_analysis.md) — M7.6 zh prompt retune 診斷
