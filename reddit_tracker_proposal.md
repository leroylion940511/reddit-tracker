# Reddit 素人爆文發現、追蹤與問答系統 — 專題企劃書 v4

> **v4 與 v3 的核心差異**
> v3 立基於 Threads + Apify Scraper，成本實測落在 $246/月，且仍受 Threads 公開搜尋的 cookie 認證風險。
> v4 改採 **Reddit 官方 API（PRAW）** 作為主資料來源，每月成本估 $15–25（降幅約 90%），且資料抓取合規性大幅優於第三方 scraper。
> 平台改變的同時，**核心命題與三段式互動模型（探索 → 推送 → 收藏追蹤 → 問答）一律沿用 v3**，已寫好的評分層 / DB schema 大架構繼續用，僅替換資料來源與抽取邏輯。

---

## 一、專題動機與背景

社群平台每天都有素人貼文意外爆紅。讀者當下被吸引、留言追問「後來呢？」，但因為這類貼文不在原本追蹤清單內，極容易錯過後續發展。

v3 選擇 Threads 為觀察平台，但實際進入 M2 後發現兩個結構性問題：

1. **資料取得成本過高**：Threads 公開搜尋自 2025 年底起限制 cookie 認證，必須透過第三方 scraper（Apify），實測 production 預設規模即達每月 $246，且仍要承擔 actor 維護中斷、欄位變動的風險。
2. **回貼追蹤天然劣勢**：Threads 的留言是 flat 結構，引用討論（quote）難以聚合；要做「事件後續追蹤」必須額外搜尋，每追一篇就要再耗一次 scraper quota。

Reddit 在這兩點上是天然的好替代：

- **官方 API 免費**（在 100 QPM rate limit 內），不需 scraper
- **留言原生是樹狀結構**，「四類後續事件」中的三類（作者更新、高分留言、引用討論）都有直接對應的 API endpoint
- **Subreddit 是天然主題容器**，比關鍵字搜尋更穩定可預測
- **`submission.duplicates()`** 一行就能拿到所有 crosspost / 引用討論

v4 由此沿用 v3 的研究命題（**素人爆文發現 + 收藏追蹤 + 對話式問答**），但把資料層換成 Reddit，重新評估每一層的設計。

## 二、專題目標

### 主要目標（沿用 v3）

1. 建立**自動化探索 + 評分流水線**，每日從目標 subreddit 與關鍵字產出 Top 5 候選清單
2. 透過 Telegram Bot **每日定時推送**，使用者以 inline button 三選一（❤️ 收藏 / 👎 不感興趣 / 🔕 靜音）
3. 對使用者收藏的貼文進入**長期追蹤池**，自動偵測後續發展（原 PO 新貼文、原 PO 留言更新、高分回應、crosspost 引用）並推播
4. 提供 `/ask <id>` **對話式問答模式**，使用者可對單一事件做多輪 LLM 問答

### 次要目標

1. 探討「演算法判斷貼文價值」與「使用者收藏行為」的相關性
2. 評估在重量級 context（含完整 comment tree）下，LLM 對素人事件的問答品質
3. 建立可重現的素人爆文資料集（去識別化）

### 範圍限定

- **語言**：中文（r/Taiwan、r/HongKong、r/ChineseLanguage 等）+ 英文 storytelling subreddit 混合
- **使用者規模**：個位數，共用同一份每日推送清單，不做個人化
- **平台**：純 Reddit，不混 Threads / X / Dcard

## 三、系統架構

### 整體架構：探索流水線 + 收藏追蹤雙環

```
[每日推送主環]                              [收藏追蹤副環]

┌─────────────────┐                         ┌──────────────────┐
│ ① 探索層         │                         │ ⑤ 收藏池          │
│ Subreddit /new + │                         │ (使用者 ❤️ 後)    │
│ 關鍵字補充       │                         └────────┬─────────┘
│ 每 60 分鐘       │                                  ↓
└────────┬────────┘                         ┌──────────────────┐
         ↓                                  │ ⑥ 追蹤層          │
┌─────────────────┐                         │ 分級輪詢          │
│ ② 評分層         │                         │ 15min/1h/6h      │
│ 硬規則 → Haiku  │                         │ 抓四類後續事件    │
│ → 加權分數       │                         └────────┬─────────┘
└────────┬────────┘                                  ↓
         ↓                                  ┌──────────────────┐
┌─────────────────┐                         │ ⑦ 後續推送        │
│ ③ 候選排程層     │                         │ 有後續即推 / 整合 │
│ 每日 09:00 取    │                         │ 至每日彙整        │
│ Top 5            │                         └────────┬─────────┘
│ (3 已爆+2 早期)  │                                  ↑
└────────┬────────┘                                  │
         ↓                                  ┌──────────────────┐
┌─────────────────┐                         │ ⑧ 問答層          │
│ ④ 推送層         │ ──────❤️ 收藏─────────→ │ /ask <id>        │
│ Telegram +       │                         │ 重量 context     │
│ inline button    │                         │ 多輪對話 /exit   │
│ + 即時破例推送   │                         └──────────────────┘
└─────────────────┘
```

