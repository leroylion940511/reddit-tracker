# Reddit Tracker — 專案進度（現為 v2.0 AI 綜合日報）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 現行企劃見 `docs/AI_NEWS_COMPANY_PROPOSAL.md`、規格入口見 `docs/v5/README.md`。
> 2026-10-27 以前的段落是 v4／v5 歷史紀錄，裡面提到的 bot、scrapers、services、v5 newsroom 模組都已移除。

**Last updated:** 2026-10-27（日報撰稿改用 Codex）

## 目前狀態（2026-10-27 起）

- **線上只跑 v2.0 綜合日報。** LaunchAgent 只剩 `newsroom`（`reddit_tracker.newsroom.scheduler`：收集＋聚合每 15 分鐘、06:00 準備、08:35 發 Telegram）與 `rsshub`。
- **程式結構：** `collection/`（收集、聚合、報表）、`daily/`（評分、撰稿、渲染、發行）、`llm/{codex,gemini}.py`、`newsroom/{scheduler,deploy}.py`、`web.py`（只看日報）、`seeds/news_sources.*`、`scripts/probe_news_sources.py`。
- **驗收：** 收集七天驗收 10/27–11/02，11/03 用 `uv run python -m reddit_tracker.collection report --days 7 --out docs/collection_acceptance_2026-11-03.md` 出報告；11/30 交付。
- ✅ 10/27 首期正常發行：42 則（Gemini 40／模板 2，12 次 request），Telegram message 499、500。
- ⚠️ 首期觀察到的問題（使用者決定先多跑幾天再修）：① 同事件重複見報——巴西大選 cluster 472／453、塞爾維亞 405／410，`find_same_events` 一次丟整個候選池漏併；② 模板稿照搬英文原標題（Vucic）；③ 柯米起訴被投到財經版（cluster 2154）；④ 社群版有無內容稿、科學版單篇 arXiv、文化版三則都是金鐘；⑤ 數據欄停在 10/22——證交所 OpenAPI `MI_INDEX` 本身落後，非程式錯。建議修正順序 1→2→5→3→4。
- ➡️ **下一步：** 再觀察幾期，看上述問題是否每期都出現，再一起修。

## 本次變更（2026-10-29 — 執行手冊步驟 0–3.7，`mas-handbook` 分支）

- ✅ 老師的執行手冊 `docs/HANDBOOK_2026-10-28.md` 在 `mas-handbook` worktree 實作，強制指令與逐步狀態見 `docs/HANDBOOK_ADAPTATION.md`。
- ✅ 步驟 0：唯讀母本 `data/snapshots/2026-10-27.db`、tag `baseline-pipeline`（42a3cf5）、`scripts/export_1027_fixtures.py` 匯出 `tests/regression/fixtures/1027_{groups,merges,meta}.json`、`.gitignore` 補 `annotation/`、第一份週報 `docs/weekly/2026-11-03.md`。
- ✅ E01 查證：美式足球稿（source_item 1053）原在英文 NFL cluster 403，是 `find_same_events` 的 `[403, 410]` 錯併進塞爾維亞 cluster 410；英文塞爾維亞 405 反而漏併（E07）。
- ⚠️ 母本內容涵蓋到 10/29；凡是重現 10/27 都要以 `first_seen_at ≤ 2026-10-26 22:00 UTC` 截止。
- ✅ 步驟 1：`LEGACY_JOBS_ENABLED`（預設 false，true 也不復活舊 job）；`llm/quota.py` 依 model 計數額度（`LLM_DAILY_LIMIT=60`，所有用途共用，每次嘗試含重試扣一格），Codex／Gemini 重試 1、`WRITE_ATTEMPTS=2`；24 個社群來源停用，停用來源的舊素材不進聚合／選題／證據包（10/27 複本重現：E13 不再入選）；`DAILY_WRITER` 只允許 codex／gemini／template／fake；非 MVP 版空版印「本版未開放」。詳見 ADAPTATION。
- ⚠️ 部署注意（尚未部署，`mas-handbook` 未併 main）：設定鍵改名 `GEMINI_DAILY_LIMIT`→`LLM_DAILY_LIMIT`、state 檔改 `/tmp/reddit-tracker-llm-quota.json`；Codex 呼叫也開始受每日 60 次本機上限。
- ✅ 步驟 2：回歸集 `tests/regression/cases/E01–E16.json`（15 個錯誤案例＋E09 非錯誤），runner 用離線 fixture `1027_items.json.xz` 在 tmp SQLite 照線上聚合時間表逐輪重編 10/27，`find_same_events` 用 `1027_merges.json` 重播、撰稿走 `llm/replay.py`（request_hash，找不到就失敗）；全域防護擋 codex subprocess 與 Gemini HTTP。現況 E13 通過、15 個條件 strict xfail。全套 148 passed／1 skipped／15 xfailed。
- ⚠️ 文字類案例（E03–E05 正文、E08、E11、E12、E16）要有錄好的回應才能拿掉 xfail：修完後先在 `data/work` 複本用 Codex 錄一次並匯出 `tests/regression/fixtures/1027_llm_records.json`。到期日當天還掛 xfail，`test_overdue_cases_are_not_xfail` 會失敗。
- ✅ 步驟 3 第 1–4 點：共同實體檢查（`collection/entities.py`）＋兩段門檻（≥0.45 要 1 個、0.28–0.45 要 2 個，設定值 `CLUSTER_*`）＋譯名表 `seeds/name_glossary.yaml`（50 筆，中央社譯名，只收 10/30 前出現過的名字，撰稿與合併共用）＋常見字清單 `seeds/entity_common_words.yaml`；編輯會議改由 `daily/desk.py` 用譯名表＋共同實體做跨語言合併，`find_same_events` 降為第二意見、說合併也要程式確認有共同實體。回歸集 E01、E02、E03、E04、E06、E07 拿掉 xfail 並通過（E07 換了錨點標題，見 ADAPTATION）。全套 182 passed／4 skipped／6 xfailed。
- ⚠️ 聚合變嚴格：10/27 重編事件數 2,539 → 2,822、≥2 家出處 264 → 220；英文 Title Case 標題與只共有一個名字的中段配對會被拆開（刻意，11/07 dev 標註後重調）。`cluster_recent_items(threshold=)` 改為 `rules=`／`lexicon=`；`apply_merges` 修正重疊組遺失事件的 bug。
- ✅ 步驟 3 第 5–7 點：`build_evidence` 相關性過濾（與代表標題無共同實體就剔除，記進 `review_notes`）；轉載辨識（指紋去開頭 `[..]`／`【..】`、`recompute_duplicates`、`mark_reprints`、`outlet_count` 排除重複稿與轉載、來源列「中央社（中央廣播電台轉載）」）；arXiv 預印本措辭、數據欄「資料更新延遲」、單一來源警語改由程式 `finalize_story` 加在文末（提示詞第 4 條刪除）。E10、E15 拿掉 xfail；E12、E16 規則用單元測試驗證，文字條件等錄音。全套 202 passed／4 skipped／4 xfailed。詳見 ADAPTATION。
- ⚠️ 轉載不算多來源後，10/27 重編 ≥2 家出處事件 222 → 156（主要是排除重複稿）；相似度轉載只套中文標題（英文獨立報導標題常 >0.8）。數據欄交易日只排除週末，連假後會多標一次延遲。
- ✅ 步驟 3 第 8 點（10/30）：`scripts/rebuild_1027.py` 在 `data/work/1027_rebuild.db` 重聚＋重編 10/27（39 則，Codex 38／模板 1）；`run.py prepare --now ISO [--recluster]`；`scripts/compare_1027.py` → `docs/weekly/1027_compare.md`（週報已連結）。真 Codex 16 次（上限 60），每次嘗試記進複本 `llm_records`（`scripts/llm_recorder.py`，不動 models／migration）；錄音 `tests/regression/fixtures/1027_llm_records.json`（16 筆、67 KB）。步驟 3 四項標準全過；全套 213 passed／4 skipped／1 xfailed（E14）。
- ⚠️ 錄音只對當下的提示詞與證據包有效：改到撰稿提示、譯名表、證據包就要重跑 `scripts/record_regression_1027.py`（會呼叫 Codex，`LLM_QUOTA_STATE_PATH` 腳本已指到 `data/work`）。E03／E05 正文、E12 在重編版沒見報，回歸是 skip；E12 由 `tests/test_step3_rules.py` 把關。
- ➡️ 下一步：步驟 4（併版與配額，E14 11/15 到期）；E11 等步驟 9 文稿編輯。

## 本次變更（2026-10-27 — 日報撰稿改用 Codex）

- ✅ 撰稿 provider 改為 Codex CLI（`reddit_tracker/llm/codex.py`）：subprocess 呼叫 ChatGPT.app 內建的 `codex exec`，吃本機 ChatGPT 訂閱登入，模型 `gpt-6.1-sol`／reasoning low。`DAILY_WRITER` 預設 `codex`，`gemini`、`template` 仍可切；找不到 codex binary 整期退模板稿。`GeminiDailyWriter` → `DailyWriter(name)`；stats 鍵改 `ai_articles`／`llm_requests`（render 相容 10/27 舊鍵）。
- ✅ 安全：空暫存目錄＋read-only sandbox＋忽略使用者 config／rules，關掉 shell／code mode／子 agent 等工具（實測叫它讀 `/etc/hosts` 失敗），輸出含本機機密就丟棄。
- ✅ production DB 複本試編 10/28：42 則（Codex 39／模板 3，模板都是數字關卡擋下），12 次請求、約 6 分鐘，合併 4 組重複事件。全套 59 passed。
- ⚠️ 每次呼叫固定約 16k input tokens 的 agent 開銷，與使用者互動用 Codex 共用額度；ChatGPT.app 更新會換 CLI 版本（alpha），若新增工具類 feature 要補進 `_DISABLED_FEATURES`。
- ➡️ 10/28 06:00 是第一期 Codex 撰稿，看 `newsroom.log` 的 `codex completion` 行與 `daily_articles.review_notes`。首期觀察到的 5 個問題（重複見報、英文標題等）要以 Codex 版重新觀察。

## 本次變更（2026-10-27 — 精簡為綜合日報）

