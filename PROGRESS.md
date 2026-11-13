# Reddit Tracker — 專案進度（現為 v2.0 AI 綜合日報）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 現行企劃見 `docs/AI_NEWS_COMPANY_PROPOSAL.md`、規格入口見 `docs/v5/README.md`。
> 2026-10-29 以前的段落已搬到 `docs/archive/`（見文末「更早的紀錄」）。
> 下面各段裡的「➡️ 下一步」是當時寫的，現況一律以本節「下一步」為準。

**Last updated:** 2026-11-13（`chore/cleanup-1113` 已部署：19:12 併入 main、`newsroom-reload`；**還沒 push**，main 領先 origin 9 個 commit）

## 線上現況（2026-11-13 查證）

- newsroom、rsshub 兩個 LaunchAgent 都在跑。**Mac 在 11/12 18:56 重開機，newsroom 於 18:59 重新啟動，載入的已是 `feat/newsroom-3d` 併入後的程式**（下面 11/12 段落寫的「服務沒有重載」只到重開機前為止）。重開機那一輪 RSSHub 比 newsroom 晚起來，11 個 RSSHub 來源連線被拒，下一輪恢復。
- 11/13 是新程式的第一期：06:00–06:05 準備（P 影子 5 次、M 28 次 Codex），12 篇、`degraded=[]`；12 篇於 07:06 核准；08:35 發行（Telegram 533、534）。
- 查證當下 main 領先 origin/main 3 個 commit（`ff87ca0`、`7f72c69`、`4446959`）；部署後共 9 個，**還沒 push**。
- production DB 523 MB、Alembic `b8d4f0a17c33`。全套（production checkout，有母本）413 passed／4 skipped。

## 本次變更（2026-11-13 — 專案梳理與小修，`chore/cleanup-1113`）

worktree `~/Documents/Developer/Lab/rt-wt-cleanup`。開發時 production 只做唯讀查詢，沒有呼叫 Codex。

- ✅ **已部署（2026-11-13 19:12 台北，依志晨指示）**：fast-forward 併入 main（`4446959`→`b8208b6`），備份 `~/Documents/Developer/Lab/reddit_tracker_backups/cleanup-20261113/`（sqlite `.backup`、integrity ok；`.env` 複本），`uv sync` 後 `deploy/install_launchd.sh newsroom-reload` 一次。log 有 `codex version guard ok: codex-cli 0.166.0`、三個 job 已註冊、scheduler Python process 1 個；首輪收集 19:13 ok 23/23。rsshub 未動，不需要 migration。
- 👀 11/14 06:00 是第一期用新額度檔：準備後 `~/.local/state/reddit-tracker/llm-quota.json` 應該出現。

- ✅ **SQLite 等鎖 5 秒→30 秒**（`db.py`）。11/11 06:06 收集 tick 寫 `ltn-politics` 時撞上 06:00 準備的寫入（`database is locked`），補寫健康紀錄又撞一次，整輪 tick 丟例外。`collect_due_sources` 補寫健康紀錄失敗時改成只記 log，其他來源照常寫入。
- ✅ **額度檔移出 `/tmp`**：`LLM_QUOTA_STATE_PATH` 預設改 `~/.local/state/reddit-tracker/llm-quota.json`（`/tmp` 重開機會被清掉）。⚠️ 部署當下會換檔，當天已用的次數從 0 重新算一次；請在 08:35 發行後部署。
- ✅ **E11 xfail 拿掉**（11/15 到期）：回歸重編這則沒入選，條件是 skip（不適用）；同一個條件由 `tests/test_e11_replay.py` 用 11/06 的錄音離線重播把關，理由寫在 `E11.json` 的 `note`。回歸集現在沒有任何 xfail。
- ✅ 11/13 盲計雜湊寫進 `docs/eval/blind_mapping.sha256`（與 06:05 log 的 sha256 相同）。
- ✅ ruff 4 個未使用的 import／變數清掉；README 的測試基準、來源數、Web 路由更新。
- ✅ PROGRESS 2026-10-29 以前的段落搬到 `docs/archive/PROGRESS_2026-09_to_10-29.md`。
- ✅ 實驗一結果計算腳本 `scripts/exp1_results.py`＋`tests/test_exp1_results.py`（8 個測試，含手冊 8.1 的計算例子）。
- ⛔ 實驗二三組執行腳本這次沒做：要動 `_check_and_maybe_revise`（加「相關性檢查關閉」一組）、v1 只產生一次三組共用、保留集要等實驗一 test 的人工標註、正常稿要等 A 選完，還要先定額度與 `FACT_CHECKER_PER_SOURCE`。先定設計再寫。
- 全套 420 passed／7 skipped（worktree 沒有母本快照，多 3 個 skip）。不需要 migration、不改提示詞與 `request_hash`。