### 技術選型

| 層級 | 技術 | 選用理由 |
|------|------|---------|
| 後端框架 | Python 3.11 + FastAPI | 沿用 v1 baseline |
| 資料庫 | SQLite (dev) / PostgreSQL (prod) | 個位數使用者初期 SQLite 即可 |
| 排程 | APScheduler | 已驗證可行 |
| **主資料來源** | **Reddit API + PRAW 7.x** | **官方 API、免費、文件齊全、留言樹原生支援** |
| LLM 評分 | Claude Haiku 4.5 | 低成本快速判斷 |
| LLM 摘要 + 問答 | Claude Opus 4.7 | 重量 context 需強推理 |
| 通知介面 | python-telegram-bot | 已驗證可行 |
| 部署 | Docker + Railway / 本地 | 個位數使用者本地跑也夠 |

### 從 v3 程式碼繼承

v3 已完成 M1–M3 主幹，大部分可直接沿用：

| v3 既有檔 | v4 處置 |
|--------|------|
| `config.py` / `db.py` / `cli.py` / `logging.py` | ✅ 留 |
| `models.py`（v3 schema） | 🔧 改欄位名 + 新增 Reddit 專屬欄位 |
| `scrapers/apify.py` `factory.py` | 🗑️ **刪** |
| `scrapers/reddit.py` | 🆕 新增（PRAW wrapper + 統一資料模型） |
| `services/discovery.py` | 🔧 主軸由 keyword 改為 subreddit /new；keyword 降為輔助 |
| `services/scoring.py` | ✅ **大致全留**（硬規則閾值微調，Haiku prompt 改寫 grassroots 判定方式） |
| `services/summarization.py` | ✅ 留 |
| `services/detection.py` | 🔧 改為使用 PRAW 的 reply tree 比對 |
| `seeds/loader.py` | 🔧 改載 subreddit list + 新一批繁中/英文 keywords |
| `scheduler.py` | 🔧 沿用 job 結構，改 discovery job 內部 |
| `llm/*` | ✅ 全留 |
| `bot/*` | 🔧 沿用 inline button 設計，文字內容改 Reddit-friendly |

v3 已完成的 scoring layer（46 tests passed）幾乎能整段搬過來，**估 v4 重寫成本約 30–40%**。

## 四、核心功能設計

### 4.1 探索層：Subreddit /new 為主 + 關鍵字補充

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

### 4.2 評分層：三層篩選（沿用 v3 主幹）

#### 第一層 硬規則（Reddit 化調整）

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

### 4.3 候選排程層：每日 Top 5 = 3 已爆 + 2 早期

完全沿用 v3 設計：

| 類型 | 數量 | 條件 |
|------|------|------|
| 已爆 | 3 | 互動速度排名前 3，且發文時間 ≥ 6 小時 |
| 早期 | 2 | 發文時間 < 3 小時，semantic_score 排名前 2 |

#### 即時破例推送

候選池中出現「發文 1 小時內互動速度 Top 1%（Reddit 換算 ups_per_hour > 100 + comments_per_hour > 30）且 Haiku verdict=track 且 semantic_score > 0.85」，立即推送。每日上限 2 則。

### 4.4 推送層：每日 09:00 + inline button

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

### 4.5 收藏與追蹤層

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

#### 後續推送

預設整合至每日彙整（追加在當日 5 篇推薦之後，標題改「📌 你收藏的事件有更新」）。
例外：Haiku 判定「重大進展」（例如當事人現身、結局揭曉）→ 即時推送。

### 4.6 問答層：對話模式

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

> **與 v3 差異**：Reddit comment tree 比 Threads flat 留言「肥」許多（reply 巢狀 + 通常更長），預估 context 比 v3 大 50%。對應地調高 prompt cache 命中閾值（同 tracked_post_id 在 5 分鐘內重用）。

保留輕量 / 中量模式作為旗標：`/ask <id> --light <問題>` 只給原文 + 摘要。