- ✅ 依使用者決定移除 v4 全部程式（Reddit scrapers、評分、Top-5 推送、收藏追蹤、偵測、問答、Telegram bot 指令與 `fb:` 按鈕）以及 v5 Reddit 早報（候選探索、編採 agent、05:30／08:30 排程、`nr:` 回饋按鈕）。v2.0 日報本來就不依賴這些：收集層只抓 rss／rsshub，發行直接用 `telegram.Bot` 送到 `TELEGRAM_CHAT_ID`。
- ✅ `newsroom/scheduler.py` 只註冊 `newsroom_source_collection`、`daily_prepare_edition`、`daily_publish_edition`；`_PollingBackgroundScheduler` 從已刪的 v4 `scheduler.py` 移過來。`llm/gemini.py` 只留 `GeminiClient`。`web.py` 只剩 `/daily/` 檢視器。`config.py` 刪掉 38 個沒在用的設定（`.env` 裡的舊鍵會被忽略）。拿掉 `anthropic`、`praw`、`websocket-client` 依賴。刪掉 m1–m7／eval 腳本與對應測試；全套 55 passed。
- ✅ 線上：`legacy-uninstall` 停掉並移除 bot 與 v4 scheduler 的 LaunchAgent；`newsroom-reload` 後 log 確認只有上述三個 job。
- ℹ️ DB models、資料表與 Alembic migration 都不動（不寫 drop migration）。舊程式碼查 commit `ff15181` 或更早。

## 本次變更（2026-10-27 — 遊戲新聞來源）

- ✅ 登錄表新增 `gnn-gamer`（巴哈姆特 GNN）、`4gamers`（4Gamers），原生 RSS，放在 `culture`（文化娛樂），不另開板塊。probe 兩者皆 OK（30／50 筆）。線上 newsroom 每輪 tick 重讀登錄表，不需重載。
- ⚠️ 兩者在驗收期間中途加入，七天報告裡的筆數不滿七天；若遊戲稿擠占文化版配額，再考慮獨立板塊。

## 本次變更（2026-10-26 深夜 — 綜合日報上線試刊）

- ✅ 規格 [DAILY_EDITION.md](docs/v5/DAILY_EDITION.md)；新套件 `reddit_tracker/daily/`：`scoring.py`（程式評分、報導類型 report／single_source／social、選題時依登錄表重新投票板塊、頭版 6 則每版最多 2、各版配額寧缺勿濫）、`evidence.py`（每事件最多 6 家出處、至少保留一篇中文）、`writer.py`（Gemini 編輯會議合併跨語言同一事件＋每版一次撰稿、數字核對審稿關卡、模板稿後備）、`market.py`（證交所指數）、`render.py`（自含 HTML 報紙＋Telegram 精選）、`run.py`（LLM 呼叫不在 DB 交易內、冪等、發行失敗標 `delivery_failed` 不重送）。
- ✅ migration `a6c9e2f31d84`：`daily_editions`、`daily_articles`。設定：`DAILY_EDITION_ENABLED`、06:00 準備、08:35 發行（與 v5 08:30 錯開）、`GEMINI_DAILY_LIMIT=60`（太平洋時間換日）。控制台新路由 `/daily/`、`/daily/{date}`；產出在 `site/daily/`（不進版控）。
- ✅ 在 production DB 複本試編 10/27 一期：42 則（頭版 6），Gemini 37、模板 5，合併 8 組重複事件。全套 366 passed。
- ⚠️ 已知限制：只用標題＋摘要撰稿（未讀全文）；匯率／天氣數據欄未接（登錄表停用）；Gemini 免費層偶爾 503 或格式錯，靠重試與模板稿兜底。
- ✅ 已部署（commit `84b6c5a`）：`newsroom-deploy` 備份後升至 `a6c9e2f31d84`，`.env` 設 `DAILY_EDITION_ENABLED=true` 並重載；`daily_prepare_edition`／`daily_publish_edition` 已註冊。刻意未在 production 試編（會佔用 10/27 版次或把事件標為已刊登）。今晚測試已用 Gemini daily 額度 40/60（太平洋時間 10/26），06:00 那期在同一額度日，約需 12–16 次。
- ➡️ 試刊：10/27 06:00 首期準備、08:35 發 Telegram（文字精選＋完整 HTML 檔）。每天看報紙內容與 `daily_articles.review_notes`；11/13 Reddit RSS 停止後，社群觀察版仍有 PTT／Threads。

## 本次變更（2026-10-26 22:53 — 事件聚合上線）

- ✅ 依使用者同意：commit `4eee6b9` → `newsroom-deploy`（備份 `reddit_tracker.backup-20261026-225347.db`）→ Alembic 升至 `f4b2d8e61c07` → 只重載 newsroom。bot、rsshub 未動。
- ✅ 線上首輪聚合 22:53：2,436 篇 → 2,009 個事件（176 個 ≥2 家出處、58 個 ≥3 家），與複本試跑一致。4,525 篇中 2,637 篇已歸事件；其餘 1,888 篇是首日回補、超出 72 小時窗的舊稿，依規格不聚合。
- ℹ️ 22:53 那輪 `sources=0` 是正常的（22:43 剛抓過，未到 60 分鐘間隔）；第一輪「新素材＋增量聚合」約在 23:53 的 tick。科學與健康版事件多為單篇 arXiv，屬預期。
- ➡️ 下一步：程式評分（獨立出處數、層級、時效、升溫）與各版選題；驗收期間每天看 `report --days 1` 與 `clusters --top 30`。

## 本次變更（2026-10-26 — 事件聚合）

- ✅ 規格 [CLUSTERING.md](docs/v5/CLUSTERING.md)；實作 `reddit_tracker/collection/clustering.py`：TF-IDF（中文字元 bigram、英文單字、zhconv 簡轉繁、去網址／電頭樣板）＋餘弦相似度增量指派，門檻 0.28＋事件重心 0.20 防串錯；只在同語言群組、發布時間差 48 小時內合併；既有歸屬不變。
- ✅ 新 migration `f4b2d8e61c07`：`story_clusters` 表、`source_items.cluster_id`。事件訊號由程式算：`outlet_count`（可註冊網域、中央社轉載歸中央社、社群不計）、T1／T2／T4 數、首末發布時間、代表標題（層級高者優先）、板塊（綜合 feed 不投票）。
- ✅ 登錄表加 `general_feed`（14 個綜合 feed）；新依賴 `zhconv`。CLI：`python -m reddit_tracker.collection cluster`／`clusters --top 30`。排程：收集後立即聚合（獨立 commit）。
- ✅ production DB 複本：2,436 篇 → 2,009 個事件，176 個 ≥2 家出處、58 個 ≥3 家；約 1 秒；重跑無變動。抽查最大事件皆正確。全套 354 passed。
- ⚠️ 未部署：production 仍在 `e3a7c1f09b52`。部署需再跑 `newsroom-deploy`（備份→migration→重載 newsroom）。跨語言合併（中英文同事件）尚未做，留給選題階段 LLM。
- ➡️ 下一步：部署聚合 → 程式評分（獨立出處數、層級、時效、升溫）與各版選題。

## 本次變更（2026-10-26 22:42 — 收集層上線）

- ✅ 依使用者同意：commit `9ada3af` → `newsroom-deploy`（備份 `reddit_tracker.backup-20261026-224201.db`，integrity ok）→ Alembic 升至 `e3a7c1f09b52` → 只重載 newsroom；之後 `.env` 加 `NEWS_COLLECTION_ENABLED=true` 並 `newsroom-reload`。bot、rsshub 未動，v4 scheduler 仍 disabled。
- ✅ 線上 `newsroom_source_collection` 已註冊（每 15 分鐘 tick），首輪 22:43：107 個來源 106 成功（cw-today 503）、新增 4,525 筆、唯一 4,290 筆。Reddit 候選收集、05:30 編採、08:30 發報不受影響。
- ⚠️ 10/26 是首日回補，不計入驗收。**七天收集驗收期間：10/27–11/02（Asia/Taipei）**，11/03 用 `uv run python -m reddit_tracker.collection report --days 7 --out docs/collection_acceptance_2026-11-03.md` 出報告，對照企劃附錄 B 門檻。比原企劃（10/29–11/04）提早兩天。
- ℹ️ 重載時 log 會出現 `SystemExit: 0` 的 threading Traceback，是舊 process 在 signal handler 中 `sys.exit` 的關機雜訊，部署前就存在，不影響運作。
- ➡️ 下一步：驗收期間做事件聚合（跨媒體同一事件），並每天看一次報表的來源健康。

**更早（同日）：** 收集層完成並在 DB 複本試跑

## 本次變更（2026-10-26 — 多來源收集層）

- ✅ 重開機後確認 newsroom／bot／rsshub 自動恢復（rsshub 只綁 127.0.0.1:1200），v4 scheduler 維持 disabled。
- ✅ 收集層 `reddit_tracker/collection/`：`normalize.py`（網址正規化、標題指紋、發布時間判斷）、`collector.py`（到期判斷、8 thread 抓取、ETag／Last-Modified、單一 writer 寫入、去重、失敗也記健康紀錄）、`report.py`（七天驗收報表）、CLI `python -m reddit_tracker.collection run|report`。規格：[COLLECTION.md](docs/v5/COLLECTION.md)。
- ✅ 新 migration `e3a7c1f09b52`：`source_items`、`source_fetch_runs`。登錄表加 `time_offset_hours`（三立 -8），逐篇抓全文的 RSSHub 路由調為 120–240 分鐘一次（天下被 429）。
- ✅ newsroom scheduler 新增 `newsroom_source_collection`（每 15 分鐘 tick），**只有 `NEWS_COLLECTION_ENABLED=true` 才註冊，預設關閉**。
- ✅ 在 production DB 複本試跑：首輪 106/107 成功、新增 4,525 筆（重複 233）約 100 秒；立即重抓只新增 20 筆、23 個來源回 304、無重複寫入。全套 347 passed。
- ⚠️ 未部署：production DB 仍在 `d68a592f6d22`，`.env` 未開啟收集。部署需 `deploy/install_launchd.sh newsroom-deploy`（備份→migration→只重載 newsroom）＋ `.env` 設 `NEWS_COLLECTION_ENABLED=true`，需使用者同意。
- ⚠️ 首次啟用當天會回補大量舊稿（央行一次 500 筆），七天驗收從啟用後第一個完整日起算。標題去重必須搭配發布時間相近（機關會重用同一標題）。
- ➡️ 下一步：使用者同意後部署並啟用收集 → 開始七天收集驗收 → 同時做事件聚合（跨媒體同一事件）。