## 下一步（2026-11-13 現況）

日期都是方案 B，見 [`docs/weekly/trial-dates.md`](docs/weekly/trial-dates.md)。依期限排：

1. 👤 **試刊到 11/15，每天**：06:00 準備後核准 M 組稿；交 B 之前 `scripts/collect_blind_hashes.py --write` 並 commit（11/09–11/13 已記）。
2. 👤 **push main**（領先 origin 9 個 commit）。`chore/cleanup-1113` 已於 11/13 19:12 部署。
3. 👤 **實驗一**：100 組目前是 AI 工具標的（`annotation/exp1/exp1_resolution.md`），手冊不允許，要 A、B 本人重標。結果計算腳本已有：`scripts/exp1_results.py`（`reddit_tracker/eval/exp1_results.py`，Wilson／bootstrap F1／exact McNemar／κ；不加 `--write` 只印不存）。重標交回後跑一次並 `--write`，再由開發者補 3 個錯誤分析；11/22 前。⚠️ 11/13 用 AI 標的檔案乾跑過一次確認腳本能動（只印到 stdout），那些數字不能用，也不要因此回頭調方法 C。
4. 👤 **請老師確認** `trial-dates.md` 的時程與用本機 Codex 當 LLM（手冊 6.9 第 1 條要正式 API），並告知 A、B。這裡沒有收到確認的紀錄；B 的七類錯誤計數練習（原訂 11/08 前）也沒有紀錄。
5. 👤 **`FACT_CHECKER_PER_SOURCE`**：試刊已用預設關閉在跑；要不要在實驗二 (c) 組打開，最晚 11/17 前定案（`docs/pr/checker-per-source.md`）。
6. **實驗二 11/17–11/18**（A 11/17 中午前選 15 篇正常稿）。⛔ 三組執行腳本還沒有。
7. **11/20 打 `final-1120` 功能凍結**；之前不要 `brew upgrade codex`。
8. **凍結後的清理**（都不要在 11/20 前做）：
   - `run_mas` 把整個候選池（每天約 4,800 個事件）都寫成 `stories` 並建證據包，實際只用 12 篇；先確認分版主編要不要全池，再改成只處理入選稿。
   - v4／v5 遺留資料表（`candidate_posts` 186 MB、`agent_artifacts` 58 MB、`scoring_records` 12 MB…）與 `models.py` 裡約 20 個遺留 class：交付後寫 drop migration 再 `VACUUM`。
   - production 根目錄 7 個舊 DB 備份約 1.1 GB、`bot.log` 48 MB、`scheduler.log` 21 MB；`Lab/reddit_tracker_backups` 3.6 GB。
   - 9 個 worktree 與已併入的分支；`.env` 裡 13 個沒有作用的舊鍵（含 `MINIMAX_API_KEY`）。
   - `docs/v5/` 的歷史檔移到 `docs/archive/`；`CLAUDE.md` 與 `AGENTS.md` 內容相同，擇一為主。
   - `orchestrator.py`（1,163 行）、`run.py`（1,004 行）交付不要求就不拆。

- ℹ️ `agent_messages` 有 342 列 11/12 以前的訊息停在 `pending`（結案邏輯 11/13 才生效）。是試刊資料，不回填，報告裡註明。
- ⚠️ 11/04、11/05、11/07–11/12 的 M 組稿都是 08:35 之後才核准，讀者只收到標題短訊；11/13 起是發行前核准。報告照實記。

## 本次變更（2026-11-12 — 手冊對照盤點＋3D 編輯室，`feat/newsroom-3d`）

worktree `~/Documents/Developer/Lab/rt-wt-3d`。查證用 production DB 唯讀複本，沒有呼叫 Codex、沒動 production。細節見 ADAPTATION「2026-11-12 手冊對照盤點與 3D 編輯室」。