#### 對話狀態管理（沿用 v3）

- 每個使用者同時只能進入一個事件的問答模式
- `/exit` 或 5 分鐘無訊息自動結束
- 對話歷史寫入 `qa_sessions` 與 `qa_messages`

#### 問題類型（預期）

事件結論型 / 輿情整理型 / 人物背景型 / 跨貼文連結型（crosspost 是天然素材）/ 細節考據型。

## 五、資料庫設計

v3 schema 大部分沿用，僅換欄位名 + 新增 Reddit 專屬欄位。

```sql
-- 探索層產出（欄位 Reddit 化）
CREATE TABLE candidate_posts (
    id BIGSERIAL PRIMARY KEY,
    reddit_post_id VARCHAR(16) UNIQUE NOT NULL,   -- PRAW submission.id
    subreddit VARCHAR(64) NOT NULL,
    title TEXT,
    selftext TEXT,
    permalink VARCHAR(255),
    author_username VARCHAR(64),
    author_karma INT,
    author_created_utc TIMESTAMPTZ,                -- 帳號年齡判定用
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    discovery_source VARCHAR(64),                   -- 'subreddit:<name>' / 'keyword:<seed>'
    initial_score INT,                              -- ups - downs
    initial_num_comments INT,
    upvote_ratio FLOAT,
    lang VARCHAR(8),                                -- 'zh-Hant' / 'en' / ...
    metadata JSONB                                  -- 完整 PRAW raw 備份
);

-- 評分結果（沿用 v3）
CREATE TABLE scoring_records (
    id BIGSERIAL PRIMARY KEY,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    stage VARCHAR(16),                              -- 'rules' / 'haiku' / 'final'
    passed BOOLEAN,
    score FLOAT,
    details JSONB,
    scored_at TIMESTAMPTZ DEFAULT NOW(),
    cost_usd NUMERIC(10, 6)
);

-- 每日推送清單（沿用 v3）
CREATE TABLE daily_pushes (
    id BIGSERIAL PRIMARY KEY,
    push_date DATE,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    push_type VARCHAR(16),                          -- 'already_hot' / 'early_bet' / 'breaking'
    rank INT,
    pushed_at TIMESTAMPTZ
);

-- 使用者反饋（沿用 v3）
CREATE TABLE feedback (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    action VARCHAR(16),                             -- 'collect' / 'dislike' / 'mute_author'
    acted_at TIMESTAMPTZ DEFAULT NOW()
);

-- 收藏池（沿用 v3）
CREATE TABLE tracked_posts (
    id BIGSERIAL PRIMARY KEY,
    candidate_post_id BIGINT REFERENCES candidate_posts(id),
    user_id BIGINT,
    promoted_at TIMESTAMPTZ DEFAULT NOW(),
    polling_tier VARCHAR(16) DEFAULT 'hot',
    last_polled_at TIMESTAMPTZ,
    status VARCHAR(16) DEFAULT 'active',
    initial_summary TEXT
);

-- 快照（時序資料，Reddit 化）
CREATE TABLE post_snapshots (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    score INT,
    num_comments INT,
    upvote_ratio FLOAT,
    new_comments JSONB                              -- 自上次以來新增 comment 摘要
);

-- 後續事件四類（沿用 v3，relation_type 多了 'crosspost'）
CREATE TABLE related_posts (
    id BIGSERIAL PRIMARY KEY,
    tracked_post_id BIGINT REFERENCES tracked_posts(id),
    reddit_post_id VARCHAR(16),                     -- comment 用 t1_xxxx, submission 用 t3_xxxx
    relation_type VARCHAR(16),                      -- 'author_followup' / 'author_reply' / 'hot_reply' / 'crosspost'
    relevance_score FLOAT,
    is_milestone BOOLEAN DEFAULT FALSE,
    content TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW()
);

-- LLM 紀錄 / qa_sessions / qa_messages：完全沿用 v3，無改動

-- 探索來源：subreddit + keyword 兩個 source 表
CREATE TABLE subreddit_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(64) UNIQUE,
    lang_hint VARCHAR(8),                           -- 'zh' / 'en' / 'mixed'
    enabled BOOLEAN DEFAULT TRUE,
    last_polled_at TIMESTAMPTZ,
    total_candidates_yielded INT DEFAULT 0,
    total_promoted INT DEFAULT 0,
    total_collected INT DEFAULT 0
);

CREATE TABLE keyword_seeds (                        -- 沿用 v3 名稱與結構
    id SERIAL PRIMARY KEY,
    keyword VARCHAR(64) UNIQUE,
    category VARCHAR(32),
    lang VARCHAR(8),                                -- 新增：'zh' / 'en'
    enabled BOOLEAN DEFAULT TRUE,
    last_polled_at TIMESTAMPTZ,
    total_candidates_yielded INT DEFAULT 0,
    total_promoted INT DEFAULT 0,
    total_collected INT DEFAULT 0
);
```