## 本次變更（2026-10-26 — 來源登錄表與 RSSHub 探測）

- ✅ 新增 [來源登錄表](reddit_tracker/seeds/news_sources.yaml)：156 個來源、11 個板塊，啟用 127 個；格式與介面見 [SOURCE_REGISTRY.md](docs/v5/SOURCE_REGISTRY.md)。loader `reddit_tracker/seeds/news_sources.py`，新增依賴 `pyyaml`、`feedparser`，`config.py` 加 `rsshub_base_url`／`rsshub_access_key`／`news_sources_path`。
- ✅ RSSHub 裝在 `~/rsshub`（`fb2ce11`），只綁 127.0.0.1:1200、需 ACCESS_KEY（存在 `~/rsshub/.env` 與專案 `.env` 的 `RSSHUB_ACCESS_KEY`）。Homebrew Node 26 可跑（官方標 22／24）；pnpm 需用 `npx -y pnpm@12.15.0`（全域 pnpm 10 切版本會失敗）；啟動必須 `NODE_ENV=production`。
- ✅ `scripts/probe_news_sources.py` 實測：非 Reddit 啟用來源 109/110 成功（cw-today 間歇 503），單次快照 5,386 筆、24h 內 2,054 筆。報告：[docs/sources_probe_2026-10-26.md](docs/sources_probe_2026-10-26.md)。新增 `tests/test_news_sources.py`，全套 329 passed。
- ✅ 依使用者同意，RSSHub 已加入 launchd：`com.leroy.reddit-tracker.rsshub`（`deploy/install_launchd.sh rsshub-install`／`rsshub-uninstall`），已確認只 LISTEN 127.0.0.1:1200、無 key 回 403、被 kill 後 21 秒自動重啟、探測經 launchd 版 RSSHub 成功。log：`~/rsshub/rsshub.log`。
- ⚠️ Gotchas：Reddit RSS 對探測限速很嚴（7–30 秒間隔仍 429），探測 Reddit 會搶線上 newsroom 額度，改用 DB 佐證；聯合新聞網每則 pubDate 都是 1970（要用首次取得時間代替）；三立時區偏 +8h。
- ✅ 已修正 `.venv/bin` 內 15 個 entry script／activate 檔仍指向搬家前 `~/Documents/Developer/Project/reddit_tracker` 的路徑（只改文字，不重建 venv，不影響線上服務）；`.venv/bin/pytest`、`uv run pytest`、`.venv/bin/alembic` 皆可直接執行，329 passed。之後若再搬專案，用 `rm -rf .venv && uv sync` 重建。
- ℹ️ 2026-10-26 使用者準備重開機。預期登入後 newsroom／bot／rsshub 自動恢復（皆 enabled），v4 scheduler 維持 disabled；重開機後先跑 `deploy/install_launchd.sh status` 確認。
- ➡️ 下一步：收集層（`source_items` migration、通用 RSS 收集器、去重、來源健康紀錄）→ 10/29 開始七天收集驗收。

**2026-10-26 稍早：** 企劃改為多來源綜合日報 v2.0

## 本次變更（2026-10-26 — 企劃轉向多來源綜合日報）

- ✅ [AI 新聞公司企劃書](docs/AI_NEWS_COMPANY_PROPOSAL.md) 改版為 v2.0：從 Reddit-only 社群報改為多來源綜合日報（頭版＋10 版＋數據欄），來源分 T1 官方／T2 媒體／T3 專業資料／T4 社群四層；Reddit 降為社群觀察版來源之一。
- ✅ 參考 intel-radar（程式計分、雙訊號分級、預算上限、冪等補跑、靜態日報）與 RSSHub（本機自架、只綁 127.0.0.1、作為無原生 RSS 網站的第二順位管道）。已用 GitHub 原始碼確認 RSSHub 有 cna／pts／ltn／udn／twreporter／cw／storm 等台灣媒體路由，但**沒有 Reddit 路由**；需 Node 22/24 + pnpm。
- ⚠️ v1.1 排定的 10/15–10/21 第三方 Reddit 供應商驗收**未執行**（未建帳號）；候選仍只靠 Reddit RSS（15 個 subreddit，每日約 1,300–1,600 篇），11/13 RSS 停止後 Reddit 斷料。v5 日報仍每天 08:30 發 8 則。
- ⚠️ 僅改文件；未改程式、schema、排程或 production。新企劃待教授確認後才更新 `docs/v5/` 實作契約。
- ➡️ 下一步：建立來源登錄表（YAML，首批 120+ 來源）並本機架設 RSSHub，逐一實測可用性；10/29 起收集層（`source_items`、去重、事件聚合、來源健康）與七天收集驗收。時程：11/12 前不依賴 Reddit 完成端到端出刊、11/13–11/19 七天試刊、11/30 交付。

## 本次變更（2026-10-14 — 資料取得與交付驗收規劃）

- ✅ [AI 新聞公司企劃書](docs/AI_NEWS_COMPANY_PROPOSAL.md) 更新至 v1.1：Reddit 優先，RSS 僅為過渡管道；加入 ScrapeCreators／Apify 與 X／Threads 備選、資料量與費用假設、七天資料驗收、停用 RSS 的端到端最終測試。
- ✅ 排定計畫決策點：10/15–10/21 預定資料驗收、10/22 選型、11/06–11/10 無 RSS 連續測試、11/12 最終驗收、11/30 前交付；帳號或測試未就緒須重排並揭露影響，不得算成通過。
- ⚠️ 使用者確認尚未建立供應商帳號，先完成企劃與測試安排。沒有開始供應商實測、購買額度、建立自動排程或變更 production；價格文件與本機憑證存在性檢查不等於資料取得驗收。
- ➡️ 當前優先下一步：準備測試帳號／金鑰與額度，先做小樣本，再完成七天資料驗收；通過後擴建三版示範與七版產品。X／Threads 仍為備選，未納入正式素材範圍。

## 本次變更（2026-10-14 — AI 新聞公司企劃討論稿）

- ✅ 依教授對內容過於 raw data、需要完整新聞板塊的回饋，新增 [AI 新聞公司企劃書](docs/AI_NEWS_COMPANY_PROPOSAL.md)，以非技術說明呈現七大板塊、編採流程、AI／人工分工、讀者體驗與品質驗收。
- ✅ 文件清楚區分現有 v5 基礎與提案中的能力，並以虛構事件說明線索如何轉為完整報導；本次僅更新文件，未變更程式、production 資料或服務。
- ➡️ 下一步：與教授討論企劃，優先確認報導深度與產品方向，再製作台灣、國際、科技三版的示範報紙。新企劃尚未取代既有 v5 實作契約。

## 本次變更（2026-09-30 — 重開機後恢復）

- ✅ 已確認 launchd 自動恢復 v5 `com.leroy.reddit-tracker.newsroom` 與 Telegram callback receiver `com.leroy.reddit-tracker.bot`；兩者皆為 `running`，舊 v4 scheduler 維持 disabled。
- ✅ 已啟動本機 FastAPI 控制台，僅綁定 `127.0.0.1:8765`；`GET /` 回傳 HTTP 200。

## 本次變更（2026-09-25 — Telegram 回饋 receiver 上線）

- ✅ 已依使用者明確授權啟用並 bootstrap `com.leroy.reddit-tracker.bot`，只恢復 Telegram long-polling callback／指令接收；舊 v4 scheduler 仍 disabled，不會恢復 09:00 Top-5 或其他舊排程。
- ✅ 啟動前已確認 Telegram token／chat 設定與已安裝 plist 均就緒，且沒有既有 bot process；啟動後 launchd 為 `running`（PID 13036）、Python child 為 PID 13038、首次執行尚未退出，`bot.log` 已更新。
- ✅ Telegram 每篇報紙的 ❤️／🚫／👀 現可寫入既有 `reader_feedback` ledger；handler 仍會確認 chat 屬於該 reader、冪等記錄並移除已處理按鈕。網頁回饋維持可用。

## 本次變更（2026-09-25 — 試刊 Gate 固化與日常運作交接）

- ✅ 控制台的試刊判定改為掃描歷史中任一段連續 7 天的「已發行、8–10 則、每則有來源」版次；一旦通過，通過日期區間會保留，不會在原始試刊週滑出「最近七天」後錯誤退回未通過。
- ✅ 同一面板仍顯示近七日的發行、版面與來源完整度，讓歷史 launch gate 與目前營運健康分開判讀。
- ✅ 根 README 與 v5 README／roadmap／架構／demo 文件已改為「試刊完成、日常運作中」；Telegram callback receiver 的啟用仍需使用者另行明確授權。
- ✅ 新增 dashboard regression test：在 9/19–9/25 通過後，以 9/26 的滾動視窗查詢仍保有歷史通過結果；沒有操作 production DB、launchd 或 Telegram。

## 本次變更（2026-09-25 — 七日試刊驗收完成）

- ✅ 2026-09-19 至 2026-09-25 連續 7 天皆於 08:30 實際發行（edition 2–8）；每期都是 8 則、8/8 項目具來源、各有 10 個 source bridge，Telegram 均成功投遞 9 則訊息。
- ✅ 期間的 Gemini 缺欄／額外欄位與 RSS 單次 403／斷線都由既有安全 fallback 或後續輪次復原；沒有造成漏刊、重複投遞或來源不完整。最新 24 小時有 1,488 則候選、14 個 source。
- ✅ 最終驗收：production SQLite `PRAGMA integrity_check` → `ok`；newsroom launchd running（PID 44476），舊 v4 scheduler／Bot 仍 disabled；`uv run --group dev python -m pytest -q` → **319 passed**（既有 FastAPI TestClient deprecation warning 1 則），Ruff 與 `git diff --check` 通過。
- ✅ 七日監測 automation 已結束；日常新聞室仍照原排程運作（候選 discovery 90 分鐘、05:30 編採、08:30 發行）。Telegram callback receiver 仍維持 disabled，網頁回饋可用；若要讓 Telegram ❤️／🚫／👀 寫入回饋，仍需使用者明確授權單獨啟用 Bot receiver。

## 本次變更（2026-09-21 — 七日試刊第 3 天）

