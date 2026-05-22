# Reddit Tracker — 專案進度（v4 / Reddit pivot 起始）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 完整企劃見 `reddit_tracker_proposal.md`、任務級里程碑見 `SCHEDULE.md`。
> 進度以里程碑（M1–M8）追蹤，不用週數。

**Last updated:** 2026-05-23（M4 完成 — scheduler + 真實 Telegram 端到端跑通，99/99 tests 全綠）

> **本分支策略**：不申請 OAuth、不用 PRAW，全程走 public JSON endpoint。M1 probe
> 實測 4 個 M5/M6 用得到的 endpoint（user_about / user_submitted / duplicates /
> comments）皆 80%+ 成功率，詳見 [docs/m1_public_endpoints_probe.md](docs/m1_public_endpoints_probe.md)。
> `praw_oauth.py` 暫保留為對照實作，factory 預設只走 `public_json`。

---

## 緣由

前身為 Threads Tracker (v1–v3)。v3 進行到 M3 主幹完成後，重新評估發現 Threads 資料源（Apify Scraper）月成本 $246、且公開搜尋的 cookie 認證風險長期難解。決定整個改建到 Reddit：

- Reddit 資料免費（no-reddit-api 分支走 public JSON endpoint，月成本估 $15–36，降幅 ~90%）
- 留言原生樹狀結構，crosspost 一行 endpoint 即可拿——v3 在 Threads 上 quote 抓不到的問題消失
- Subreddit 是天然主題容器，比關鍵字搜尋更穩定

研究命題與三段式互動（探索 → 推送 → 收藏追蹤 → 問答）完全沿用。

---

## v4 里程碑完成度

| 里程碑 | 主題 | 狀態 | 備註 |
|--------|------|------|------|
| M1 | Reddit API 可行性驗證 | 🟢 | no-reddit-api 分支：public JSON path 跑通連通性、預算、4 endpoint probe；OAuth 不申請 |
| M2 | 探索層 + DB 重構 | 🟢 | 12 表 schema / alembic migration、雙 source discovery、scheduler 雙 job、5/5 tests 過、端到端 smoke 76 筆 |
| M3 | 評分層接 Reddit | 🟢 | 三段式 pipeline 完成、MiniMax scorer 暫代 Haiku、756 真候選跑過、30 篇 baseline accuracy 0.733 ✅ |
| M4 | 候選排程 + 推送層 | 🟢 | feed.py + bot 全部接通 + scheduler 雙 job + 真 Telegram 端到端 (cand=241 收到推送、按 ❤️ 寫 feedback id=1) + 99 tests |
| M5 | 收藏追蹤層 | ❌ | 升格邏輯、分級輪詢、四類後續事件偵測（含 crosspost）|
| M6 | 問答層 | ❌ | `/ask` 對話模式、重量 context 組裝（comment tree）|
| M7 | 評估與調優 | ❌ | 收藏率、後續命中率、中英 subreddit 對照 |
| M8 | 報告與 demo | ❌ | 案例分析 + 問答自評 |

---

## 從舊 Threads Tracker 可移植的資產

**可整段移植（無需改）**：

| 舊檔 | 用途 |
|------|------|
| `config.py` / `db.py` / `cli.py` / `logging.py` | 基礎設施 |
| `llm/base.py` / `factory.py` / `opus.py` / `minimax.py` / `haiku.py` | LLM provider 抽象 + Haiku 評分入口 |
| `services/summarization.py` | EvolutionSummary + 24h cache |
| `services/scoring.py` | 三段式（rules → haiku → final），硬規則閾值要改 Reddit 欄位 |
| `services/polling.py` 的 tier_for_age + select_due_posts | 分級輪詢演算法 |
| `bot/handlers.py` 的 inline button callback 框架 | 三按鈕（❤️ / 👎 / 🔕）流程 |
| `tests/test_summarization.py` `test_llm.py` 大部分 | 改 mock 資料即可 |
| `scheduler.py` 的 job 結構 | 改 job 內部、頻率、新增 subreddit polling |

**需重寫**：