## 六、演算法評估方法（沿用 v3）

### 6.1 量化指標

| 指標 | 定義 | 目標值 |
|------|------|--------|
| 收藏率 (Collection Rate) | 推送的貼文中被使用者 ❤️ 的比例 | ≥ 30% |
| 後續命中率 | 收藏的事件在 30 天內偵測到至少 1 個有效後續的比例 | ≥ 50% |

評估期：系統穩定運行後第 4–8 週。

### 6.2 質性章節

3–5 個案例敘事分析，重點：系統推送依據、收藏時點、後續發展是否符合預期、問答品質。

### 6.3 問答品質評估

抽 30 組 (問題, 回答) pair，研究者自評：事實正確性（0–1）、引用 context 的精準度（0–1）、是否有幻覺。

### 6.4 v4 額外可比較項

因為 Reddit 的 crosspost / comment tree 是 native，可額外報告：

- 「四類後續事件」各類偵測量分布（v3 在 Threads 上 quote 幾乎抓不到，v4 應顯著改善）
- 中文 subreddit vs 英文 subreddit 的收藏率差異（語言/文化因子分析）

## 七、開發里程碑

依任務依賴排序，不綁週數。任務級拆解見 `SCHEDULE.md`（v3 SCHEDULE.md 需重做）。

| 里程碑 | 主題 | 前置 | 主要產出 |
|--------|------|------|---------|
| M1 | Reddit API 可行性驗證 | — | 申請 OAuth app、PRAW hello world、確認 100 QPM 額度足夠、跑通 /new + search + duplicates |
| M2 | 探索層 + DB 重構 | M1 GO | Reddit schema、subreddit + keyword 雙來源 loader、每 60 分鐘輪詢、純記錄候選 |
| M3 | 評分層接 Reddit | M2 累積 ≥ 200 筆 candidate | 從 v3 移植硬規則 + Haiku，依 Reddit 欄位改寫；30 篇人工標記驗證 |
| M4 | 候選排程層 + 推送層 | M3 final_score 可算 | 每日 09:00 Top 5、inline button、即時破例推送 |
| M5 | 收藏追蹤層 | M4 ❤️ 能寫 feedback | 升格邏輯、分級輪詢、四類後續事件偵測（含 crosspost）|
| M6 | 問答層 | M5 有追蹤資料 | `/ask` 對話模式、重量 context 組裝（comment tree + crosspost）|
| M7 | 評估資料蒐集 + 調優 | M6 流水線完整 + 累積 7 天資料 | 收藏率、後續命中率統計；中英 subreddit 對照 |
| M8 | 報告與 demo | M7 評估數據完整 | 撰寫報告、3–5 案例分析、demo 影片 |

**v4 vs v3 進度繼承**：
- M1 重做（不同平台），但比 v3 M1 更輕量（不需算 Apify quota，PRAW 申請即用）
- M2 schema 重做但程式架構沿用 v3 已完成的 discovery service
- M3 scoring 程式可整段移植，只改 prompt 與硬規則欄位對應

預估 M1–M3 重做時間：**5–8 天**（v3 在這三個里程碑共花了約 14 天）。

## 八、成本估算

### 每日成本（穩定運行階段）

| 項目 | 計算 | v3 成本 | v4 成本 |
|------|------|---------|---------|
| 資料源（探索） | Reddit API 免費 vs Apify 2000 篇 × $0.003 | $6 | **$0** |
| 資料源（追蹤） | Reddit API 免費 vs Apify 30 篇 × 8 次 × $0.005 | $1.2 | **$0** |
| 資料源（深挖） | Reddit API 免費 | $0.05 | **$0** |
| Haiku 評分 | 200 筆 × $0.001（與 v3 同） | $0.2 | $0.2 |
| Opus 摘要 | 5 篇 × $0.05（與 v3 同） | $0.25 | $0.25 |
| Opus 問答 | 5 次 × $0.15（context 較 v3 大 50%） | $0.5 | $0.75 |
| **每日總計** | | **$8.2** | **約 $1.2** |
| **每月總計** | | **$246** | **約 $36** |