- ✅ 第 4 期於 05:30 編採、08:30 發行成功：8 則項目、10 個來源 bridge、9 則 Telegram 訊息；edition status 為 `published`，全部項目都有來源。RSS 發行前輪次完成 15 個 source，最近 24 小時新增 1,510 則候選、涵蓋 14 個 source。
- ✅ 發現前次 Gemini 欄位容錯修正過度嚴格：模型額外輸出未使用的 `debt_zh` 欄位會讓整期改走模板 fallback。已恢復忽略非契約額外欄位；模型仍不能改動由程式持有的 kind、來源、信心與 warnings，且缺失必要欄位仍會逐則以安全模板補齊。
- ✅ 新增 extra-field regression test，完整 `uv run --group dev python -m pytest -q` → **319 passed**（既有 FastAPI TestClient deprecation warning 1 則）；Ruff 與 `git diff --check` 通過。已用 `deploy/install_launchd.sh newsroom-reload` 套用至 production，僅 v5 newsroom 重載並確認 PID 44476 running。

## 本次變更（2026-09-19 — 七日試刊第 1 天）

- ✅ 05:30 成功完成第 2 期編採，08:30 已發行至 Telegram：8 則項目、10 個來源 bridge、9 則 Telegram 訊息；edition status 為 `published`，所有 8 則均有來源。
- ✅ RSS 候選擷取持續正常：發行前最近一輪完成 15 個 source，沒有 429；最近 24 小時累積 1,435 則候選、涵蓋 14 個 source。
- ✅ Gemini 本期輸出有 2 個必填稿件欄位遺漏，既有機制已安全以 source-transparent template 完整 fallback，因此未漏刊；現在改為逐則、逐欄位補齊，保留 Gemini 已通過驗證的內容，並在 writing artifact 記錄 `template_fallback_positions`，避免未來因單一缺欄讓整期退化為模板稿。
- ✅ 驗證：Gemini writer／writing 定向測試、Ruff、`git diff --check` 通過；完整 `uv run --group dev python -m pytest -q` → **318 passed**（既有 FastAPI TestClient deprecation warning 1 則）。
- ✅ 已執行 `deploy/install_launchd.sh newsroom-reload` 將無 schema 的 writer 修正套用到 production；僅 v5 newsroom 被重載，確認 `com.leroy.reddit-tracker.newsroom` 以 PID 13153 running，v4 scheduler／Bot 維持 disabled。

## 本次變更（2026-09-18 — v5 可運作編採鏈路與控制台）

- ✅ 找到 9/18 漏刊根因：v4 scheduler 停用後沒有任何 job 繼續擷取候選；9/17 台灣日曆窗口為 0 筆，選題 agent 因來源不足正確拒絕出刊。
- ✅ v5 newsroom scheduler 現在啟動時會先跑一輪、之後每 90 分鐘只跑 subreddit candidate discovery；不會啟動 v4 scoring、Top-5、追蹤或 Telegram 發送工作。
- ✅ 編採與發行拆成兩個 v5 jobs：05:30 先製作可檢閱 draft，08:30 才做冪等 Telegram 發行；避免把 Gemini 寫稿延遲或選題失敗壓在發送時刻。
- ✅ 可選早報快訊已接入：只檢視 edition 當日凌晨後的候選，且必須同時達到初始 score 150／留言 25 的保守門檻；會保留來源、互動限制 warning 與完整 artifact，不會把歷史候選偽裝成即時訊息。
- ✅ FastAPI 控制台新增「每日報紙」：版次歷史、來源與可見 agent artifacts、讀者偏好設定、網頁 ❤️／🚫／👀 回饋、新聞室服務狀態與 log。大量 artifact 來源僅顯示前 12 筆並標示總數，避免 UI 載入失控。
- ✅ 「每日報紙」新增候選來源健康面板：逐一顯示 subreddit 的輪詢新鮮度、最後候選與 24 小時新增量；不顯示憑證或抓取內容。production 已驗證新 RSS 輪次的 `r/taiwan` 立即保存 21 篇候選（9 篇去重）。
- ✅ 控制台的主要服務按鈕現在只控制 v5 newsroom；舊 v4 scheduler／bot 只顯示狀態，避免誤按「全部啟動」導致舊 Top-5 推播復活。
- ✅ 控制台會讀取 Alembic head 與目前 DB version；schema 尚未升級時新聞室標示「需要部署」並拒絕啟動，避免新程式碰到舊 DB 後才在日誌失敗。
- ✅ 控制台的 launchd 狀態判讀已對齊 macOS 實際 `=> disabled` 回覆；已停用的 v4 scheduler／Bot 現在正確顯示為「已停止」，不再誤標為「未載入」。production API 已實測能讀取服務、9/17 已發行 8 則版次、七日試刊與 reader profile。
- ✅ 編輯室新增「回饋通路」狀態：依 Bot receiver 的即時狀態告知 Telegram 按鈕能否被接收；receiver 停用時明確引導使用網頁 ❤️／🚫／👀，避免誤認 Telegram 回饋已上線。
- ✅ 控制台新增七日試刊面板：逐日顯示出刊、8–10 則 layout、來源完整度與 ❤️ 正向回饋，只有連續 7 天已出刊且來源完整才會顯示 gate 通過；已用隔離 migrated SQLite 實機檢視。
- ✅ Telegram newspaper 改為每篇獨立、可來源追溯的訊息，附 ❤️／🚫／👀 callback；callback 會確認 chat 屬於該 reader、冪等寫入 `reader_feedback`，並在成功後移除鍵盤。現有 bot 仍 disabled，尚未將新 callback 上線。
- ✅ 回饋學習 agent 會在每期編採前留下可檢視 artifact；同一採訪線累積至少兩次正向回饋才會成為 soft priority，避免單次點擊造成偏好劇烈漂移。
- ✅ 讀者版設定補上優先／排除關鍵字：遷移、API、控制台與 scout 都已串接；優先字會提高選題排序，排除字會在標題或正文命中時剔除。
- ✅ 選題候選不足時，版次與 failed assignment artifact 會保留為 `planning_failed`；控制台可直接顯示漏刊原因，不再因 transaction rollback 只剩服務日誌。
- ✅ 已執行 `deploy/install_launchd.sh newsroom-deploy`：建立並驗證 SQLite 備份 `reddit_tracker.backup-20260918-133504.db`、production DB 升級至 `d68a592f6d22`、只重載 v5 `com.leroy.reddit-tracker.newsroom`（PID 88082）；舊 v4 scheduler／bot 仍維持 disabled。
- ⚠️ 部署後首輪 candidate discovery 使用 RSS 時在 `/r/taiwan/new/.rss` 收到 429，依保護邏輯跳過本輪剩餘 feeds，結果 `inserted=0`；服務未中斷，但明日 05:30 是否有足夠候選仍需觀察。RSS 為匿名 fallback，必須維持保守節流。
- ✅ 修正 newsroom reload 競態：先由 launchd `bootout` 再清除殘留程序，避免 `KeepAlive` 於重載期間短暫啟動第二個 scheduler，導致雙重 RSS 首次請求。已重載 production newsroom，確認僅 PID 88838／88843 一組程序。
- ✅ RSS scraper 在 429 後會停止當輪 source traversal；尚未真正請求的 source 不再被更新為 `last_polled_at`，日誌與控制台可據此辨識候選新鮮度。首次 discovery 也改成 scheduler 啟動後的背景 job，避免保守節流的 15 分鐘 crawl 延誤 05:30 編採或 08:30 發行。
- ✅ RSS discovery 改為每個 subreddit 完成後立即 commit 與進度記錄；長輪詢可在中途從健康面板看見新候選，也不會因後續來源失敗遺失先完成的資料。已清除 9/18 首次 429 舊程式錯標的 14 個 `last_polled_at`，避免控制台誤報來源新鮮。
- ✅ 以 production SQLite online snapshot 做 9/19 不送訊息的 template 預檢：成功組出 8 則（6 brief／2 feature），每則都有 1–2 個 Reddit 來源；快照已移至垃圾桶，production DB、版次與 Telegram 均未改動。
- ✅ 已建立每日 08:45 Asia/Taipei 的新聞室七日試刊檢查：正常無異常時保持安靜，遇失敗或完成 7/7 gate 才回報並繼續處理。
- ✅ 全套驗證：`uv run --group dev python -m pytest -q` → **317 passed**（既有 FastAPI TestClient deprecation warning 1 則）；變更檔 Ruff、`node --check`、`bash -n` 與 `git diff --check` 通過；本機 UI 已實機檢視。

## 本次變更（2026-09-17 — 發行失敗停損）

- ✅ 9/17 08:30 首期已成功發行：edition 1、8 則稿件、Telegram 1 則訊息；scheduler log 顯示 job 成功完成。
- ✅ 修正多訊息 Telegram 發行的失敗語意：若送出中斷，版次會標記 `delivery_failed`，不再退回 `drafted` 供 scheduler 自動重試，避免已送出前段後重複發送。需人工檢視 Telegram 與 log 後再處理此類版次。

## 本次變更（2026-09-16 — production 試刊切換與 Gemini 實測）

- ✅ 已停止並 disable 舊 `com.leroy.reddit-tracker.scheduler`／`.bot`，因此明早不會再收到舊 v4 的 09:00 top-5；舊程序已確認停止。
- ✅ 在停止服務後以 SQLite `.backup` 建立 `reddit_tracker.db.backup-20260916-pre-newsroom`（77 MB），production DB 已從 `7778060d74e7` 升級至 v5 `b91feebcd321`。
- ✅ 以 9/16（Asia/Taipei）候選池的 562 則貼文製作 9/17 版次：1 位 trial reader、8 個 drafted items、13 個成功的可檢視 agent runs；Telegram preview 與 HTML preview 都只在本機產生，尚未發送。
- ✅ Google 免費 API 實測結果：`gemini-3.5-flash` 整期請求兩次皆 HTTP 503（temporary high demand），不適合作為關鍵路徑；既有評分用的 `gemini-3.5-flash-lite` 成功以**單一 JSON request**完成 8 則繁中稿。新聞室預設已改用 Flash-Lite，且每天僅需一筆整期 request、以本機 12 次/日 + 5 RPM guard 控制；若失敗保留完整繁中 template fallback。
- ✅ 已安裝、enable 並啟動 `com.leroy.reddit-tracker.newsroom`；它只等待 Asia/Taipei **每日 08:30**，啟動不會立刻發訊息。9/17 已有 drafted edition，所以明早工作只剩 Telegram delivery，不會再依賴 Gemini 生成。

## 本次變更（2026-09-16 — v5 08:30 受控試刊，待 production 切換）