| 模組 | 原因 |
|------|------|
| `scrapers/apify.py` `watcher.py` `factory.py` | 整個刪掉，改寫 `scrapers/json_public.py`（無 OAuth public JSON wrapper） |
| `models.py` | schema 大改：`reddit_post_id`、`subreddit`、`author_karma`、`upvote_ratio`；新增 `subreddit_sources` 表 |
| `alembic/versions/*` | 重生 migration |
| `services/discovery.py` | 主軸由 keyword 改為 subreddit /new，keyword 降為輔助 |
| `services/detection.py` | 改用 public JSON comment tree（`services/comment_tree.py`）+ /duplicates/ endpoint |
| `seeds/*` | 新增 subreddit 名單 + 中英文雙 keyword 種子池 |
| `tests/test_discovery.py` `test_smoke.py` | 跟著 schema 改 |

舊 repo 路徑：`/Users/leroy/Documents/Developer/Project/threads_tracker`（v3 已併入 master）。

---

## 下一步（單一優先）

**M5.1–5.2**：收藏追蹤層。`feedback.action='collect'` 升格 → 建 `tracked_posts`
row、`polling_tier='hot'`；改寫 `services/polling.py` 用分級輪詢（0–24h: 15min /
1–7d: 1h / 7–30d: 6h）抓 post snapshot。完整任務清單見 `SCHEDULE.md`。

### M1 現況（2026-05-22，no-reddit-api 分支結算）

- 🚫 **OAuth 申請取消**：本分支不申請、不用 PRAW；走 public JSON path
- ✅ **M1.2–1.7 等價驗證已過** — 透過 `scripts/m1_hello.py` + `PublicJSONScraper` 跑通：
  fetch_new / search / fetch_post / fetch_duplicates / fetch_user_submissions
- ✅ **M1 endpoint probe**：`scripts/m1_public_endpoints_probe.py` 對 4 個 M5/M6
  關鍵 endpoint 各 6–9 樣本，user_about 83% / user_submitted 100% /
  duplicates 67% / comments 100%（樹深 10 / 500 cap，MoreComments 比例 0%）。
  另確認 `/search.json` (all-reddit) **一律 403**，keyword discovery 須 per-sub
  `restrict_sr=on` 才會通。詳見 [docs/m1_public_endpoints_probe.md](docs/m1_public_endpoints_probe.md)
- ✅ **M1.8 預算試算**：subreddit 14×16 + keyword 20×2 + tracked 30×8 + scoring
  about-lookup ≈ 600 calls/day ≈ 0.4 QPM — public JSON ~10 QPM 餘裕 25×
- ✅ **M1.9 / 1.10 seeds 完成**：`reddit_tracker/seeds/subreddit_list.py`（15 sub，5 中 + 10 英）、
  `keyword_seeds.py`（20 詞，10 中 + 10 英）
- ✅ **M1.11 GO**：public JSON 條件下足以完整推進 M2–M6（含 crosspost、author profile、
  comment tree、重量問答 context），不需 OAuth

### M4 現況（2026-05-23）

- ✅ **M4.7 scheduler.py 雙 job**：`daily_push_job` CronTrigger 01:00 UTC (=09:00 Asia/Taipei)
  + `breaking_check_job` IntervalTrigger 10 分鐘；兩者共用 `_deliver_picks_sync`
  做 sync→async 橋接（`asyncio.run` + `telegram.Bot(token)` lazy import）；缺
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 自動 graceful skip 不阻塞 dev
- ✅ **M4.8 真 Telegram 端到端**：`scripts/m4_smoke.py` 跑 cand=241
  (r/ChineseLanguage, 520 那則) → pick_daily_top5 picked 1 → record_pushes
  inserted 1 → deliver_picks sent 1 → DailyPush.pushed_at 寫入；接著啟動 bot
  polling，使用者按 ❤️ → feedback.id=1 寫入 (user=8555056364, cand=241, action=collect)；
  edit_message_text 把按鈕清掉並附「已收藏」尾註成功
- ✅ **`scripts/m4_capture_chat_id.py`**：跑短時 long polling 抓 chat_id，
  解掉「沒有 chat_id 就無法啟動 push」的雞先蛋先問題