- ✅ 3D 編輯室回放 `/daily/<date>/newsroom/office`（`daily/replay.py`、`office_page.py`、`office.html`）；日報頁右下與表格版回放都有入口。three.js 從 jsDelivr 載入，放一份到 `reddit_tracker/daily/vendor/three.module.js` 就能離線。
- ✅ 補齊：`agent_messages.llm_call_id`、訊息真實時間、訊息結案、報頭期號／台北出刊時間、「多來源」標籤、來源列時間、頁尾聲明、盲計雜湊（11/09–11/12）、`scripts/trial_metrics.py`、週報草稿 `docs/weekly/2026-11-10.md`。
- ⚠️ 2026-11-12 晚上依志晨指示 fast-forward 併入 main，但 **newsroom 服務沒有重載**：常駐 process 還是舊程式，06:00 出刊照舊。新程式（訊息時間、llm_call_id、結案、報頭）要等 `deploy/install_launchd.sh newsroom-reload` 或服務自己重啟才生效；試刊到 11/15，👤 決定什麼時候重載。不改提示詞與 `request_hash`，不需要 migration。3D 回放用 `uv run python -m reddit_tracker.web` 就看得到，不用重載。
- ⚠️ **11/07–11/12 的 M 組稿是 11/12 11:03 一次補核准的**（晚於各期 08:35 發行）；試刊 11/09–11/12 四期讀者都只收到標題短訊。
- ⚠️ **實驗一的 100 組是 AI 工具標的**（`annotation/exp1/exp1_resolution.md`），手冊不允許；要標註員 A、B 本人重標。
- ⛔ 還沒有：實驗一結果計算腳本、實驗二三組執行腳本。
- 全套 410 passed／7 skipped。

## 本次變更（2026-11-06 — E11 錄音入口）

- ✅ `scripts/record_e11.py`：只處理回歸重編沒入選的莫德納稿（MarketWatch item 2736，單一來源，財經改判 world）。`--live` 在 `data/work/1027_e11.db` 走 M 組記者→（可疑才）查核→文稿編輯，新的 Codex 呼叫上限 5，額度檔 `data/work/llm-quota-e11.json`。不讀 `.env`、不開 production DB。匯出 `tests/regression/fixtures/1027_e11_evidence.json` 與 `1027_e11_records.json`。
- ✅ `tests/test_e11_replay.py`：沒有這兩個 fixture 就 skip；有了才用 `request_hash` 離線重播並套 `headline_must_not_match`。pytest 不呼叫 Codex。fixtures 已錄完並併入 `main`。
- ⚠️ STAT item 3875（刊出稿的另一家，摘要才有 “expected in 2027”）現在是另一個 cluster，這次錄音不併回去。回歸集 E11 的 xfail／重編 skip 維持。
- ✅ 離線全套在錄音後為 392 passed／7 skipped／1 xfailed／1 xpassed（新 replay 通過；回歸重編 E11 仍 skip）。

## feat/checker-per-source（已併入 `main`，旗標預設關閉）

- ✅ 查核員可對每個程式點名的可疑來源回 `KEEP`／`REMOVE`（`CHECKER_PER_SOURCE_SCHEMA`、`checker_source_verdicts`），新舊格式都收。旗標 `FACT_CHECKER_PER_SOURCE` 預設 false＝請求逐字不變，`1027_t2a_records.json` 照常重播；開啟時 T2a 重播有 2 個 miss（查核員＋記者修稿）。數字規則、LLM 失敗／額度用完不變。
- ✅ 假 client 重現 11/01 5330：S2 留、S3 刪。沒有呼叫 Codex。
- 👤 決定要不要把旗標打開與時程、實驗二影響：`docs/pr/checker-per-source.md`；設計：ADAPTATION「查核員逐來源判斷」。

## fix/newsroom-1106（已部署）

- ✅ **已部署（2026-11-06 15:54 台北）**：`fix/newsroom-1106` fast-forward 併入 production main（`84186b9`→`f252c8b`）並 push origin/main。備份 `~/Documents/Developer/Lab/reddit_tracker_backups/fixes-20261106/`；`uv sync` 後只跑一次 `deploy/install_launchd.sh newsroom-reload`（launchd LastExitStatus 0）。production `.env` 沒寫 `CODEX_TIMEOUT_SECONDS`，新預設 150 秒生效。對 11/01 M 組 5327 v2 重新核准以重畫網頁，**沒有重送 Telegram**。