- ✅ 新增 Gemini 整期 writer：單一 guarded JSON request 產生 8–10 則繁中短稿；程式固定 story kind、信心、warning、原帖標題與 Reddit link，模型不能改寫來源契約。Gemini 失敗時會留下 failed agent run，且可改用 source-transparent template fallback，不會讓明早無報可讀。
- ✅ 新增 `newsroom.run`：預設只做 preview；同一期可冪等重用草稿。發行前會標記 `publishing`，成功後記錄 Telegram message id／時間，避免 scheduler retry 重複發送。
- ✅ 新增 Telegram newspaper formatter：保留每篇原帖標題與連結、以 article boundary 拆成 3,700 字內訊息；不使用未完成的 feedback button。
- ✅ 新增獨立 `com.leroy.reddit-tracker.newsroom` launchd plist，以 `caffeinate -i` + polling APScheduler 在 Asia/Taipei 每日 08:30 發行；不會啟動時立即寄送。
- ✅ 新增 Gemini writer／Telegram formatter contract tests；newsroom 定向測試 13 passed、Ruff passed。下一步是全套測試後，停 v4、備份 production SQLite、Alembic migration、用 9/16 真實候選製作 9/17 preview，並以保守多次 API probe 實測 Gemini 免費額度。

## 本次變更（2026-09-16 — v5 可展示離線 Demo）

- ✅ 新增 `newsroom.demo` 一鍵端到端流程：建立**新的暫存 SQLite**、seed 10 則代表性候選、跑 N2 planning + N3 evidence/drafting，產生 8 則 edition、6 個可見 agent artifact、Telegram preview 與 HTML 編輯室。
- ✅ 新增 `newsroom.rendering`：HTML 顯示每篇繁中 headline、原帖標題／可點 Reddit link、內容邊界／warning，以及右欄的六個 agent status、摘要與來源；輸出只含可檢視 artifact，沒有 prompt 或 private reasoning。
- ✅ 實跑 `uv run python -m reddit_tracker.newsroom.demo --output <tmp>/daily-paper.html`：成功寫出 17 KB HTML + 224 KB isolated DB，8 items／6 artifacts，且 console preview 明確標示未發送。
- ✅ Demo 原帖英文標題不再直接充當中文 headline：採訪 agent 優先用 source metadata 的 `headline_zh`，否則採用中文安全 fallback；原文標題另在成稿與 source card 保留。
- ⚠️ 這是展示產品體驗的離線版：不讀 production DB、不打 Reddit／Gemini／Telegram；Gemini writer、真實 callback／08:30 scheduler 與既有 FastAPI dashboard 整合為下一階段。

## 本次變更（2026-09-16 — v5 N3 Evidence + Demo Drafting）

- ✅ 新增 `newsroom.writing` 的 verification／writing／chief_editing 三段：每個 pitch 先轉為 `EvidenceBrief`，明確記錄原作者自述、Reddit-only 未獨立驗證的邊界與敏感內容 warning，再產出保留原帖標題、來源與「為何值得看」的繁中 draft。
- ✅ 寫入 8 個 `edition_items` 與其 source bridge，並將三段 artifact 寫入 ledger；drafting 重跑保護改用 DB query，避免 ORM relationship cache 導致 unique position error。
- ✅ 採 template writer 作為無 API、無外部副作用的 demo fallback；未來 Gemini writer 只替換 draft 生成，不會改變 evidence、source、safety 或 dashboard contract。
- ➡️ 下一步：完成 N4/N5 的 Telegram preview formatter、離線 HTML 編輯室頁面與一鍵 demo script；Gemini writer adapter 留待 demo 後接入。

## 本次變更（2026-09-16 — v5 N2 Editorial Planning）

- ✅ 新增 `newsroom.planning`：以出刊日期的**前一個 Asia/Taipei 日曆日**為 candidate window，統一轉成 UTC 查詢；`posted_at` 缺失時明確 fallback `discovered_at`。
- ✅ 讀者檔案 agent 將明確 topic／排除條件與自然語言偏好轉為 `ReaderBrief`；採訪 agent 對候選做採訪線分類、排除 subreddit、偏好排序，且每個 `StoryPitch` 都帶原帖標題、完整 Reddit link 與 timestamp。
- ✅ 選題主編按來源多樣性組出 6–8 則 brief + 1–2 則（每則至少 2 個來源）feature，固定產出 8–10 項 `EditionPlan`；候選不足時拒絕偽造版次並把 assignment agent run 寫為 failed。
- ✅ `plan_edition` 已把 reader_profile／scout／assignment 三段可見 artifact 寫入 N1 ledger，包含 source bridge 與 retry-safe run record；N2 fixture tests 覆蓋台灣日界、window filter、偏好排除、來源與 artifact 追溯、8 項版面與候選不足。
- ➡️ 下一步 N3：以 evidence brief 把每則候選的主張、原作者自述、留言觀點與不確定性結構化，再由 LLM 生成繁中短報／專題草稿與 content-safety gate。

## 本次變更（2026-09-16 — v5 N1 Reader + Edition Ledger）

- ✅ 新增 Alembic revision `b91feebcd321`：`reader_profiles`、`newsroom_editions`、`edition_items` 與來源 bridge、`agent_runs`／artifact ledger 與來源 bridge、`reader_feedback`。每一期以 `(reader_profile_id, edition_date)` 唯一，stage retry 以 `(edition_id, stage, attempt)` 唯一，保證可重跑與可追溯。
- ✅ 新增 `newsroom.repository`：建立讀者、冪等建立版次、開啟／完成 agent run（artifact 必須連到既有 candidate）、以及 ❤️／🚫／👀 (`more`／`less`／`follow`) 回饋；跨讀者 item 回饋會被拒絕。
- ✅ disposable SQLite 的 Alembic integration test 已實測 `upgrade head → downgrade 7778060d74e7`；production `reddit_tracker.db` 未執行 migration。N1 合計 10 個 newsroom／migration tests 通過。
- ➡️ 下一步 N2：依 edition 的台灣日曆 window 讀取候選、產生 reader-aware `StoryPitch` 與 8–10 則 `EditionPlan`，不再沿用 v4 FIFO scoring picker。

## 本次變更（2026-09-16 — v5 AI Newsroom 開發準備）

- ✅ 產品方向正式從「Reddit 單篇推送」轉為「個人化 AI agent 每日報紙」：台灣讀者視角、中英文 Reddit 來源、繁中成稿、每日 08:30 Telegram 發行、8–10 則短報／專題混合版、網頁可追溯編輯室。
- ✅ 決定**沿用本 repo、不 fork、不重建**：保留 scraper、candidate DB、LLM factory、Telegram transport 與 FastAPI dashboard；以 branch `codex/ai-newsroom-foundation` 隔離 v5 開發。v4 scheduler / bot / production DB 本次完全未改動。
- ✅ 建立 v5 規格與分工文件：`docs/v5/` 含產品 brief、agent contracts、架構／安全切換、里程碑與 Codex／Claude Code 共用協作準則。
- ✅ 新增 `reddit_tracker.newsroom.contracts`，用 Pydantic models 固化 ReaderBrief、StoryPitch、EditionPlan、AgentArtifact 的 source-first 可見產出契約；新增 fixture-only tests，沒有呼叫 Reddit、Telegram 或 LLM。
- ✅ `uv sync --all-groups` 後以 `uv run --group dev python -m pytest -q` 驗證 **273 passed**（既有 FastAPI TestClient deprecation warning 1 則）；newsroom 新檔 Ruff 通過。直接呼叫 `pytest` 目前會失敗，因舊 console script 的 shebang 指向已搬遷的 workspace，已在協作準則中固定使用 module 形式。
- ⚠️ v4 的 FIFO scoring（每 30 分鐘 5 篇）與 daily_top5 不符合新聞室需求；N2 必須改為 edition date window 優先處理。資料 migration 前必須先停服並備份，詳見 `docs/v5/ARCHITECTURE.md`。

## 本次變更（2026-09-16 — Telegram 無通知診斷）

- ✅ scheduler（PID 2097）與 Telegram bot（PID 2098）均持續存活；launchd 兩個 job 已 enable，scheduler 的 discovery、scoring、daily push、breaking 與 milestone jobs 都持續準時執行。
- ✅ 9/14 09:00 CST daily push 成功送出 5 則（log：`sent=5 failed=0`）；9/15 與 9/16 09:00 CST daily push 均正常執行，但都記錄「無候選」，不是 Telegram 發送失敗。
- ⚠️ 根因是 RSS 試跑設定 `SCORING_BATCH_LIMIT=5`、每 30 分鐘最多評 5 篇（理論上限 240/日），但 RSS 候選累積遠高於此：9/14–9/16 新增約 3,400 篇，尚有 3,532 篇未評，且目前只評到 9/13 19:25 的舊候選。daily picker 僅收過去 24 小時且 `final.passed=True` 的貼文，因此最近兩日池為空。
- ⚠️ RSS 本身也無 single-post、comment tree、duplicates endpoint；M5 polling / milestone 偵測會持續印 warning，但不影響 daily push。另有 1 筆舊 pending milestone（2026-05-28）尚未通知，需另行判斷是否補送或清理。

## 本次變更（2026-09-13 — RSS one-day trial 準備）

- ✅ 實機 RSS probe：`r/taiwan/new/.rss` 成功回傳 5 篇當日貼文（含 post id、title、UTC time、`source=rss`）。快速連抓多個 feed 時 Reddit 對後續請求回 429，證實 RSS 可用但必須保守節流。
- ✅ 本機試跑設定改為 RSS 60 秒 request 間隔、每次 M3 最多評 5 篇，避免 RSS burst 與 Gemini Free Tier 回補同時造成限流；這兩個 `.env` override 不會提交。
- ✅ 21:16 CST 開始一天試跑：RSS 間隔再降為 60 秒，429 時跳過該輪剩餘 feed、等待下個 90 分鐘 discovery round；scheduler / bot 均由 launchd 啟動且各只有一個 process。初始 pass 完成，M3 處理 5 篇、rules pass 2、無 errors，DB 尚餘 8 篇未評分。
- ✅ 21:22 CST RSS cooldown 後複測：專案 `RssScraper.fetch_new("taiwan")` 再次成功解析 5 篇當日貼文；429 為短時 request throttling，非 RSS endpoint 失效。
- ✅ 一天試跑完成（2026-09-13 21:16 → 2026-09-14 21:16 CST）：18 次 subreddit discovery round 中 14 次有新增，累積寫入 1,730 筆 RSS 候選、4,358 筆去重；來源涵蓋 AskReddit、offmychest、relationship_advice、中文 sub 等 14 個 subreddit。M3 三階段各完成 238 筆，Gemini Flash-Lite 共處理 238 篇、48 篇通過 Haiku gate。scheduler / bot 持續存活，試跑最終階段沒有 scheduler ERROR 或 bot warning/error。少數 RSS 429 / user feed 404/403 已由 Plan C 防護處理，不中斷下一輪排程。

