# Reddit Tracker — 專案進度（現為 v2.0 AI 綜合日報）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 現行企劃見 `docs/AI_NEWS_COMPANY_PROPOSAL.md`、規格入口見 `docs/v5/README.md`。
> 2026-10-27 以前的段落是 v4／v5 歷史紀錄，裡面提到的 bot、scrapers、services、v5 newsroom 模組都已移除；v4 的段落已搬到 `docs/archive/PROGRESS_v4.md`。
> 下面各段裡的「➡️ 下一步」是當時寫的，現況一律以本節「下一步」為準。

**Last updated:** 2026-11-12（`feat/newsroom-3d`：手冊對照盤點＋3D 編輯室回放，已併入 main `7f72c69`，**服務沒有重載、沒有 push**）；上次部署 2026-11-06 15:54（`fix/newsroom-1106`，main `f252c8b`）

## 本次變更（2026-11-12 — 手冊對照盤點＋3D 編輯室，`feat/newsroom-3d`）

worktree `~/Documents/Developer/Lab/rt-wt-3d`。查證用 production DB 唯讀複本，沒有呼叫 Codex、沒動 production。細節見 ADAPTATION「2026-11-12 手冊對照盤點與 3D 編輯室」。

- ✅ 3D 編輯室回放 `/daily/<date>/newsroom/office`（`daily/replay.py`、`office_page.py`、`office.html`）；日報頁右下與表格版回放都有入口。three.js 從 jsDelivr 載入，放一份到 `reddit_tracker/daily/vendor/three.module.js` 就能離線。
- ✅ 補齊：`agent_messages.llm_call_id`、訊息真實時間、訊息結案、報頭期號／台北出刊時間、「多來源」標籤、來源列時間、頁尾聲明、盲計雜湊（11/09–11/12）、`scripts/trial_metrics.py`、週報草稿 `docs/weekly/2026-11-10.md`。
- ⚠️ 2026-11-12 晚上依志晨指示 fast-forward 併入 main，但 **newsroom 服務沒有重載**：常駐 process 還是舊程式，06:00 出刊照舊。新程式（訊息時間、llm_call_id、結案、報頭）要等 `deploy/install_launchd.sh newsroom-reload` 或服務自己重啟才生效；試刊到 11/15，👤 決定什麼時候重載。不改提示詞與 `request_hash`，不需要 migration。3D 回放用 `uv run python -m reddit_tracker.web` 就看得到，不用重載。
- ⚠️ **11/07–11/12 的 M 組稿是 11/12 11:03 一次補核准的**（晚於各期 08:35 發行）；試刊 11/09–11/12 四期讀者都只收到標題短訊。
- ⚠️ **實驗一的 100 組是 AI 工具標的**（`annotation/exp1/exp1_resolution.md`），手冊不允許；要標註員 A、B 本人重標。
- ⛔ 還沒有：實驗一結果計算腳本、實驗二三組執行腳本。
- 全套 410 passed／7 skipped。

## 下一步（2026-11-06 現況）

日期都是方案 B，👤 老師尚未確認，見 [`docs/weekly/trial-dates.md`](docs/weekly/trial-dates.md)。依期限排：

1. 👤 **實驗一交件**（志晨）：快照 `data/snapshots/2026-11-05.db`（11/05 23:25，原訂 11/03），抽樣 commit `5f31fab`，A 100 組／B 30 組、沒有不足的層，見 [`docs/eval/EXP1_SAMPLING.md`](docs/eval/EXP1_SAMPLING.md)「實際執行紀錄」。要做：檢查輸出 → 自己打 `exp1-frozen` → xlsx 交 A、B（`_private/` 不給）。A、B dev 標註 11/07、test 標註 11/12；結果 11/22 前寫進 `docs/eval/`。⚠️ 不要用 `fix/newsroom-1106` 重跑抽樣。
2. 👤 **請老師確認** `trial-dates.md` 的時程（試刊 11/09–11/15、實驗二 11/17–11/18、11/20 `final-1120`）與用本機 Codex 當 LLM（手冊 6.9 第 1 條要正式 API，模型 11/15 前定案），並告知 A、B。
3. 👤 **11/08 前**：B 拿到七類錯誤計數練習（老師）。
4. 👀 **`fix/newsroom-1106` 已部署（11/06 15:54）**：11/07 06:00 是第一期套用——看準備是否在 `DAILY_PREPARE_DEADLINE` 前結束、分版與來源列是否正確。
5. 👤 **`FACT_CHECKER_PER_SOURCE` 預設關閉**（程式已併入 `main`，見 `docs/pr/checker-per-source.md`）：**11/09 試刊前**決定要不要開；開了會改實驗二 (c) 組，最晚 11/17 前定案。要有逐來源的真錄音另需 Codex 2 次（最壞 4）。
6. 👤 **E11**（11/15 前）：錄音入口與 replay fixtures 已在 `main`（`scripts/record_e11.py`、`1027_e11_evidence.json`／`1027_e11_records.json`）。新的 replay 測試可離線跑；回歸重編條件仍 skip，原 xfail 維持。11/15 前決定要不要拿掉原 xfail（不要只刪 xfail 而不處理條件）。否則 `test_overdue_cases_are_not_xfail` 11/15 起失敗。
7. 👤 **試刊 11/09–11/15 每天**：06:00 準備後核准 M 組稿；交 B 盲計資料夾之前用 `scripts/collect_blind_hashes.py --write` 把當天雜湊寫進 `docs/eval/blind_mapping.sha256` 並 commit（步驟見 trial-dates.md）。
8. 實驗二 11/17–11/18（A 11/17 中午前選 15 篇正常稿）。
9. 11/20 打 `final-1120` 功能凍結；之前不要 `brew upgrade codex`。