11/01–11/05 觀察到的五個問題；查證用唯讀複本 `~/Documents/Developer/Lab/rt-data-1106/prod-copy-20261105.db`，沒有呼叫 Codex、沒動 production。細節見 ADAPTATION「11/01–11/05 的五個小修正」。

- ✅ **補核准後重畫網頁**：`daily approve`／`hold`（CLI 與回放頁）commit 後重畫 `site/daily/YYYY-MM-DD.html`（已發行照發行規則、草稿照預覽），**不重送 Telegram**。11/01 的網頁已於部署後用 5327 v2 重新核准重畫。
- ✅ **分版**：財經改寫加「過半標題有政治詞→國際」（排在科技詞後）、台灣公共基金詞、台灣上市櫃公司名（只蓋過國際詞）。11/05 Talarico→國際、11/04 環球晶兩則→台灣、11/03 勞動基金→台灣。⚠️ 會改到實驗一方法 C 的編輯會議候選池；已正式抽樣的話不要用這版重跑抽樣（用 `84186b9`）。
- ✅ **來源列同一家兩次**：M 組／page_plans 版面的出處改用證據包同一套名稱（「中央社（Yahoo 股市新聞轉載）」），不再用 `source_id`。
- ✅ **06:00 準備的上限**（分析）：10/31–11/05 正常時 06:00 開始、06:06 前畫完；成功的呼叫最長 45 秒（P 撰稿），M 角色最長 16 秒。11/05 的兩次 300 秒都是卡住，重試 10 秒就好，整期 06:15 畫完。但修正前沒有整體上限：每次嘗試都可能卡滿逾時，60 格額度最壞約 5 小時。改法：排程的 06:00 準備綁 `DAILY_PREPARE_DEADLINE`（預設 08:20）——每次 Codex 嘗試前檢查，剩不到 20 秒就丟 `DeadlinePassed`（不扣額度、不重試、不開 subprocess），單次逾時不超過剩餘秒數；M 組把過了截止當成額度 0 照既有順序降級（記進 `stats.degraded`），P 撰稿直接退模板稿；P 影子另限 30 分鐘（`DAILY_SHADOW_MAX_MINUTES`），卡住也留時間給 M。`CODEX_TIMEOUT_SECONDS` 預設 300→150。LLM 呼叫因此保證 08:20 前結束，之後只剩寫 DB／畫 HTML（秒級）與行情（20 秒逾時）。codex 版本沒動。production `.env` 沒寫 `CODEX_TIMEOUT_SECONDS`（11/06 部署時確認），新預設生效。手動 `daily prepare`（CLI）不綁截止。
- ⚠️ **E11（11/15 到期）**：重編版莫德納稿沒入選（MarketWatch item 2736 單一來源、改判 world；STAT item 3875 另成一 cluster），回歸條件仍是 skip，xfail 維持。錄音入口 `scripts/record_e11.py` 已接上（`--live` 才呼叫 Codex，上限 5；`--check` 與 `tests/test_e11_replay.py` 只重播，沒有 fixture 就 skip）。👤 11/15 前在 Mac 的 `data/work` 複本錄完並 commit 兩個 fixture，或拿掉 xfail 註明不適用。不要只拿掉 xfail。
- ✅ 全套 380 passed／7 skipped／2 xfailed（基準 363／7／2）。不需要 migration。

## 本次變更（2026-11-01 — 10/31、11/01 兩期 M 組問題修正，`fix/newsroom-1101`）

- ✅ **已部署（2026-11-01 18:00 台北）**：`fix/newsroom-1101` fast-forward 併入 main（`3d78ec1`→`6edfc5e`）並 push。備份 `~/Documents/Developer/Lab/reddit_tracker_backups/fixes-20261101/`（production DB 用 sqlite `.backup`、integrity ok；`.env`、`news_sources.yaml`、newsroom plist 複本）；不需要 migration。只用 `deploy/install_launchd.sh newsroom-reload` 重載 `com.leroy.reddit-tracker.newsroom` 一次（18:00:46），rsshub 未動。
  - log 有 `codex version guard ok: codex-cli 0.166.0`；scheduler Python process 只有 1 個；3 個 job 已註冊。首輪收集 18:00:46 ok 12/12：`cbsnews-world` 30、`abcnews-intl` 25、`bbc-business` 51、`guardian-tech` 32 筆（全部 HTTP 200；首次抓取，含部分舊稿）；停用的 feed 不再抓。
  - 部署前驗證：全套 363 passed／7 skipped／2 xfailed（基準 334／7／2）；DB 複本重算 10/31＋11/01 查核員決定，刪除 21 → 3。編輯會議：在 Lab DB 複本（另用額度檔，非 production）把 11/01 存下的 desk 提示（`llm_records` id 41）裡 13410 的過時高雄代表標題換成 S1 標題，**真 Codex 1 次**，回 `[[18416, 13410]]`，即台北辯論重複會被合併（`confirm_groups` 會接受，見 `tests/test_desk_duplicates.py`）。
  - 👀 **下一個檢查**：11/02 06:00 是第一期套用這些修正——看 `trace`、單一來源稿數、`merged_groups`、`llm_records.purpose`（P 影子撰稿列應為 `shadow`）。