## 本次變更（2026-09-13 — Gemini Free Tier API）

- ✅ 新增 `LLM_PROVIDER=gemini`：M3 評分使用 `gemini-3.5-flash-lite` 的 JSON mode；M6 問答使用 `gemini-3.5-flash`。兩條路徑皆記錄 API usage token，Free Tier 成本記為 `$0`。
- ✅ 加入跨 scheduler / Telegram bot 的本機額度 guard：Pacific 日界線、評分 450 次／日、QA 50 次／日、5 RPM；Gemini 429 最多 retry 兩次，仍受限才 fallback 至既有手動登入 browser provider。
- ✅ 實機驗證：API key 可列出可用模型；QA 與 M3 JSON request 均回覆成功（M3 正常 JSON、Gemini 3.5 系列可用）。此 key 對新使用者不再提供 Gemini 2.5 Flash / Flash-Lite generate endpoint，故預設改為 3.5 系列。
- ✅ 268/268 pytest 通過；本次變更檔案 ruff 通過。全 repo ruff 仍有既存 16 個 scheduler / import lint 問題，未在此功能變更中修改。
- ⚠️ launchd scheduler 與 bot 仍維持 disabled；本次只做 API 最小請求，不會自行啟動服務。

## 本次變更（2026-09-13 — 本機操作控制台）

- ✅ 新增 `reddit_tracker.web` 本機 dashboard：總覽、scheduler / Telegram Bot 一鍵啟動與停止、非敏感設定編輯、SQLite 資料瀏覽、QA 歷史對話、服務日誌與 Chrome LLM doctor。
- ✅ 控制台只綁定 `127.0.0.1:8765`；不會讀取或顯示 API key／Telegram token。launchctl 呼叫使用固定 allowlist，停止時同時 bootout + disable，防止 `RunAtLoad` 在下次登入時重啟。
- ✅ `uv run python -m reddit_tracker.web` 啟動並自動開啟瀏覽器；不會因建置控制台而啟動既有背景服務。

## 本次變更（2026-09-13 — 零 API-key LLM browser provider）

- ✅ 新增 `LLM_PROVIDER=web`：評分（M3）與 `/ask`（M6）共用已登入的 ChatGPT / Gemini 官方網頁工作階段，取代 Anthropic / MiniMax API；回報成本固定 `$0`。
- ✅ 參考 `teddashh/multi-ai-chat-desktop` 的 adapter 架構，保留 ChatGPT / Gemini 的 input、send、response、streaming selector；目前實作為 Python + 本機 Chrome DevTools，非其 Tauri app 的直接依賴。
- ✅ 安全邊界：只允許 loopback CDP、使用者手動登入、絕不讀帳密／cookie／既有對話、不自動登入或繞過 CAPTCHA／配額；scheduler 和 bot 以跨 process lock 序列化網頁請求。
- ✅ 實機驗證：隔離 Chrome profile 已手動登入 ChatGPT；`llm_web_session_doctor.py` 回覆 `READY`。短 QA round-trip 回傳 `QA_OK`、虛構 Reddit 貼文五軸 JSON 成功解析為 `track`，均為 `$0` API 成本。ChatGPT 152 的 mobile composer / 繁中 send button / assistant turn selector 與 CDP Origin allowlist 已納入 adapter。
- ⚠️ 兩個 launchd job 目前仍停用；這次只驗證 provider，不自動啟動 Reddit 抓取或 Telegram 推送服務。

## ⚠️ 服務狀態（2026-08-19 — 全部暫停，且已停用自動重啟）

**launchd jobs**：
- `com.leroy.reddit-tracker.bot` — bootout + **disable**
- `com.leroy.reddit-tracker.scheduler` — bootout + **disable**
- 確認方式：`launchctl list | grep reddit` 應該無輸出；`launchctl print-disabled gui/$(id -u) | grep reddit` 應顯示兩個都是 `disabled`
- **實測驗證過根因**：8/13 只 bootout、沒 disable，結果 8/18 17:11 開機/登入時 launchd 依 `RunAtLoad=true` 自動把兩個 job 重新載入（PID 1399/1403），8/19 發現後才補上 disable。確認過沒有 crontab 或其他 plist 在搞，純粹是 RunAtLoad 的效果。

**關閉方式**（下次要暫停服務時）：
```bash
launchctl bootout gui/$(id -u)/com.leroy.reddit-tracker.bot
launchctl bootout gui/$(id -u)/com.leroy.reddit-tracker.scheduler
```
若要連重開機也不自動復活，額外加：
```bash
launchctl disable gui/$(id -u)/com.leroy.reddit-tracker.bot
launchctl disable gui/$(id -u)/com.leroy.reddit-tracker.scheduler
```
（兩個 plist 都設了 `RunAtLoad=true` + `KeepAlive=true`，單純 bootout 不會阻止重開機/登入後 launchd 自動重新載入，disable 才會。）

**重啟方式**（若之後又被 disable 過，要先 enable 再 bootstrap）：
```bash
launchctl enable gui/$(id -u)/com.leroy.reddit-tracker.scheduler
launchctl enable gui/$(id -u)/com.leroy.reddit-tracker.bot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.leroy.reddit-tracker.scheduler.plist
sleep 2  # 避開 launchd ratelimit
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.leroy.reddit-tracker.bot.plist
launchctl list | grep reddit  # 應該看到兩個 PID
```

**Demo 用 DB 變更**（純人工 SQL，無 migration）：
- `UPDATE tracked_posts SET status='active' WHERE id IN (2, 3);`（讓 /ask 2 /ask 3 可開 session）
- demo 結束想還原：`UPDATE tracked_posts SET status='archived' WHERE id IN (2, 3);`

重啟後驗證：`tail -f scheduler.log` 應該看到 "Scheduler started" + PRAGMA WAL 觸發。

重啟後立即生效的 commits（停服期間累積未生效）：
- `6304bc3` subreddit 大小寫 lowercase normalize（PostPayload + ingest）
- `7fc83fd` M7.6 haiku SYSTEM_PROMPT retune（議題型 + 0/0 disclaimer）
- `6cfede8` db.py WAL + busy_timeout=5s（修 lock 致死）

**DB 已實際切到 WAL** — 即使 launchd 重啟前，DB file 本身已是 WAL 模式（直接 `sqlite3 PRAGMA journal_mode=WAL` 跑過）。`reddit_tracker.db-wal` + `-shm` 兩個輔助檔會持續存在直到下次 checkpoint。



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
| M5 | 收藏追蹤層 | 🟢 | 升格 + tier polling + 四類偵測（author_followup / author_reply / hot_reply / crosspost）+ milestone immediate push + daily digest + `RelatedPost.notified_at` 去重 + `/saved` `/timeline` + alembic migration (notified_at + uq_related_post_triple) + 8-job scheduler + smoke end-to-end + 61 新 tests (160/160) |
| M6 | 問答層 | 🟢 | MiniMax 多輪 chat（Opus 由專案決定替換為 MiniMax）+ in-memory session state + 重量 system prompt（origin / snapshots / comment tree / related events）+ `/ask` `/exit` + 自由文字 MessageHandler + scheduler `qa_idle_sweep` (TTL=5min) + 38 新 tests (198/198) |
| M7 | 評估與調優 | 🟡 | 7.1/7.2/7.3/7.4/7.7/7.9 完成（5 支 eval + dry-run cleanup + baseline 報告）；7.6 retune / 7.8 QA 自評等 OAuth 通過 |
| M8 | 報告與 demo | 🟡 | 8.1/8.2/8.3/8.5/8.7 ✅ (docs/report.md Ch1-5 + Ch8 + Ch6 灌數據；README + .env.example 對齊)；8.4 樁 (等 OAuth)；8.6 demo / 8.8 slides 由 user 自做 |

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

**Incident triage — daily_push lock 致死 + db.py WAL 修上** ✅（2026-06-11, commit `6cfede8`）：
- 症狀：user 回報「這幾天沒收到 Telegram 通知，但 bot 還活」。實查確認 launchd scheduler + bot 都還在跑，discovery 持續累積 candidate（過去 3 天 +3,737 筆，最新 6/11 07:00）
- log 找出真因：6/9 / 6/10 / 6/11 連 3 天 9 AM daily_top5_push 都 raise `sqlite3.OperationalError: database is locked`，死在 `services/feed.py:399 record_pushes/session.flush()`
- Plan C fallback ✅ 確實有 engage（log 三天都印 `plan_c fallback engaged pool=~580 picked=5 via final_score`）— 5 篇都選好了，全死在「寫 daily_pushes」這一步
- 245 次 OperationalError 累積在 scheduler.log，bot ↔ scheduler 兩 process 並發寫 SQLite 必撞 lock 是長期 systemic 問題
- 根因：SQLite 預設 `journal_mode=delete` + `busy_timeout=0` — 撞鎖立即 fail 不重試
- 修法（[reddit_tracker/db.py](reddit_tracker/db.py)）：
  - `create_engine` `connect_args["timeout"]=5.0`
  - `@event.listens_for("connect")` 跑 `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` + `busy_timeout=5000`
  - WAL 讓 reader 與 writer 不互相 block；只有 writer 之間 mutex
  - [.gitignore](.gitignore) 加 `*.db-wal` / `*.db-shm`
- DB file 已用 `sqlite3 CLI PRAGMA journal_mode=WAL` 一次性切到 WAL，即使重啟前對現存 connection 也立即生效降低衝突
- 248/248 pytest 過
- 接著 launchd 兩個 job 全 bootout 暫停服務（user 要先做其他事）