- 🐛 **Markdown→HTML 轉換**：第一次發送遇到 `Can't parse entities` (title 含特殊
  字)；切到 HTML parse mode 後穩定（escape 集合 `< > &` 比 Markdown 小、更可控）
- ✅ **新指令骨架** (`bot/app.py`)：/start /help 上線；/feed /saved /ask /exit
  /digest /timeline /settings 為 deferred stub；CallbackQueryHandler(pattern='^fb:')
  捕捉所有三按鈕

### M4 現況（2026-05-23，bot 骨架）

- ✅ **M4.4 bot/formatter.py**：純函式 `format_push_message(pick) → (markdown, InlineKeyboardMarkup)`；
  header 依 push_type 變化（🔥 已爆貼 / ⚡ 早期下注 / 🚨 即時破例）；callback_data 編
  `fb:<c|d|m>:<candidate_id>`，靠單字節 action 留 64-byte buffer
- ✅ **M4.5 bot/handlers.feedback_callback**：解析 callback_data → `asyncio.to_thread`
  橋接到 sync `services/feedback.record_feedback`（在 sqlite 上跑）→ 回 query.answer
  + edit_message_text 把按鈕清掉。冪等：同 (user, candidate, action) 三元組只寫一筆，
  第二次觸發回 duplicate=True 在 reply 文字加「先前已收到」尾註
- ✅ **bot/sender.py deliver_picks**：每送出一篇就把對應 DailyPush.pushed_at 補
  UTC now；失敗單篇不阻塞 batch
- ✅ **bot/app.py**：build_application 註冊 /start /help + 7 個 deferred stub 指令
  + CallbackQueryHandler(pattern='^fb:')；缺 TELEGRAM_BOT_TOKEN 才會 raise
- ✅ **29 tests**：`tests/test_bot_formatter.py` 17 個（encode/decode 邊界、各 push_type
  header、可選欄位缺漏、Markdown 逃逸）+ `tests/test_bot_handlers.py` 12 個
  （5 個 sync record_feedback + 7 個 async callback，AsyncMock + patch）

### M4 現況（2026-05-23, 早）

- ✅ **M4.1 pick_daily_top5**：`services/feed.py`，過去 24h 內 final.passed=True
  的候選池分桶 — already_hot（age ≥ 6h，velocity 大→小取 3）+ early_bet
  （age < 3h，semantic = (story+emotional)/2 大→小取 2）；中間 3–6h 的灰帶刻意
  落空；缺額不補（兩桶各 1 篇就回傳 2 筆，不會湊滿 5）
- ✅ **M4.2 check_breaking**：age < 1h + velocity 在當前候選池 top 1% 門檻
  + verdict='track' + semantic > 0.85；小樣本（< 100）下 top 1% 退化為「最高 1 筆」；
  讀 `daily_pushes` 算當日已 breaking 筆數扣除剩餘配額（預設 2）；同篇今日已被推
  （任何 push_type）不再 breaking 重推
- ✅ **M4.3 record_pushes**：用 (push_date, candidate_post_id) UniqueConstraint
  防重複 — 預先 SELECT 已存在的 candidate id + 同批 picks 內 dedup，回傳
  PushWriteStat(inserted, skipped_dupe)；`pushed_at` 留 None 給 bot 那層真正送出時回寫
- ✅ **19 tests**：`tests/test_feed.py` — pool 過濾 / 桶分配 / age 邊界 / breaking
  各條件 / daily cap / dedup（DB 既存 + 同批次）全綠
- 🐛 **順手修**：`services/scoring.py::score_batch` 加 `now` 參數轉發給
  `score_candidate`，否則 `test_score_batch_handles_mixed_outcomes` 在 wall-clock
  跨日後會失敗（posted_at 寫死 NOW、batch 用 real clock）

### M3 現況（2026-05-22）

- ✅ **M3.1 硬規則**：`services/scoring.py::apply_hard_rules`，6 條（velocity / karma /
  account age / 文字長度 / 語言 / 黑名單+stickied+mod），karma 與 account age 在
  欄位 None 時放行（public JSON scraper 拿不到這兩個）