- ✅ **11/01 M 組（12 則：5327 5328 5329 5330 5331 5332 5334 5337 5395 5404 5452 5455）由志晨於 2026-11-01 約 17:22（台北）補核准**；08:35 發行時尚未核准，所以當天只送出標題短訊。
- ✅ **查核員刪過頭**：根因是 `irrelevant_sources` 用 `shared(..., None)` 比標題，句首字（Binance、Oleshky）不算名字、中文標題沒有譯名表名字就比不到；查核員 LLM 每次都回 OK（同一事件）卻不能覆蓋程式。10/31、11/01 共刪 21 個來源，11/01 有 8／12 篇剩 1 家、正文最短 49 字。修正：句首字要包內佐證；可疑來源要 LLM 沒回 OK 才刪，保留的記 `cleared_item_ids`、修稿重驗跳過；數字仍只看程式。重算（`scripts/recheck_factcheck.py`，輸出在 `reddit_tracker-fixes-1101-data/recheck-factcheck.txt`）：21 → 3 個（5330 高雄稿、5455 Microsoft 稿照刪；5330 的央廣台北稿 S2 仍被刪，因 LLM 回 CHALLENGE 時沒有逐來源判斷）。
- ✅ **同一事件見報兩次**：10/31 幣安（國際 14963 中文／科技 14305+16914 英文）是 LLM 提對了、程式確認因譯名表沒有「幣安」剔除 → 確認時加看摘要別名「幣安(Binance)」；11/01 台北辯論（5327／5330）是事件 13410 代表稿為高雄辯論、成員與 S1 卻是台北，LLM 被代表標題誤導 → 編輯會議改給 LLM 看證據包 S1 標題。程式合併、聚合、譯名表都沒改（實驗一方法 C 不變）。
- ✅ **P 影子 `llm_records.purpose`**：額度本來就扣在 `shadow`（M 的 48 格沒被吃），只是撰稿紀錄被 `llm_log_meta(purpose="daily")` 改寫成 daily（11/01：shadow 1、daily 4）；改為記 shadow。
- ✅ **來源**：停用 `reuters-world`／`reuters-tech`／`reuters-business`（401／404，10/29 起 0 成功）、`apnews-top`（403，11/01 03:29 起）、`cw-today`（403，10/30 起；官方 RSS 停在 2021，無替代），設 `keep_items: true`（不再抓、已收的稿照用）；加 `cbsnews-world`、`abcnews-intl`、`bbc-business`、`guardian-tech`（官方 RSS，11/01 中途加入）。七天報告新增「停用來源」表並標中途加入日期；複本預覽在 `reddit_tracker-fixes-1101-data/report-preview.md`（不 commit）。
- ✅ 新測試 29 個（查核員 20、編輯會議 5、影子 1、報表 1、登錄表 2；另改 1 個報表斷言）；全套 363 passed／7 skipped／2 xfailed。細節見 ADAPTATION 文末「10/31、11/01 兩期 M 組的修正」。
- ⚠️ 部署後 11/03 的 `collection report --days 7` 期間是 10/28–11/03：四個替代來源只有 11/01 起的數字（報表會標「11/01 加入」），停用的五個來源列在「停用來源」表。
- 👤 待決定（2026-11-06 已做成旗標，見 `feat/checker-per-source`）：要讓查核員逐來源回報（改 CHECKER schema＋重錄 `1027_t2a_records.json`，需呼叫 Codex）才能救回 5330 S2 這類「同一則 CHALLENGE 裡一個對一個錯」的情況；同語言重複仍靠 LLM 第二意見，LLM 沒提就可能重複。