**M8 cold-start — 報告骨架 + onboarding 整理** ✅（2026-06-08, SCHEDULE 8.1/8.2/8.3/8.5/8.7）：
- 8.7 [README.md](README.md) 大改 — 反映 no-reddit-api 分支實況（Plan C / RSS / public_json / OAuth 申請中）+ M1-M7 完成度表 + 真實技術棧（含 MiniMax）+ 文件索引（含新 M7 docs）
- 8.7 [.env.example](.env.example) 補齊 — 加 `REDDIT_SCRAPER` 4 種選項說明 + `MINIMAX_*` 三個變數 + 排程 envs 一律列出做為 override 參考
- 8.1+8.2+8.5 [docs/report.md](docs/report.md) — Ch1 動機（含 v3→v4 + Plan C 兩段 pivot）+ Ch2 目標 + Ch3 系統架構（含 v4 vs v3 差異表 + Plan C 退化處理）+ Ch4 核心功能（M2-M6 五層摘要）+ Ch5 DB schema（12 表 + M5 migration）+ Ch8 倫理（公開性 / 去識別 / LLM 責任界線 / Reddit ToS / 資料保留刪除）
- 8.3 Ch6 評估結果灌真實數據：漏斗總覽 17,743 → 9 tracked / 中英對照 zh 15.1% vs en 35.3% / 四類後續 / 後續命中 / 成本 $1.5/月 / Plan C 適應性
- 8.4 Ch7 案例分析留樁 — 樣本不足（1 unique tracked），等 OAuth + 14 天運轉後展開 ≥ 3 個生命週期
- 待 user：8.6 5 分鐘 demo 影片 + 8.8 10–15 頁簡報 slides

**M7.6 變體 — Haiku prompt retune（中文 sub 識別偏弱）** ✅（2026-06-08, M7 retune backlog #1）：
- 命題：SCHEDULE 7.6 原本要分析 dislike 樣本，但只累積 5 筆要等 OAuth；改用 scoring 視角的等價分析 — 中文 sub haiku pass 15.1% vs 英文 35.3%（差 2.3×）
- 分析：[scripts/eval_haiku_fail_samples.py](scripts/eval_haiku_fail_samples.py) 抽 5 中文 sub × 10 + 2 英文對照 sub × 5 = 60 筆 haiku verdict=skip 樣本 → [docs/m7_haiku_fail_samples.md](docs/m7_haiku_fail_samples.md)
- 三個失準模式（[docs/m7_haiku_fail_analysis.md](docs/m7_haiku_fail_analysis.md)）：
  - 2.1 諮詢題大量被 skip（旅遊 / 美食 / 簽證） — **合理判定，不是 bug**；中文地方 sub 結構性差異，不該動 prompt
  - 2.2 議題討論型被低估（紀念六四 / 文化反思）：`emotional_pull=0.8` 但 `story_potential=0.3` → skip。**真盲點**：prompt 把 story_potential 限定為「事件繼續發生」，沒涵蓋「議題引發持續討論」
  - 2.3 0/0 互動被當冷度證據：60% candidate 是 `score=0 num_comments=0`（剛發布 + RSS 退化），Haiku 推斷低 story_potential。**真盲點**：prompt 沒提醒這是時間序起點
- 修法（[llm/haiku.py](reddit_tracker/llm/haiku.py)）：
  - SYSTEM_PROMPT 擴展 story_potential 定義 — 加 (a) 事件型 + (b) 議題型；註明 `emotional_pull ≥ 0.7 且 authenticity ≥ 0.6` 時不要因「沒具體後續」就 < 0.4
  - 加 0/0 互動 disclaimer — 明確告訴模型那是時間序起點不是冷度證據
  - **不**動 verdict 門檻 / build_user_prompt（避免過度鬆綁讓英文 sub 噪音貼也被打爆）
- 6 個新 tests（[tests/test_haiku_prompt.py](tests/test_haiku_prompt.py)）覆蓋 prompt 含關鍵段落 + JSON schema 保留 + verdict 門檻不變 + parser 行為不變。全套 248/248 過
- 留 backlog：A/B 驗證等 OAuth 通過後 ≥ 50 dislike 樣本，跑 eval_dislike_features.py（新腳本），驗證 retune 是否提升 precision；每週對帳 eval_lang_breakdown.py 看中文 pass 是否升到 25%+

**Subreddit 大小寫正規化** ✅（2026-06-08, M7 retune backlog #3）：
- 症狀：candidate_posts 內 mixed-case（taiwan 381 + Taiwan 8 + Taipei 197 + Updateme 17…），跟 subreddit_sources.name 對不上、JOIN 統計失準
- 根因：Reddit JSON 內 `d["subreddit"]` 不同 endpoint 偶爾回不同 case；seeds 寫顯示名（大寫），scraper 寫入 candidate 用 reddit 回的 case
- 修法：
  - [scrapers/base.py](reddit_tracker/scrapers/base.py) `PostPayload.__post_init__` 統一 `subreddit.lower()`（外部→系統的單一闸口）
  - [seeds/subreddit_list.py](reddit_tracker/seeds/subreddit_list.py) 全 lowercase + `__post_init__` 保險
  - [seeds/loader.py](reddit_tracker/seeds/loader.py) 比對既存 row 用 `func.lower()`，認領舊 mixed-case row 並 rename，不會多開一筆小寫版
  - [services/discovery.py](reddit_tracker/services/discovery.py) `_ingest_payloads` 雙保險 `(p.subreddit or "").lower()`
  - [scripts/m7_normalize_subreddit_case.py](scripts/m7_normalize_subreddit_case.py) 一次性 housekeeping（dry-run + --apply）：9 source rename + 7,698 candidate UPDATE，無合併衝突
- 6 新 tests（test_subreddit_case_normalize.py）涵蓋 PostPayload 4 種輸入 + seeds_loader 認領 + ingest 雙保險。全套 242/242 過
- 預期：M7 eval 統計（eval_lang_breakdown / eval_relation_dist）的 subreddit JOIN 從此完全乾淨

**Plan C picker fallback** ✅（2026-06-08, commit `0fae935`）：
- 症狀：6/6 6/7 6/8 三天早上 9 點都印「無候選」沒推送
- 根因：兩個主桶都空——already_hot 要 velocity 但 RSS 全 None；early_bet 要 age<3h 但 9 點前那 3h 還沒被 scoring 趕上；灰帶 3-6h 照 M4.1 設計刻意跳過
- 修法：`pick_daily_top5` 偵測 `velocity_none_ratio > 90%` 時，退化為「final_score top 5 取滿」全標 `early_bet`，log 印 `plan_c fallback engaged`
- 4 新 tests 全套 236/236 過。預期 6/9 起每天 9 AM 正常推 5 篇
- 同次修上：[reddit_tracker/bot/app.py](reddit_tracker/bot/app.py) `post_init` 自動 sync Telegram 端 setMyCommands；[scripts/refresh_bot_commands.py](scripts/refresh_bot_commands.py) 不重啟也能刷選單

**M7 baseline 半段完成** ✅（2026-06-02）— 詳見 [docs/m7_baseline_2026-06-02.md](docs/m7_baseline_2026-06-02.md)：

- `scripts/eval_collection_rate.py` (7.1)、`eval_followup_hit.py` (7.2)、
  `eval_lang_breakdown.py` (7.3)、`eval_relation_dist.py` (7.4)、
  `eval_llm_cost.py` (7.9)、`m7_disable_dead_sources.py` (7.7, dry-run)
- 收藏率 64.3%（pre-Plan-C 71% → Plan-C 57%，already_hot 71% → 33%）
- 後續命中率 archived 80% / active 0%；avg 9.2 related/篇 + 2.2 milestone/篇
- 中英對照：英文 haiku 通過 20% vs 中文 8.6%；中文 sub 在 daily picks 曝光僅 1/14
- 月成本 $1.5（企劃預估 $15–36，便宜 10×）
- cleanup 結論「現階段不該動」：6 個零收藏 sub 都是 never-pushed，picker 樣本不足
- 待辦：7.6 prompt retune（針對中文）+ 7.8 QA 自評（要 OAuth 通過）

**Plan C 期間補完 bot 三個 deferred 指令** ✅（2026-06-02）：

- `/feed` — 今日 daily_pushes 依 push_type 分組（🔥 已爆貼 / ⚡ 早期下注 / 🚨 即時破例）；
  今日無推送則 fallback 列過去 24h 通過 final scoring 的 top 5
- `/digest` — user 自己 tracked_posts 過去 7 天的 milestone，依 tracked 分組 + 各
  relation_type 統計 + 每篇 top 3 milestone snippet（每筆附 `/timeline <id>`）
- `/settings` — scraper mode（Plan C 在 RSS 時顯示警示 banner）+ 過去 24h
  candidate / scoring 通過率 + 該 user 收藏統計
- `app.py` 把 deferred_cmd 拿掉，三個指令各自掛 handler；HELP_TEXT 同步更新
- 18 新 tests（test_bot_feed_digest_settings.py）：feed 空 / 今日分組 / 只列今日 /
  fallback 路徑 / fallback 過濾 stale；digest 空 / 無 milestone / 分組 / 跨 user
  隔離 / 排除非 milestone；settings 各 scraper mode / 通過率 / 個人統計 / 零資料
  邊界 + 3 個 async dispatcher smoke

**M7**：評估與調優。`scripts/eval_*.py` 系列：收藏率（feedback.collect /
daily_pushes，依 push_type 分組）、後續命中率（30 天內 related_posts ≥ 1
的 tracked 比例）、中英 sub 對照、四類 related 分布；系統需先連續跑 7 天
真實資料。Haiku/MiniMax prompt 跟硬規則閾值在 M7 過後做一輪 retune。M6
token 實測會在這階段一起補（用真實 MiniMax key 跑 5 個 tracked × 3 輪，記
input / output / cost 到 `docs/m6_token_baseline.md`）。完整任務清單見
`SCHEDULE.md`。

### M6 現況（2026-05-24，全段完成）

- ✅ **M6.1 `services/qa.py::QASessionState`**：dataclass 持 user_id /
  tracked_post_id / qa_session_id / system_prompt / history / system_tokens_estimate /
  started_at / last_active_at；in-memory `_ACTIVE: dict[user_id, state]` +
  `threading.Lock` 給 BlockingScheduler (sweep) 與 asyncio (bot) 兩個 thread
  共用。`reset_state()` 給單元測試清空