- ✅ **M3.2 Haiku prompt**：五軸 + verdict + reason，strict JSON output；
  prompt 容忍 ` ```json fence ` 與閒聊文字夾雜
- ✅ **M3.3 HaikuScorer**：`llm/haiku.py`，包 Anthropic SDK、抓 usage、估
  cost（Haiku 4.5 公定價 $1/$5 per MTok）；factory 在沒 ANTHROPIC_API_KEY 時
  自動 fallback 到 `FakeScorer`
- ✅ **M3.4 combine_final**：`0.4·v + 0.3·s + 0.2·g + 0.1·n`，
  velocity 用 `v / (v + 10)` 正規化進 [0,1]
- ✅ **M3.5 ScoringService**：rules → haiku → final 三段式寫入；rules fail 時
  跳過 Haiku 仍寫 placeholder row；Haiku exception 寫 error row 不阻塞 batch
- ✅ **M3.6 scheduler.scoring_job**：APScheduler 每 30 分鐘掃未評分 candidate，
  啟動跑一輪；config 加 `scoring_minutes` / `scoring_batch_limit`
- ✅ **M3.8 tests**：`tests/test_scoring.py` 28 個 case（硬規則 12 + combine 3 +
  parsing 5 + service 5 + lang_detect 3），全綠
- ✅ **M3.7 人工標記**：public JSON 累積 756 筆真實 candidate（一次 discovery 跑完），
  52 筆已過 rules + MiniMax 評分；隨機抽 30（zh 16 / en 14），Opus 充當人工標記，
  accuracy **0.733**（門檻 0.60 過）；錯誤偏 over-track（FP=7 vs FN=1），主要是
  AskReddit 式討論題、新聞轉貼、規則 meta 問題。詳細見
  [docs/m3_haiku_baseline.md](docs/m3_haiku_baseline.md)
- ✅ **MiniMax scorer**：`llm/minimax.py` 暫代 Haiku，OpenAI-compatible chat
  completion；每篇 ~$0.0002 USD、~3s 延遲；若有 ANTHROPIC_API_KEY 可隨時切回 Haiku 4.5
- ✅ **M3 smoke**：`scripts/m3_smoke.py` 用 FakeScraper 跑通 discovery → scoring
  完整 wiring；39 candidate × 3 stage = 117 scoring_records 寫入正確

### M2 現況（2026-05-15）

- ✅ **M2.1 ER 圖**：`docs/v4_schema.md`，12 張表 mermaid + 索引設計
- ✅ **M2.2 models.py**：12 張 SQLAlchemy 2.0 declarative model，含 v3 兩個 gotcha 應對
- ✅ **M2.3 alembic init + 第一支 migration**（`alembic/versions/c0d4993bb6f1_initial_schema_12_tables.py`）
- ✅ **M2.4 upgrade head**：SQLite 上跑通，13 張表（含 alembic_version）
- ✅ **M2.5–2.7 scraper 抽象**（M1 已完成）+ **M2.6 FakeScraper**（50 筆 fixture，中英混合 + 邊界）
- ✅ **M2.8 seeds loader**：冪等 upsert，不覆寫 enabled / 統計欄位
- ✅ **M2.9 / 2.10 discovery**：subreddit /new + keyword search 雙路徑，dedup + 統計回寫
- ✅ **M2.11 scheduler**：APScheduler `BlockingScheduler`，60min sub + 6h keyword 雙 job，啟動跑一輪
- ✅ **M2.12 tests**：5/5 PASS（dedup × 2、disabled skip、deleted skip、keyword dedup）
- 🟡 **M2.13 連續 24h**：尚未跑；端到端 smoke 已驗證 wiring 正確（76 candidate ingested）

### 已知坑（M1+M2+M3 階段踩到的）

- **SQLite + `DateTime(timezone=True)` 載回會掉 tzinfo** → scoring 算 age_hours
  會 `can't subtract offset-naive and offset-aware`；統一在
  `services/scoring.py::_ensure_utc` 補成 UTC