- ℹ️ `docs/weekly/trial-dates.md` 已寫，`test_three_live_mas_days_and_announced_trial_dates` 會變 XPASS；`blind_mapping.sha256` 還沒有（試刊才有資料）。兩個 xfail 等老師確認時程、第一個雜湊 commit 後再拿掉。
- ⚠️ 11/04、11/05 M 組稿 08:35 前沒核准，讀者只收到標題短訊；11/06 排定 06:25 由自動化流程核准（志晨授權）。報告照實記。

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

## 目前狀態（2026-10-27 起）

- **線上只跑 v2.0 綜合日報。** LaunchAgent 只剩 `newsroom`（`reddit_tracker.newsroom.scheduler`：收集＋聚合每 15 分鐘、06:00 準備、08:35 發 Telegram）與 `rsshub`。
- **程式結構：** `collection/`（收集、聚合、報表）、`daily/`（評分、撰稿、渲染、發行）、`llm/{codex,gemini}.py`、`newsroom/{scheduler,deploy}.py`、`web.py`（只看日報）、`seeds/news_sources.*`、`scripts/probe_news_sources.py`。
- **驗收：** 收集七天驗收 10/27–11/02，11/03 用 `uv run python -m reddit_tracker.collection report --days 7 --out docs/collection_acceptance_2026-11-03.md` 出報告。後續時程依 10/28 老師手冊（取代企劃 v2.0 的 11/30 交付、11/13–11/19 試刊），10/30 起再改成方案 B（👤 老師尚未確認）：11/04–11/06 連續 3 天 live（手冊原為 11/30 關卡）、11/09–11/16 間七日試刊（原 12/01–12/10）、11/20 功能凍結（原 12/15）。
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
- ✅ 步驟 4（10/30）：`daily/sections.py`＋`seeds/section_rules.yaml` 改寫分版（兩岸→國際／台灣、財經→台灣／國際／科技、生活版教育社會→台灣），`SECTION_QUOTAS={taiwan:4, world:4, tech:4}` 一期 12 篇，頭版 6 則從中標記，內版放頭版連結；科學／生活／文化／體育只出頭版標題短訊（`stats.briefs`，不呼叫 LLM）。E14 通過。重錄錄音用真 Codex 4 次（累計 20），fixture 20 筆、82 KB。全套 243 passed／4 skipped。驗證：`scripts/validate_step4_1027.py`。
- ⚠️ 10/27 兩岸稿全數改寫進內版但分數沒擠進國際版前 4；`cursor/mas-steps-6-11-cc77` 合併時 run.py／render.py 的衝突點見 ADAPTATION 步驟 4。
- ✅ 步驟 5（10/30）：實驗一抽樣 `reddit_tracker/eval/exp1.py`＋`scripts/sample_exp1.py`（種子 20261104，commit `cff09fa`），方法 A＝舊門檻參數＋merged_groups 重播、方法 C＝現行規則＋desk；分層 60＋40、dev／test 各 50、B 複標 30、無洩漏欄位，私有對照在 `annotation/exp1/_private/`。母本試抽：dev 50 組抽滿、test 0（資料還沒發生）。操作說明 `docs/eval/EXP1_SAMPLING.md`。全套 258 passed／4 skipped。
- 👤 **11/03 要做**：開發者從 production 做新的唯讀快照 `data/snapshots/2026-11-03.db`，跑 `uv run python scripts/sample_exp1.py --db data/snapshots/2026-11-03.db`，11/04 把 `annotation/exp1/exp1_A_100.xlsx` 給 A、`exp1_B_30.xlsx` 給 B（`_private/` 不給）。
- ➡️ 下一步：步驟 6–7 由另一個分支（`cursor/mas-steps-6-11-cc77`）負責；本分支下一個是 11/03 正式抽樣（人工）與 E11（步驟 9 文稿編輯）。

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
- ➡️ 下一步：建立來源登錄表（YAML，首批 120+ 來源）並本機架設 RSSHub，逐一實測可用性；10/29 起收集層（`source_items`、去重、事件聚合、來源健康）與七天收集驗收。時程（當時排定 11/12 前端到端出刊、11/13–11/19 七天試刊、11/30 交付；已由 10/28 老師手冊取代，10/30 再改成方案 B，👤 老師尚未確認）：11/04–11/06 連續 3 天 live、11/06 公告試刊日期、11/09–11/16 間七日試刊（預定 11/09–11/15）、11/20 功能凍結（`final-1120`）。

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

## 歷史（v4，已廢棄）

2026-08-19 及更早的 v4 Reddit Tracker 段落（服務暫停紀錄、緣由、M1–M8 里程碑、Public JSON、subreddit /new、v3 坑與 v4 設計決策）已原封不動搬到 [`docs/archive/PROGRESS_v4.md`](docs/archive/PROGRESS_v4.md)。程式 2026-10-27 已刪除，只供查歷史。