- ✅ **M6.2 重量 context 組裝 `build_system_prompt`**：
  - SYSTEM_PROMPT_HEADER 嚴格要求只依 context 答 / 不編造 / 中英都吃
  - 4 個 section：ORIGINAL POST + SNAPSHOTS（最舊→最新）+ RELATED EVENTS
    （依 relation_type 分組、relevance 排序、milestone 標 ★）+ COMMENT TREE
    （`comment_tree.to_prompt_text` 縮排呈現，標 [OP]）
  - Token budget 18k：超出自動 trim comments → `top_n_by_score(60)` + 標
    「trimmed to top X by score」
  - Scraper 可選；None / fetch_comment_tree 失敗時 comment section 留空，
    不阻塞流程
- ✅ **M6.3 `/ask <id>` handler**：驗 4 種拒絕（not_found / not_owner /
  archived / already_active）+ 整數參數；成功時回 system_tokens 估值讓使用者
  心裡有底（也利於 M7 token baseline）
- ✅ **M6.4 自由文字路由**：`MessageHandler(filters.TEXT & ~filters.COMMAND)`
  接 `chat_message`：active 走 chat、無 session 回最小提示；reply > 3900
  字自動截斷加「…（後續截斷）」尾註避開 Telegram 4096 限制；尾註附
  `in=X out=Y cost=$Z.NNNN`
- ✅ **M6.5 `/exit` + 5min idle sweep**：scheduler 新增 `qa_idle_sweep` job
  （每分鐘觸發、TTL 從 `qa_idle_ttl_seconds=300` 拉），掃 in-memory state
  找 `last_active_at <= now - 5min` 的 user，呼 `close_session(reason='ended_idle')`
  寫 `QASession.ended_at` + `state='ended_idle'`，從 `_ACTIVE` pop 出來
- ✅ **M6.6 DB 寫入**：`handle_message` 每輪寫 user QAMessage → call chat
  → 寫 assistant QAMessage（含 tokens + cost）+ LLMRecord（purpose='qa'、
  context_ref 帶 qa_session_id / tracked_post_id / turn）；chat raise 時
  rollback in-memory history（user row 保留以利追蹤）
- ✅ **M6 chat 替換策略**：原企劃寫 Opus，本次決定改 MiniMax（與 scoring
  共用 `chatcompletion_v2` endpoint、同 base_url / api_key，省一份 SDK 依
  賴）。`llm/minimax_chat.py::MinimaxChat` 為實作、`FakeChat` 為離線 stub、
  `build_chat()` factory 無 key 自動 fallback FakeChat 不阻塞 dev
- ✅ **M6.8 38 新 tests**：
  - `tests/test_qa.py`（18）：context 4 / open 5 / handle_message 4 / close
    1 / sweep 2 / state utils 2
  - `tests/test_bot_qa.py`（14）：/ask 7 拒絕 + 成功 / /exit 2 / chat_message
    4 / 整合 1
  - `tests/test_minimax_chat.py`（6）：cost / FakeChat / build_chat fallback
  - 全套 160 → 198，0 失敗、ruff clean
- 🧪 **`scripts/m6_smoke.py`**：1 candidate → promote → 1 snapshot + 2 related
  → open session（prompt 784 chars / 34 lines / ~313 tokens / 3 comments）
  → FakeChat 跑 2 輪（qa_messages=4, llm_records=2）→ sweep_idle 強制收
  → ended_idle ✓ → 再 open → 手動 close ✓
- 📌 **既知設計取捨**：
  - In-memory state 用 module-level dict — 個位數使用者下夠用，多 process
    才需要 Redis；`reset_state()` 暴露給 tests 清乾淨
  - System prompt 一次組好快取在記憶體（不每輪重組）— Reddit comment tree
    在 5 分鐘內變動很小，且重組會多打一次 fetch_comment_tree
  - Anthropic prompt cache 沒接（MiniMax API 沒提供）— M7 對帳會看 monthly
    cost 是否超出企劃預估 $0.15/次再決定要不要 hack
  - `LLMRecord.context_ref` 寫 dict 而非裸 ID — 之後對帳 / 報告分析能直接
    `WHERE context_ref->>'tracked_post_id' = ?` 撈一個 tracked 的所有 QA 開銷
  - 不寫 `qa_messages.user / assistant_tokens` 分離欄位 — `usage` 是 per-call
    維度（一次 chat 同時算進 / 出），存在 assistant 那筆 row 即可，user row 留 None

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

### M5 現況（2026-05-23，全段完成）

- ✅ **M5.3–5.6 偵測層 `services/detection.py`**：四類純函式 + `detect_for_tracked`
  編排器。各 endpoint 獨立 try/except，單類失敗不阻塞其他。
  - `detect_author_followup`：作者近期貼文中比原貼新且非自己者，title 二元組
    Jaccard（中英文都吃，不靠空白切詞）+ 同 sub `+0.3` 加成（cap 1.0）→ relevance
  - `detect_author_reply`：filter `CommentNode.is_submitter=True`，存 raw score
  - `detect_hot_reply`：絕對 ≥ 50 **或** top 與第二名比 ≥ 1.3 倍；`more` placeholder
    自動跳過；OP reply 與 hot reply 視為不同 relation_type、可同篇 fire 兩筆
  - `detect_crossposts`：`fetch_duplicates` 結果直接收
  - `persist_findings`：dedup 鍵 `(tracked_post_id, relation_type, reddit_post_id)`；
    alembic UniqueConstraint `uq_related_post_triple` 做 DB-level 保險
- ✅ **M5.7 `evaluate_milestone` heuristic**：依 `relation_type` 用閾值 — followup
  ≥ 0.7、author_reply ≥ 20、hot_reply ≥ 200、crosspost ≥ 100。預留接口、TODO
  切 Haiku 對 finding.content 做語義判斷
- ✅ **M5.8 推送層 `services/notification.py` + `bot/related_sender.py`**：
  - `fetch_pending_milestones`：is_milestone=True AND notified_at IS NULL AND
    tracked.status='active'，join Tracked+Candidate 回 PendingMilestone dataclass
  - `build_daily_digest`：lookback_hours=24、非 milestone、未 notified，依 tracked
    分組、每組取 relevance top N（預設 5）
  - `mark_notified`：idempotent，已 notified 的不覆寫時戳
  - sender 套用各自 formatter（`format_milestone_message` 帶 emoji + 原文連結、
    `format_digest_message` 一封多 tracked 聚合）
  - 對應 alembic migration 加 `RelatedPost.notified_at` + `uq_related_post_triple`
- ✅ **M5.9 `/saved` `/timeline`**：純讀 query，`asyncio.to_thread` 包 sync DB；
  saved 顯示 tier emoji（🔴 hot / 🟠 cooling / 🟡 archive）+ snapshot 數 + related
  數 + milestone 計數；timeline 列「快照變化（新→舊，相對時間）」與「相關事件
  （時間排序、milestone 標 ★）」
- ✅ **M5 scheduler 變 8 job**：原 6 + `detection`（60min）+ `milestone_check`（10min）;
  `daily_push` 接著跑 `_deliver_digest_sync` 把當日 digest 一起發
- ✅ **M5.10 smoke `scripts/m5_smoke.py`**：FakeScraper 餵 1 candidate +
  2 user_submissions + 3 comments + 1 dup → 偵測寫 5 筆 RelatedPost（4 milestone：
  followup + OP reply + hot_reply + crosspost）→ `/saved` 列出該篇 `★ 4`、
  `/timeline` 渲染快照 + 5 條相關事件
- 🧪 **61 新 tests**：detection 17 / notification 10 / bot_m5 12 / promotion 9 /
  polling 13 → 全套 160/160 過、ruff clean
- 📌 **既知設計取捨**：
  - 首位 collect 使用者寫入 `TrackedPost.user_id`；後續者再 ❤️ 同篇仍寫 feedback row
    但不換 owner（個位數使用者規模下夠用，未來多用戶可改成 user×candidate 多對一）
  - milestone 即時推送在 scheduler thread 內 `asyncio.run`，每輪 fetch_pending +
    重抓 ORM rows 進 fresh session 後 send → mark_notified（避免 session 跨執行緒）

### M5 現況（2026-05-23）

- ✅ **M5.1 升格邏輯**：`services/promotion.py::promote_to_tracked`，feedback.action=
  'collect' 寫成 feedback row 後在同一 session_scope 升格成 TrackedPost
  (polling_tier='hot' / status='active') + 累加 `subreddit_sources.total_collected`。
  Idempotent on candidate（`CandidatePost.tracked` 是 `uselist=False`）— 第二位
  使用者再 ❤️ 同篇只回 already_tracked，total_collected 也不會重複加。
  Integrate 點在 `bot/handlers._record_feedback_sync`，feedback layer 本身保持單純。
- ✅ **M5.2 分級輪詢 `services/polling.py`**：
  - `tier_for_age`：0–24h='hot' / 24h–7d='cooling' / 7–30d='archive' / >30d=None
  - `select_due_posts`：Python-side filter（SQLite 表達不了 `last_polled_at +
    interval(tier)`），對 status='active' 的 TrackedPost 看 `now - last_polled_at`
    是否 ≥ tier interval（hot=15min / cooling=1h / archive=6h）
  - `capture_snapshot`：打 `scraper.fetch_post` → 寫 `PostSnapshot(score,
    num_comments, upvote_ratio)`、更新 `last_polled_at` 與 `polling_tier`（隨 age
    自動升級）；age >30d 寫一筆 final snapshot 後 `status='archived'`；
    fetch_post 回 None 也直接 archived（貼文被刪 / quarantine）；
    scraper raise 不 archived 但仍更新 last_polled_at 避免立即重試
  - `run_polling`：上述兩者的編排，回 `PollingStat(total_due, captured, archived,
    errors)`
- ✅ **M5 scheduler 接 polling job**：`IntervalTrigger(minutes=polling_minutes=15)`
  對齊 tier='hot' 細粒度；jobs 從 5 個變 6 個（subreddit / keyword / scoring /
  daily_push / breaking_check / polling）
- ✅ **22 新 tests**：`tests/test_polling.py` 13 個（tier 邊界 / select_due 各情境 /
  capture_snapshot 5 種 outcome / run_polling 編排）+ `tests/test_promotion.py` 9
  個（promote 三種 outcome + subreddit 統計 + integration with `_record_feedback_sync`）
- 🧪 **注意 `polling_tier='archive'` ≠ `status='archived'`**：前者只是「降頻到 6h
  一次」仍在追蹤；後者是「終止追蹤」（壽命過 30 天 / 被刪 / quarantine）。M5.3+
  的偵測函式需以 `status='active'` 為篩選條件，不要誤排除 archive tier

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
