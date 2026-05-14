# Reddit Tracker v4 — 任務級里程碑

> 與 `reddit_tracker_proposal.md` §七 對應，展開到可勾選任務粒度。
> 每個里程碑「完成判準」全部達標後才進下一個。沒有週數，只看任務。

---

## M1 — Reddit API 可行性驗證（阻塞所有後續）

**前置**：無
**完成判準**：拿到 OAuth credentials、PRAW 跑通 /new + search + duplicates 三個 API、確認 100 QPM 內可達成每日吞吐目標

- [ ] 1.1 到 https://www.reddit.com/prefs/apps 註冊「personal use script」app，取 `client_id` / `client_secret`，寫進 `.env`
- [ ] 1.2 安裝 PRAW (`uv add praw`)，寫 `scripts/m1_praw_hello.py` 驗證 `reddit.read_only` 連得上
- [ ] 1.3 試 `reddit.subreddit("Taiwan").new(limit=50)`，確認回貼文 + 欄位齊（id, title, selftext, author, score, num_comments, created_utc, permalink, upvote_ratio）
- [ ] 1.4 試 `reddit.subreddit("all").search("update", time_filter="day", limit=50)` 跑跨 sub 關鍵字搜尋
- [ ] 1.5 試 `submission.duplicates()` 拿 crosspost（找一個熱門 submission ID 驗）
- [ ] 1.6 試 `submission.comments.replace_more(limit=0)` + 樹狀遞迴，估完整 comment tree 抓取耗時 / API call 數
- [ ] 1.7 試 `reddit.redditor(name).submissions.new(limit=20)` 抓作者近期貼文
- [ ] 1.8 計算每日 API call 預算：16 sub × 24 次 + 20 keyword × 4 次 + 追蹤池 30 篇 × 8 次 ≈ 1100 calls/天 → 換算 QPM 約 0.8，遠低於 100 QPM 上限
- [ ] 1.9 草擬 subreddit 初始名單（4–6 中文 + 8–14 英文）寫進 `seeds/subreddit_list.py`
- [ ] 1.10 草擬中英文雙 keyword 種子池（各 10 詞）寫進 `seeds/keyword_seeds.py`
- [ ] 1.11 寫 M1 結論段（PROGRESS.md 「下一步」改寫成 M2），標 GO / NO-GO

---

## M2 — 探索層 + DB 重構

**前置**：M1 GO
**完成判準**：自動跑 discovery，寫入 `candidate_posts` 並更新 `subreddit_sources` + `keyword_seeds` 統計

- [ ] 2.1 ER 圖（mermaid）→ `docs/v4_schema.md`，10 張表
- [ ] 2.2 寫 `models.py`：candidate_posts（含 subreddit, author_karma, upvote_ratio）+ 其餘 9 張表
- [ ] 2.3 alembic init + 第一個 migration（10 表 + 索引）
- [ ] 2.4 `alembic upgrade head` 驗證；空 DB schema OK
- [ ] 2.5 寫 `scrapers/reddit.py::RedditScraper`：PRAW 包一層，吐統一的 `PostPayload` dataclass（沿用 v3 介面）
- [ ] 2.6 寫 `scrapers/fake.py`：fixture-based fake scraper，吐預設 50 筆假 Reddit 資料供測試
- [ ] 2.7 寫 `scrapers/factory.py`：依環境變數切 real / fake
- [ ] 2.8 寫 `seeds/subreddit_list.py` + `seeds/keyword_seeds.py` + `seeds/loader.py`（冪等寫入 DB）
- [ ] 2.9 寫 `services/discovery.py::discover_from_subreddits`：批次掃 sub /new → 寫 `candidate_posts`（reddit_post_id UNIQUE 去重）+ 更新 `subreddit_sources` 統計
- [ ] 2.10 寫 `services/discovery.py::discover_from_keywords`：跨 sub 搜尋 → 寫 candidate（同 dedup）
- [ ] 2.11 寫 `scheduler.py`：`subreddit_discovery_job`（IntervalTrigger 60min）+ `keyword_discovery_job`（IntervalTrigger 6h）
- [ ] 2.12 `tests/test_discovery.py`：sub /new dedup、keyword dedup、disabled source、stat update、PRAW deleted 貼文處理
- [ ] 2.13 連續跑 24h，目標累積 ≥ 200 筆 candidate 作為 M3 評分驗證的料

---

## M3 — 評分層接 Reddit

**前置**：M2 candidate_posts ≥ 200 筆真實資料
**完成判準**：每 30 分鐘自動評分新 candidate，產 final_score 並寫 scoring_records；Haiku verdict 對人工標記準確率 ≥ 60%