## 本次變更（2026-10-31 — Codex CLI 版本守門，`feat/codex-version-guard`，已部署）

- ✅ **已併入 main 並部署（2026-10-31 08:59 台北，main `3d78ec1`）。**

- ✅ CLI 由 ChatGPT.app `0.164.0-alpha.11.1` 改為 Homebrew cask `0.166.0`：`CODEX_BIN` 預設 `/opt/homebrew/bin/codex`、`DAILY_MODEL_VERSION` 預設 `gpt-6.1-sol | codex-cli 0.166.0 | reasoning_effort=low`（本機 `codex --version` 實測 0.166.0）。
- ✅ 版本守門 `llm/codex_version.py`：排程啟動與每天 06:00 準備前比對 `codex --version` 與鎖定版本；不一致或讀不到記 ERROR＋Telegram 警告，不擋出刊。`llm_records.model_version` 改記實測 CLI 版本（讀不到寫 `codex-cli unknown(locked 0.166.0)`）。replay 的 `request_hash` 不含 CLI 版本。細節見 ADAPTATION「Codex CLI 改用 Homebrew＋版本守門」。
- ⚠️ **11/20 凍結前不要 `brew upgrade codex`**；Homebrew codex 是 cask，`brew pin` 沒用。
- ⚠️ 部署時 production `.env` 若有寫 `CODEX_BIN`／`DAILY_MODEL_VERSION` 要一起改（或刪掉用預設）；重啟 newsroom 後 log 應有 `codex version guard ok: codex-cli 0.166.0`。
- ✅ 全套 334 passed／7 skipped／2 xfailed（worktree 沒有母本快照，多 3 個 skip）。

## 目前狀態（2026-10-30，`mas-handbook`：手冊步驟 0–11 的程式都在）

- ✅ PR #1（`cursor/mas-steps-6-11-cc77`）已併入 `mas-handbook`。內容：MAS 資料表／migration `b8d4f0a17c33`、編排器、回放頁、核准、盲計匯出。M 組改用步驟 4 版面：三內版各 4 篇共 12 篇、頭版 6 則從中標記、其他版只出標題短訊；三位分版主編各提案 1 次。P／M 共用 `select_articles`。`llm_records` 統一由 `llm/records.py` 寫，migration 相容母本那張舊表。
- ✅ 真 Codex（只在 `data/work` 複本，額度檔 `data/work/llm-quota-merge.json`、上限 40）：本階段 **38 次 subprocess 嘗試，全部 ok**。每次都寫了 `llm_records`；目前複本裡留 36 筆，修正前那次 T1／T3 試跑的 2 筆因為重建複本被覆蓋（腳本已改成會保留，回應內容留在 log）。
  - T2a（E01）3 次；
  - MAS 整期 28 次＋修稿 2 次＋總編提示修正後 1 次；
  - T1（E06）＋T3（8→6）2 次（另有 2 次是修正前的試跑，抓到總編決定的缺陷）。
  - 錄音都可離線重播：回歸集 0 miss、MAS 整期與 T1／T3 0 次真呼叫重現。
- ✅ 全套 287 passed／4 skipped／2 xfailed。2 個 xfail 都是 👤：連續 3 天 live＋試刊日期公告（方案 B：11/04–11/06、11/06 公告；手冊原為 11/30 關卡）、真實盲計對照表 SHA-256（方案 B：試刊期間每天交 B 前；手冊原為 12/01 前）。tag `gate-1115` 已打並於 10/30 push 到 origin，見 ADAPTATION「PR #1 整合」。
- ✅ 已部署（2026-10-30 10:05 台北，依使用者同意）：`mas-handbook` fast-forward 併入 main（`42a3cf5`→`bd84bcd`）；全套 287 passed／4 skipped／2 xfailed；備份 `~/reddit_tracker_backups/deploy-20261030-1003/`（DB integrity ok＋`.env`）；先在備份複本演練，再把 production Alembic 由 `a6c9e2f31d84` 升到 `b8d4f0a17c33`（舊 `llm_records` 1 筆保留）；`.env` 加 `DAILY_MODE=mas`、`LLM_DAILY_LIMIT=60`（舊 `GEMINI_DAILY_LIMIT`／`GEMINI_QUOTA_STATE_PATH` 原本就不在 `.env`）；只重啟 `com.leroy.reddit-tracker.newsroom`，三個 job 已註冊，rsshub 未動。部署時沒有呼叫 Codex、沒有試編或發送。
  - 👀 10/31 起 06:00 以 M 組準備（約 30 次 Codex，額度 60）、08:35 發行；MAS 未核准的稿只發標題短訊，要全文需先 `uv run python -m reddit_tracker.daily approve --story ID --by 名字`。