- Reddit 對 unauthenticated 請求做 TLS / header 指紋偵測：
  - **缺 `Accept-Language` header → 403 Blocked**（即使 UA 完全合法）
  - **httpx 的 TLS 指紋不穩**（同一 client r/Taiwan 200、r/tifu 403）；改用 `requests` 後穩定
  - User-Agent 必須含具識別性的字串（含 username 或 project name），否則 403
- `PublicJSONScraper.fetch_duplicates()` 早期觀察「常為空」其實是樣本太新（r/new 抓的）；
  改抓 `num_crossposts > 0` 的 post 後實測 67% 成功率，count 與 endpoint 回的 dups 數一致。
  M5 crosspost 偵測可走 public path，但需容忍偶發 403（NSFW / quarantine）
- `/search.json`（all-reddit）對未認證請求 403。`services/discovery.py::discover_from_keywords`
  已改為對每個 lang-compatible enabled subreddit 各做 `restrict_sr=on` 搜尋的 fan-out 模式
- SQLite + `DateTime(timezone=True)` 不會強制 timezone，但 SQLAlchemy 會做 conversion；
  testing 用 in-memory SQLite 沒問題

---

## 環境檢查（新 repo 初始化用）

```bash
# 1. 安裝 / 同步依賴
uv sync

# 2. 建 DB schema
uv run alembic upgrade head

# 3. 一次性 smoke（載 seeds + 跑一輪 discovery）
uv run python scripts/m2_smoke.py

# 4. 持續運轉（兩個 discovery job）
uv run python -m reddit_tracker.scheduler

# 5. 連通性 / 預算驗證
uv run python scripts/m1_hello.py

# 6. M5/M6 用得到的 endpoint 可行性驗證（一次跑完約 2 分鐘）
uv run python scripts/m1_public_endpoints_probe.py
```

---

## 沿用 v3 踩過的坑（直接記下避免重踩）

- SQLite BigInt PK 不會 auto-increment → `BigInteger().with_variant(Integer(), "sqlite")`
- alembic 自訂 type（`JSONField`）找不到 → `alembic/script.py.mako` 加 `import <pkg>.models`
- scraper factory 沒設 token 自動 fallback fake（Reddit 版可沿用此 pattern）
- 預設 SQLite，切 Postgres 改 `DATABASE_URL`
- APScheduler 排程頻率取 `poll_hot_minutes // 3`
- `LLMSummary.content` 存 JSON 字串（不開新欄位），`parse_evolution()` 還原
- summarization 24h cache 用「最新 evolution row 的 `generated_at`」判斷
- LLM provider 抽到 `llm/factory.py`，`LLM_PROVIDER=anthropic|minimax` 切
- LLM 回傳的 JSON 容忍 ` ```json ` fence

---

## v4 新引入的設計決策（待驗證）

- **Subreddit /new 為主、關鍵字為輔**：12–20 個目標 sub、每 60 分鐘掃；keyword 每 6 小時跑一次補事件性貼文
- **中英混合**：r/Taiwan、r/HongKong 等中文 sub + r/TIFU 等英文 storytelling sub；報告需做語言分布分析
- **每日推送 5 篇 = 3 已爆 + 2 早期**：固定配比，可由 config 調整
- **問答 context 比 v3 肥 50%**：Reddit comment tree 樹狀且更長，重量 context 預估 12k–45k input tokens（v3 是 8k–35k）
- **個位數使用者共用同一份每日推送**：先不做個人化
- **Public JSON QPM 控制**：保持 < 9 QPM（PublicJSONScraper 預設 min_interval 6.5s ≈ 9 QPM；Reddit unauthenticated hard limit ~10 QPM）

---

## 已知未驗證 / 風險

- Reddit API 政策變動（2023 Apollo 事件 precedent）— M1 註冊時選對類型即可，但長期需留意
- 中文 subreddit 樣本量不足（每日 50–100 篇）→ 英文 sub 作為主要樣本
- 重量 context 問答 token 成本（預估 $0.15/次）— M6 實測
- Public JSON 對 deleted / removed 貼文的處理（content = `[deleted]` / `[removed]`）已在 `scrapers/base.py::_detect_deleted` 統一判斷
- 沒有推播 retry / rate limit 處理（沿用 v3 待補）