- [ ] 3.1 寫 `services/scoring.py::apply_hard_rules`：互動速度 / karma / 帳號齡 / 文字長度 / 中英語言檢測 / stickied 過濾
- [ ] 3.2 寫 Haiku 評分 prompt 五軸 + verdict + reason（中英文都吃，prompt 明確要求標準一致）
- [ ] 3.3 接 `llm/haiku.py::score_candidate`，回 `CandidateScore`（含 token / cost）
- [ ] 3.4 寫加權合併 `combine_final(rules, haiku)`：`final = 0.4·v + 0.3·s + 0.2·g + 0.1·n`
- [ ] 3.5 寫 `ScoringService.score_candidate`：rules → haiku → final 三段式寫入 `scoring_records`
- [ ] 3.6 接 `scheduler.py::scoring_job` 每 30 分鐘批次掃尚未評分的 candidate
- [ ] 3.7 從 M2 累積資料隨機抽 30 篇人工標記（track / skip），跟 Haiku verdict 對比，記準確率到 `docs/m3_haiku_baseline.md`
- [ ] 3.8 unit test：硬規則邊界值 + 加權邏輯（mock Haiku）+ failure path（Haiku 回 invalid JSON）

---

## M4 — 候選排程層 + 推送層

**前置**：M3 final_score 可算
**完成判準**：每日 09:00 推 5 篇到 Telegram，破例觸發即時推送，按鈕回寫 feedback

- [ ] 4.1 寫 `services/feed.py::pick_daily_top5`：過去 24h 候選池選 3 已爆（age ≥ 6h, velocity rank top 3）+ 2 早期（age < 3h, semantic rank top 2）
- [ ] 4.2 寫 `services/feed.py::check_breaking`：即時破例條件（age < 1h, velocity top 1%, haiku=track, semantic > 0.85），每日上限 2
- [ ] 4.3 daily_pushes 寫入流程 + 防重複（同 candidate 不重推）
- [ ] 4.4 寫 `bot/handlers.py` 推送訊息格式器：subreddit + 互動數 + karma + Opus 摘要 + 三按鈕
- [ ] 4.5 inline button callback：❤️→feedback.action='collect'、👎→'dislike'、🔕→'mute_author'
- [ ] 4.6 bot 指令：`/feed`、`/digest`、`/settings`（先做骨架，settings 內容後續補）
- [ ] 4.7 接 `scheduler.py`：`daily_push_job` 每日 09:00、`breaking_check_job` 每 10 分鐘
- [ ] 4.8 端到端測：fake scraper → discovery → scoring → daily push 訊息真的出現在 Telegram

---

## M5 — 收藏追蹤層

**前置**：M4 ❤️ 按鈕能寫 feedback
**完成判準**：收藏一篇後，系統自動偵測四類後續事件（含 crosspost）並推送

- [ ] 5.1 寫升格邏輯：`feedback.action='collect'` → 建 `tracked_posts` row，啟動分級輪詢
- [ ] 5.2 改 `services/polling.py`：以 `tracked_posts.polling_tier` 為驅動，沿用 tier_for_age（0–24h: 15min / 1–7d: 1h / 7–30d: 6h）
- [ ] 5.3 寫 `related_posts` 偵測 — `author_followup`：`redditor.submissions.new(limit=20)` 比對，Haiku 判斷與原事件相關性
- [ ] 5.4 寫 `related_posts` 偵測 — `author_reply`：`submission.comments.list()` 過濾 `comment.author == submission.author`
- [ ] 5.5 寫 `related_posts` 偵測 — `hot_reply`：comment.score > 50 或比第二名 top reply 高 30%
- [ ] 5.6 寫 `related_posts` 偵測 — `crosspost`：`submission.duplicates()`，整批寫入
- [ ] 5.7 寫 `services/detection.py::evaluate_milestone`：用 Haiku 判定 `is_milestone`
- [ ] 5.8 後續推送邏輯：日常更新加進每日彙整、`is_milestone=true` 即時推送
- [ ] 5.9 新增 bot 指令：`/saved` 列收藏、`/timeline <id>` 看時間軸
- [ ] 5.10 端到端測：fake 收藏 → 餵假後續資料 → 確認推送觸發

---

## M6 — 問答層

**前置**：M5 tracked_posts + related_posts 有資料
**完成判準**：`/ask <id>` 進入問答模式、多輪對話、`/exit` 或 5 分鐘 idle timeout 離開、token 成本實測過