- ✅ 方案 B 程式（2026-10-30，`mas-handbook`，未部署）：`DAILY_MODE=mas`＋`DAILY_SHADOW_ENABLED=true` 時 06:00 由 `prepare_with_shadow` 先跑 P 影子（建快照、編輯會議只開一次）、M 再從同一份快照跑；P 影子額度記在用途 `shadow`，上限 `DAILY_SHADOW_LLM_LIMIT=12`（M 至少保有 48 格）；兩組都有稿就把盲計稿／抽查稿匯出到 `annotation/YYYY-MM-DD/`（對照表在 `annotation/_private/YYYY-MM-DD/`）。影子失敗只記 log。設計與估算見 ADAPTATION「P 影子自動排程」。全套 302 passed／4 skipped／2 xfailed。
- ✅ 每日盲計抽樣（2026-10-30，`mas-handbook`，未部署）：`blind.sample_day` 從 P、M 都有寫正文的事件（同 `keeper_cluster_id`、送核准前版本、HOLD 照抽）用 `Random(f"{BLIND_SEED}-{日期}")` 抽 8 篇、4 P／4 M；不足 8 全抽、0 個只寫 README.txt；計數表改七類；`mapping.json` 位元組可直接 `shasum -a 256` 對 `mapping.sha256`。規則見 ADAPTATION 步驟 11。全套 315 passed／4 skipped／2 xfailed。
- ✅ 對照表移出當天資料夾（2026-10-30，`mas-handbook`，未部署）：`mapping.json` 改寫到 `annotation/_private/YYYY-MM-DD/`，`annotation/YYYY-MM-DD/` 只剩 blind.txt、spot-check.txt、mapping.sha256（或 README.txt），可整個交給 B；`analyze_blind_count.py` 改用 `--date`（`--mapping` 相容），用當天 `mapping.sha256` 強制驗證，舊位置或缺檔直接停。全套 319 passed／4 skipped／2 xfailed。
- ➡️ 下一步（人工／日曆；方案 B 試刊提前，👤 老師尚未確認，對照表見 ADAPTATION「🔁 時程提前（方案 B）」）：
  - 11/03 從 production 做唯讀快照，正式抽實驗一配對；11/04 交 A、B。約 11/03 打 `exp1-frozen`（仍在 11/12 test 標註之前）。
  - 11/04 前部署方案 B 程式，production `.env` 加 `DAILY_SHADOW_ENABLED=true`（`DAILY_MODE=mas` 已設）。
  - 11/04–11/06：`DAILY_MODE=mas` 連續 3 天在 07:00 前產出頭版＋三內版到待審（P 同時以影子模式跑，確認兩組合計 ≤ 60 次），日期寫進週報（手冊步驟 10）。
  - 11/06：用其中一天試匯出盲計（手冊步驟 11），公告試刊日期，寫 `docs/weekly/trial-dates.md` 並告知 A、B。
  - 11/08 前：B 拿到七類錯誤計數練習（老師）。
  - 11/09–11/16 之間出 7 期七日試刊＋實驗三（預定 11/09–11/15；失敗照實記錄；手冊步驟 12）。盲計對照表雜湊每天交給 B 之前 commit（種子 `BLIND_SEED=20261201` 與抽樣／分析腳本已 commit，數字不改）。
  - 11/17–11/18 實驗二；11/20 打 `final-1120` 功能凍結（手冊原為 12/15 `final-1215`；手冊步驟 13）。報告與發表仍在 2027 年 1 月初。
- ℹ️ 2026-10-30 docs：README／簡介重寫（v2 綜合日報＋MAS），`docs/v5/README.md`、`DAILY_EDITION.md` 開頭、CLAUDE.md／AGENTS.md 概述、`pyproject.toml` description 同步；程式行為未改。

## 更早的紀錄

- 2026-09-13 – 2026-10-29：[`docs/archive/PROGRESS_2026-09_to_10-29.md`](docs/archive/PROGRESS_2026-09_to_10-29.md)
- v4（已廢棄）：[`docs/archive/PROGRESS_v4.md`](docs/archive/PROGRESS_v4.md)