進一步若啟用 Opus prompt cache（同 tracked_post_id 在 5 分鐘內重用），問答成本可再降 50%，每月實際支出落在 **$15–25**。

### 成本控制機制

- `llm_records` + Reddit API 用量寫入 metrics
- 每日 dashboard 即時看
- Reddit API 100 QPM rate limit 在 PRAW 內建 backoff，沒 hard cap 風險
- LLM 設每日 hard cap（預設 $5）作為保險絲

## 九、風險與應對

### 風險一：Reddit API 政策變動
2023 年 Reddit 對第三方 client 商業使用大幅收費（Apollo 事件）。本專題為個人 / 研究用途，目前仍在免費額度（100 QPM）內。

**應對**：
- 註冊時明確選擇 "personal use script" 類型
- 不對外提供 public API（資料只進 Telegram bot）
- 用量保持在 < 60 QPM（保留 buffer）
- 備案：若 API 收費，退化成「使用者主動貼 Reddit URL」單篇追蹤模式

### 風險二：中文 subreddit 樣本不足
r/Taiwan、r/HongKong 每日有效 candidate 約 50–100 篇，明顯低於英文 sub。

**應對**：
- 把英文 sub 作為主要樣本，中文 sub 作為次要對照
- 報告中明示語言分布、避免過度推論
- 必要時擴充 r/translator、r/China_irl 等含中文比例較高的 sub

### 風險三：使用者收藏率過低（< 10%）
表示評分演算法跟使用者口味落差大。

**應對**：用收藏資料反向 fine-tune Haiku prompt、加大「早期」配額觀察是否偏好獨特性內容。

### 風險四：問答模式 token 燒太快
Reddit comment tree 深 + 長，重量 context 可達 45k tokens。

**應對**：
- 預設啟用 prompt cache
- 自動降級成中量模式（comment tree 只截 top 30 條）
- 單日問答次數軟上限

### 風險五：合規與隱私
- 僅處理公開貼文
- 不在報告中展示真實使用者帳號（去識別化）
- 提供 `/forget <id>` 指令完整刪除單一事件資料
- 遵守 Reddit API ToS（不轉售、不訓練）
- 報告專章討論社群媒體研究倫理

## 十、預期成果

### 可交付項目

1. 完整可運作的 Telegram bot demo
2. GitHub repository（已公開）
3. 專題書面報告（中文，約 30 頁）
4. 5 分鐘 demo 影片
5. 3–5 個從推送 → 收藏 → 完整生命週期的案例分析
6. 系統運行 4 週的量化評估數據（收藏率、後續命中率、中英對照）
7. 30 組問答 pair 的品質自評結果

### 質性評估

- 系統能否持續產出讓使用者願意收藏的內容
- 收藏的事件是否真的有後續發展
- 重量 context（含完整 comment tree）下的問答品質是否值得成本
- 「早期捕捉」配額是否真的搶在 viral 之前發現過案例
- Reddit 原生 crosspost 對「事件後續追蹤」的幫助程度

## 十一、與 v3 的差異對照

| 面向 | v3 (Threads) | v4 (Reddit) |
|------|--------------|-------------|
| 資料來源 | Apify 第三方 scraper | Reddit 官方 API (PRAW) |
| 成本 / 月 | $246 | $15–36 |
| 探索主策略 | 純關鍵字輪詢 | Subreddit /new + keyword 輔助 |
| 語言 | 純繁中 | 繁中 + 英文混合 |
| 後續事件偵測 | 四類，但 quote 難抓 | 四類，crosspost 原生支援 |
| 留言結構 | flat | 樹狀（context 更肥） |
| 主要風險 | scraper 中斷、cookie 認證 | Reddit API 政策變動 |
| 已寫程式碼可繼承 | — | scoring layer 整段、LLM 抽象、bot 框架 |

## 十二、未來延伸

1. 個人化權重（用 `feedback` 訓練）
2. 多平台擴充（補回 Threads / 加 Dcard）
3. 問答時動態決定 context mode（依問題類型自動切換 light/medium/heavy）
4. Reddit award / gilded 訊號納入評分權重
5. Web 介面：時間軸視覺化 + crosspost graph
6. 中英雙語 sub 的「跨文化敘事差異」研究章節

## 附錄：技術文件參考

- Reddit API: https://www.reddit.com/dev/api/
- PRAW: https://praw.readthedocs.io
- python-telegram-bot: https://docs.python-telegram-bot.org
- Anthropic API: https://docs.claude.com
- APScheduler: https://apscheduler.readthedocs.io
- FastAPI: https://fastapi.tiangolo.com