- [ ] 6.1 寫 `services/qa.py`：session 狀態管理（每使用者同時只能一個 active session，記憶體 dict 即可）
- [ ] 6.2 寫 context 組裝器：原貼文 + 最新 EvolutionSummary + 完整 comment tree（含巢狀層級標註）+ 作者近 30 篇 + related_posts（含 crosspost）
- [ ] 6.3 `bot/handlers.py` 新增 `/ask <id>` handler：建 qa_sessions row、組 system prompt（開 Opus prompt cache）、回 ready prompt
- [ ] 6.4 改 message handler：active session 中所有非指令訊息走 Opus 多輪對話
- [ ] 6.5 寫 `/exit` handler + 5 分鐘 idle timeout（背景 task 掃 qa_sessions.started_at）
- [ ] 6.6 qa_messages 寫入：每輪 user / assistant 各一筆，連同 `cost_usd` 記到 llm_records
- [ ] 6.7 token 實測：跑 5 個真實事件 × 3 輪問答，記錄 input / output / cache hit 比例與成本到 `docs/m6_token_baseline.md`
- [ ] 6.8 unit test：session 狀態機（開 → 訊息 → exit / timeout）+ context 組裝器（mock data）

---

## M7 — 評估與調優

**前置**：M6 完整流水線可跑、系統累積至少 7 天真實資料
**完成判準**：產出收藏率 / 後續命中率數字、30 組問答自評結果、調過至少一輪 prompt / 閾值

- [ ] 7.1 寫 `scripts/eval_collection_rate.py`：`SUM(feedback.collect) / SUM(daily_pushes)`，依 push_type 分組
- [ ] 7.2 寫 `scripts/eval_followup_hit.py`：30 天內 `related_posts ≥ 1` 的 tracked_posts 比例
- [ ] 7.3 寫 `scripts/eval_lang_breakdown.py`：中英 subreddit 的收藏率對照（v4 新增分析）
- [ ] 7.4 寫 `scripts/eval_relation_dist.py`：四類 related_posts 的分布（crosspost 比例是 v4 賣點）
- [ ] 7.5 系統連續 7 天無人工介入運行，蒐集真實資料
- [ ] 7.6 分析「被 👎 / 🔕 的 candidate」共同特徵，調 Haiku 評分 prompt
- [ ] 7.7 分析 `subreddit_sources.total_collected = 0` 的 sub 與 `keyword_seeds.total_collected = 0` 的詞，標 `enabled=false`
- [ ] 7.8 抽 30 組 (問題, 回答) pair，研究者自評三項：事實正確性 / 引用精準度 / 幻覺有無
- [ ] 7.9 成本對帳：實際 llm_records.cost_usd 月總和 vs 企劃書 §八 預估，差異寫進報告

---

## M8 — 報告與 demo

**前置**：M7 評估數據完整
**完成判準**：報告交付、demo 影片產出、GitHub 整理乾淨

- [ ] 8.1 撰寫報告 Ch1–3（動機 / 目標 / 系統架構）— 直接從 v4 企劃書改寫
- [ ] 8.2 撰寫報告 Ch4–5（核心功能 / DB schema）
- [ ] 8.3 撰寫報告 Ch6（評估結果）— 灌 M7 數據 + 中英對照 + 四類 related 分布
- [ ] 8.4 撰寫報告 Ch7 案例分析：挑 3–5 個從推送 → 收藏 → 完整生命週期事件，附時間軸圖（至少 1 個含 crosspost 延伸）
- [ ] 8.5 撰寫報告 Ch8 倫理章節（隱私 / 去識別化 / 資料刪除 / Reddit API ToS）
- [ ] 8.6 錄 5 分鐘 demo 影片：推送 → 收藏 → 後續觸發 → 問答
- [ ] 8.7 整理 GitHub README、清理 dev 殘留檔、確認 `.env.example` 完整
- [ ] 8.8 製作口頭簡報 slides（10–15 頁）

---

## 里程碑風險檢查點

| 時點 | 檢查 | 觸發條件 |
|------|------|---------|
| M1 完成 | Reddit API 可用、額度足夠 | NO-GO（API 政策變、申請被拒）→ 退化方案：使用者主動貼 Reddit URL 單篇追蹤模式 |
| M2 累積 ≥ 200 candidate | 中英文比例 | 中文 < 20% → 加 r/translator、r/China_irl 或調 keyword seeds |
| M3 完成 | Haiku 與人工標記準確率 | < 60% → 補一輪 prompt 調整再進 M4 |
| M4 完成 | Telegram bot 真的能推送 | 推不出 → 卡住一切後續，優先除錯 |
| M6 完成 | 問答 token 成本 | 單次 > $0.5（v3 估 $0.15 但 Reddit context 較肥）→ 強制降中量 context 為預設 |
| M7 完成 | 收藏率 | < 15% → 報告誠實寫，分析原因（評分 vs 使用者口味 vs 中英文化差異）|
