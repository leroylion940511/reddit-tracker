# 執行手冊實作：使用者指令與改編紀錄（mas-handbook 分支）

> 正式要求：`docs/HANDBOOK_2026-10-28.md`（老師的「AI 新聞公司專題：執行手冊（學生版）」）。
> 本檔記錄使用者（張志晨）對實作的**強制指令**，以及每一步「做完的標準」的達成／改編／留給人工狀況。每完成一步就更新本檔下方的「逐步狀態」。

## 強制指令（binding）

1. **只在 `mas-handbook` 分支工作。** 工作目錄是 git worktree `/Users/leroy/reddit_tracker-mas`。不碰 `main`、不 push、不 merge、不 force、不 rebase 已有 commit。每一步（或子步驟）一個以上本地 commit，訊息清楚。
2. **Production 絕對不碰。** `/Users/leroy/reddit_tracker/`（main worktree）裡的 `reddit_tracker.db`、`*.backup*`、`.env`、`newsroom.log` 是線上正式環境，由 launchd 服務 `com.leroy.reddit-tracker.newsroom` 從那個目錄執行。不得讀寫那裡的 DB（唯一例外：已由協調者做好的唯讀母本）、不得改那裡的檔案、不得 `launchctl`／`deploy/install_launchd.sh` 任何會停止、重載、安裝、移除服務的指令（`status` 這種唯讀查詢可以）。不得 commit 任何 secret 或 `.env`。
3. **LLM 一律用本機 Codex CLI**（`reddit_tracker/llm/codex.py` 的 `CodexClient`，commit 42a3cf5），手冊寫 Gemini 的地方都改成 Codex。手冊中 Gemini 專屬的要求要**改編到 Codex 呼叫上**：
   - 額度依「模型」計數（Codex 的 model 字串，例如 `gpt-6.1-sol`）：同一模型所有用途共用一個每日計數，預設每日上限 60（沿用手冊的實驗條件），P＋M 加總不超過上限；停用的用途不建 client（不要把上限設 0）。Gemini client 可以保留程式碼，但日報不再建立它。
   - **每一次 Codex subprocess 嘗試**（含重試）都寫一筆 `llm_records`：`request_hash`（sha256(system prompt＋prompt＋model＋schema)）、`prompt_text`、`response_text`、`latency_ms`、`ok`、`error`、`role`、`run_variant`、`edition_date`、`story_id`、完整模型版本字串（Codex model＋CLI 版本／reasoning effort）。
   - **Replay**：用 `request_hash` 從 `llm_records` 找回錄好的回應重播；找不到就直接失敗，不得默默呼叫真模型。
   - **測試永遠不呼叫真 LLM**（不得執行 codex binary、不得連網）。用 fake／replay client，並加一道測試防護：測試中若有人嘗試執行 codex subprocess 就失敗。
   - 網頁備援（web_chat）要停用：commit 2d95c07 已刪掉 `web_chat.py`；確認沒有任何 `web` provider 或 fallback 路徑殘留，設定上 `LLM_PROVIDER` 不能是 `web`、fallback provider 是 `fake`（若設定不存在，就新增只允許 `codex`／`gemini`／`template`／`fake` 的驗證，並寫測試）。
   - 手冊說「真的呼叫 Gemini」才能產生的 trace（步驟 8 的 E01、步驟 9 的 T1／T3 示範），改成**真的呼叫 Codex**，但只在 `data/work/*.db` 複本上、只為產生示範 trace，呼叫次數盡量少；所有呼叫都進該複本的 `llm_records`，之後可用 replay 重播（回歸測試用 replay fixture，不用真模型）。
4. **資料庫**：唯讀母本 `data/snapshots/2026-10-27.db`（10/29 18:46 台北時間由協調者用 SQLite online backup 從 production 複製；內容涵蓋到 10/29，所以重編 10/27 時要依手冊刪掉 10/27 06:00 之後的素材）。sha256 記在 `data/snapshots/2026-10-27.db.sha256`。永遠不改母本；實驗一律 `cp` 到 `data/work/<名字>.db`，用 `DATABASE_URL=sqlite:///data/work/<名字>.db` 跑。`data/`、`*.db`、`annotation/` 不進 repo。
5. **只做開發者的程式／工具工作**（第 5 章步驟 0–11）。人類才能做的不做、不假造：標註員的標註、實際 7 日試刊與連續 3 天 live 出刊、口試報告／簡報、需要真實日曆天數的 live 發行。這些要把工具做好、留下清楚的操作說明，並在本檔標「留給人工」。
6. 每一步結束：該步「做完的標準」能自動驗證的都要驗證；`uv run python -m pytest -q` 全綠；更新本檔的逐步狀態；commit。`PROGRESS.md` 在有實質狀態改變時更新（照 CLAUDE.md 規則）。
7. 已知與手冊前提不同的現況（手冊寫於 `codex/ai-newsroom-foundation` 分支狀態）：舊 Reddit job、`web_chat.py`、v4 scheduler、問答（qa.py）已在 commit 2d95c07 移除；`codex/ai-newsroom-foundation` 已等於 `main`（42a3cf5）。遇到這類「已經做到」的項目，寫測試證明並在本檔註明，不要重新加回舊程式。

## 逐步狀態

（每一步完成時由實作者填寫：做完的標準 ✅／🔁改編（怎麼改）／👤留給人工（為什麼）／⛔受阻。）

### 步驟 0｜第一天先做的事（2026-10-29 完成）

- ✅ `data/snapshots/2026-10-27.db` 存在，而且不在排程的寫入路徑上：協調者 10/29 18:46 用 SQLite online backup 從 production 複製，放在 mas worktree（排程只寫 `/Users/leroy/reddit_tracker/reddit_tracker.db`），檔案權限 `r--r--r--`，`shasum -a 256 -c data/snapshots/2026-10-27.db.sha256` OK。🔁 母本內容涵蓋到 10/29（不是 10/27 當天的檔），所以匯出 fixture 時以那期 `prepared_at`（10/26 22:00 UTC＝10/27 06:00 台北）為 `first_seen_at` 截止。
- ✅ 兩個 fixture 都存在：`scripts/export_1027_fixtures.py`（`mode=ro&immutable=1`，可重跑、輸出穩定）產生 `tests/regression/fixtures/1027_groups.json`（2,771 cluster／3,899 篇；截止前全部有素材的 cluster 都收，檔案 68 KB 不必再縮到 72 小時窗）與 `1027_merges.json`（17 組）。🔁 `merged_groups` 實際是 LLM 回的兩兩配對、會重疊（例如 1707／1717／2420／2321 六組），所以逐組一一轉成素材 id、保留順序，不先求連通分量，重播時照 `apply_merges` 原樣處理。cluster id 版本與追溯資料另存 `1027_meta.json`（母本 sha256、截止時間、merged_groups 原值、42 則刊出稿的 cluster／merged ids、E01 追溯）。腳本會驗證所有刊出稿／合併用到的 cluster 都在分組裡，且每則刊出稿的出處 URL 都落在截止前的分組內。測試 `tests/regression/test_1027_fixtures.py` 只讀 fixture，不依賴母本。
- ✅ 週報寫了 E01 是在哪一步混進來的：`docs/weekly/2026-11-03.md`。結論：跨語言合併 `find_same_events` 錯併（AP source_item 1053 在英文 NFL cluster 403，merged_groups `[403, 410]` 把它併進中文塞爾維亞 cluster 410；英文塞爾維亞 cluster 405 反而沒併＝E07），與協調者查證一致，並以回歸測試鎖住。
- ✅ `git status` 看不到任何 `.db` 檔：`.gitignore` 原本已有 `data/`、`*.db`，本步補上 `annotation/`；`git check-ignore` 確認三者生效。
- ✅ `git tag` 看得到 `baseline-pipeline`：協調者已打在 `42a3cf5`（`git rev-parse 'baseline-pipeline^{commit}'` 驗證）。
- 🔁 `main` 已更新：**main 已是最新：已滿足**。`main`、`origin/main`、`codex/ai-newsroom-foundation` 都是 `42a3cf5`，依強制指令 1 不合併、不動 main。

### 步驟 1｜停舊排程、關社群來源、改額度、關網頁備援（2026-10-29 完成）

- 🔁 **三個舊 job 不再執行；v4 scheduler 仍是停用**：舊程式已在 commit 2d95c07 刪除，不加回。證據（協調者唯讀查 production，本步沒有執行 `launchctl`／`install_launchd.sh`）：`newsroom.log` 中 `newsroom_candidate_discovery` 最後一次執行 2026-10-27 01:09，之後 16:55 重載只 `Added` `newsroom_source_collection`、`daily_prepare_edition`、`daily_publish_edition`；`~/Library/LaunchAgents` 只剩 newsroom 與 rsshub 的 plist，v4 scheduler 已移除（`deploy/install_launchd.sh status` 也只列這兩個）。程式面照手冊：`config.LEGACY_JOBS_ENABLED`（預設 false）；`newsroom/scheduler.py` 的 `LEGACY_JOB_IDS` 列出三個舊 job 名稱，`build_scheduler` 結尾檢查不得註冊任何一個；設 true 也只記 warning「removed in commit 2d95c07」、不復活舊程式。`tests/test_newsroom_scheduler.py` 斷言 job 清單恰為三個新 job（true／false 皆然）。
- 🔁 **額度依模型計數，加總 ≤ 60**（手冊的 flash-lite 改成 Codex model 字串）：新增 `llm/quota.py` 的 `ModelQuotaGuard`，鍵＝model，所有 `purpose` 共用一個每日計數，`LLM_DAILY_LIMIT` 預設 60，太平洋時間換日，跨 process 用 `LLM_QUOTA_STATE_PATH` state 檔＋檔案鎖。`CodexClient` 每次 subprocess 嘗試前扣一格（額度用完就不執行 codex），失敗重試 `CODEX_MAX_RETRIES=1`（機密外洩不重試）；`GeminiQuotaGuard` 改為 `ModelQuotaGuard` 子類、依模型計數；`GEMINI_MAX_429_RETRIES=1`、`WRITE_ATTEMPTS=2`，一版最壞 4 格。額度用完（`QuotaExhausted`）該版直接退模板稿、不再重試。停用的用途不建 client：`_default_client` 只建被選用的 provider，日報預設（codex）不建 `GeminiClient`（有測試）；`GEMINI_DAILY_LIMIT`、`GEMINI_QUOTA_STATE_PATH` 改名為通用的 `LLM_DAILY_LIMIT`、`LLM_QUOTA_STATE_PATH`（舊鍵在 `.env` 會被忽略）。手冊「問答 flash 另外算」不適用：問答已移除。測試：conftest autouse 把 state 檔改到 `tmp_path`，測試跑完確認 `/tmp/reddit-tracker-llm-quota.json` 不存在。
- ✅ **24 個社群來源 `enabled: false` 且都有 `notes`，全部測試通過；已停用來源的舊素材不再進入聚合與選題**：實際檔案正好 17 Reddit＋6 PTT＋1 Threads＝24 個（另 2 個 Dcard 原本就停用），全加 `notes: "2026-10-28 停用：社群來源，不在 MVP"`。登錄表現為 158 個來源、啟用 105 個（手冊寫 156／127→約 103，差異是 10/27 加的兩個遊戲來源）。`tests/test_news_sources.py` 改成允許 social 版全停，並斷言 24 個的組成。排除「來源已停用」的素材：`SourceRegistry.disabled_source_ids()`；`cluster_recent_items(disabled_sources=…)` 不聚合、既有事件訊號不算它們；`score_candidates(disabled_sources=…)` 只由停用來源組成的事件不進候選、投票與升溫不算它們；`build_evidence` 不放進證據包。排程與 CLI 都傳入。在 `data/work/step1-social.db`（母本複本，刪掉 `first_seen_at > 2026-10-26 22:00 UTC` 的 18,774 篇並重算事件）重現 10/27 選題：改前 42 則、社群版 2097（E13 Threads）／2436／2485，與當期刊出完全一致；改後 39 則、社群 0 則、E13 不在候選。`render.py`：`MVP_SECTIONS=("taiwan","world","tech")`，非 MVP 版沒稿時印「本版未開放」。🔁 非 MVP 版若仍有稿照常顯示——十版併三版、配額 12 篇是步驟 4 的工作，步驟 1 先不讓稿件消失。
- 🔁 **`gemini_fallback_provider=fake`，`LLM_PROVIDER` 不是 `web`**：`web_chat.py`、`LLM_PROVIDER`、`gemini_fallback_provider` 在現況都不存在（grep 無殘留，只剩 PROGRESS 歷史段落）。改為：`config.LLM_PROVIDERS=("codex","gemini","template","fake")`，`DAILY_WRITER` 驗證只允許這四個（`web` 啟動即報錯），`prepare_daily(writer_mode=…)` 也檢查；新增離線 `llm/fake.py`（不連網、不扣額度）。不另外新增 fallback 設定：現有唯一的後備是程式內建的模板稿（不呼叫任何模型），舊 `.env` 若殘留 `LLM_PROVIDER=web`／`GEMINI_FALLBACK_PROVIDER=web` 會被 `extra="ignore"` 忽略且沒有程式讀（有測試）；刻意不讓舊鍵造成啟動失敗，避免日後部署時 production 因殘留舊鍵停擺。`.env.example` 同步（無 `web`、`LLM_DAILY_LIMIT=60`、`GEMINI_MAX_429_RETRIES=1`、`LEGACY_JOBS_ENABLED=false`）。
- ℹ️ 規格同步：`docs/v5/DAILY_EDITION.md`（額度、provider、停用來源、介面）、`docs/v5/CLUSTERING.md`（`disabled_sources`）。全套 89 passed。

### 步驟 2｜建回歸集（2026-10-29 完成）

- ✅ **15 個錯誤案例都有測試檔，每個都有 `due`**：`tests/regression/cases/E01.json`…`E16.json`，欄位 `case_id`、`edition`、`is_error`、`event_hint`、`error`／`stage`／`fix`（照 4.2 表）、`expected`、`due`，以及可機器判斷的條件（標題都從母本查的真實標題，`test_case_titles_exist_in_fixture` 驗證）：`must_not_contain_titles`（E01–E05）、`must_merge_titles`（E06、E07）、`name_glossary`（E08）、`reprint_pairs`（E10，六組［原稿, 轉載］，發布時間差都在 2 小時內）、`headline_must_not_match`（E11）、`arxiv_rules`（E12）、`must_not_publish_titles`（E13）、`expected_section`（E14）、`market_stale_label`（E15）、`single_source_notice`（E16）、`text_must_not_contain`（E03–E05 的正文部分）。`test_case_files_cover_handbook_table` 斷言 15 個錯誤案例、到期 11/04 九個／11/08 三個／11/15 三個與 4.2 表一致。E09 另存為 `is_error: false`、`due: null` 的非錯誤案例（`non_contradiction`：收盤 14%／開盤 17%），不計入 15，留給 T2 反駁測試。每個條件另有 `test_detects_original_error`：在 10/27 實際刊出的版面（`fixtures/1027_edition.json`）上必須抓到錯，證明條件本身有效（全部通過）。
- ✅ **測試可以離線跑，不呼叫 Gemini（也不呼叫 Codex）**：
  - 離線 fixture `fixtures/1027_items.json.xz`（667 KB，3,898 篇：截止前收到、在第一次聚合 72 小時窗內的素材，摘要截 400 字）＋ `1027_edition.json`（當期 42 則與數據欄），由 `scripts/export_1027_fixtures.py` 從唯讀母本（`mode=ro&immutable=1`）匯出，輸出逐位元穩定；母本在本機時 `test_fixtures_match_snapshot` 重新匯出比對，沒有母本就 skip。母本雜湊仍 OK。
  - Runner `tests/regression/rebuild.py`：在 pytest tmp 目錄建 SQLite，全部走正式程式碼重編 10/27（`now`＝10/26 22:00 UTC）。`find_same_events` 用 `1027_merges.json` 重播（素材 id 對回新 cluster id）；撰稿等其他 LLM 請求走新的 `llm/replay.py`（`request_hash`＝sha256(system＋prompt＋model＋schema)，`ReplayClient`、`load_records` 支援 JSON 與 `llm_records` 表），錄音檔 `fixtures/1027_llm_records.json` 目前不存在，找不到就記下 miss，需要稿件文字的條件直接 `pytest.fail`（不會改呼叫真模型）；數據欄用當期記錄的證交所數值重播。整個回歸集約 5 秒。
  - 全域防護（`tests/llm_guard.py`，`tests/conftest.py` 的 `pytest_configure` 安裝）：攔 `subprocess.Popen`、`os.system`／`posix_spawn`／`exec*` 執行 codex，攔 requests 與 DNS 連 `generativelanguage.googleapis.com`；攔到丟 `pytest.fail`（BaseException，程式內的 `except Exception` 吞不掉），且每個測試結束再檢查紀錄。`tests/test_llm_guard.py` 11 個測試（含真的 `CodexClient` 被擋、被吞掉仍判失敗、其他 subprocess 不受影響）。
- ✅ **到期的案例全部通過；沒到期的標 `xfail`**：今天 10/29 沒有到期案例。案例檔的 `xfail: {條件: 原因}` 決定哪些條件以 `xfail(strict=True)` 跑：修好後會 XPASS 而失敗，提醒刪掉那一條；`test_overdue_cases_are_not_xfail` 在 `due` 當天起若還掛 xfail 就失敗（手冊「到期後拿掉」）。目前結果：15 xfailed（都已用 `--runxfail` 確認是真的錯，不是程式壞掉）、E13 通過、1 skipped（E05 正文條件：重編後 SpaceX 單一來源稿沒見報，不適用）。
  - 已通過、不掛 xfail：**E13**（步驟 1 停用社群來源後 Threads 貼文不再入選）、**E05 `must_not_contain_titles`**（PTT 已停用，不再進聚合；聚合本身的修正仍由 E03／E04 把關）。
  - 掛 xfail：E01–E04、E06、E07、E10（步驟 3 聚合／證據包／轉載）、E12、E15、E16（步驟 3 程式規則）、E14（步驟 4 分版）、E08、E11（步驟 3 譯名表＋步驟 9 文稿編輯）；所有文字條件（E03–E05 正文、E08、E11、E12、E16）另外需要錄好的回應。
- 🔁 **重編方式**：手冊 3.8 是清空後一次重新聚合；但一次重聚和線上的增量結果不同（試過：E03 的 Block／瑞士就重現不出來，回歸集會在修之前就「通過」）。所以 runner 照線上當時的聚合時間表逐輪聚合：10/26 22:53（台北）首輪（PROGRESS 記錄的聚合上線時間），之後每輪收集完立刻聚合（取每輪素材的最晚 `first_seen_at`，共 15 輪）。這樣重編版重現了 E01、E02、E03、E04、E06、E07、E10、E14。步驟 3.8 的週報前後對照仍照手冊在 `data/work/1027_rebuild.db` 一次重聚。重編用的是**現在的**程式與登錄表（社群來源已停用），所以不會完全等於當期。
- 🔁 **「到期後才通過」與錄音的相依**：E03–E05 正文、E12、E16（11/04 到期）的文字條件需要撰稿輸出，但 `llm_records` 與錄音是步驟 7（11/08）。步驟 3 修完這些程式規則時，要先在 `data/work/*.db` 複本用 Codex 錄一次（照強制指令 3，次數盡量少）並匯出成 `fixtures/1027_llm_records.json`（`[{request_hash, response_text, ok}]`，hash 一律用 `llm/replay.request_hash`），才能拿掉這些 xfail；錄音只對當時的 prompt 有效，之後改到證據包或提示詞要重錄。E08、E11 到期（11/15）前同理。
- ℹ️ 程式變更：`daily/run.py` 拆出 `plan_edition()`（評分→編輯會議→選題→證據包）與 `story_evidence()`，`prepare_daily` 新增 `writer=` 注入（回歸集用，不找 codex binary），行為不變；規格 `docs/v5/DAILY_EDITION.md` 介面段已同步（順便修正 `prepare_daily` 回傳 edition id）。全套 148 passed、1 skipped、15 xfailed。

### 步驟 3｜修事件聚合 — 第 1–4 點（2026-10-29 完成；第 5–8 點另開步驟）

本次只做手冊步驟 3 的第 1–4 點（共同實體、兩段門檻、譯名表、跨語言合併）。第 5 點證據包相關性過濾、第 6 點轉載辨識（E10）、第 7 點 arXiv／數據欄／單一來源警語（E12、E15、E16）、第 8 點 `1027_rebuild.db` 前後對照與週報，都還沒做。沒有呼叫任何真 LLM。

- ✅ **1. 共同實體檢查**（`reddit_tracker/collection/entities.py`）：合併前兩篇**標題**要有共同實體。先用譯名表統一成中文標準譯名；英文取大寫開頭的字，句首字、常見字清單（`reddit_tracker/seeds/entity_common_words.yaml`，有 Block、Apple、New，可凍結）不算；整個標題是 Title Case 時只認譯名表的名字（`iPhone` 這種字也算大寫）；中文取譯名表命中的名字，加上兩篇都有、≥3 字、在當天素材標題中出現率 < 5% 的片段；數字取 3 位數以上，年份不算。手冊的例子「Serbia、Vučić」對「Seahawks、Chiefs」沒有共同實體，有測試。🔁 改編了四處，都記在 `docs/v5/CLUSTERING.md`：
  - **句首字有佐證才算**：句首字預設不算；但如果當天其他標題在句中把它大寫，而且當天從沒以小寫出現（例如「Anthropic files for IPO…」），就算名字。不這樣做的話，以公司名開頭的英文標題全部抽不到實體（10/27 的 Anthropic IPO 9 篇會拆成 9 個事件）。E03 不受影響：Block 在常見字清單。
  - **大小寫混合的字**（iPhone、SpaceX）一律算名字；中文標題裡的英文字也算。
  - 標題裡的 HTML 實體會先還原（`&#8216;` 原本會被當成數字 8216）。
  - 「出現率 < 5%」的分母是這次聚合時間窗（72 小時）內的素材標題，不是日曆上的一天。只有這兩篇有的片段（df ≤ 2）一律算少見，不然素材很少時，5% 會小於 1 篇，片段永遠不成立。
- ✅ **2. 兩段門檻**：相似度 ≥ 0.45 要 ≥ 1 個共同實體；0.28–0.45 要 ≥ 2 個；< 0.28 不合併。這些都是設定值：`CLUSTER_HIGH_THRESHOLD`、`CLUSTER_LOW_THRESHOLD`、`CLUSTER_HIGH_MIN_ENTITIES`、`CLUSTER_MID_MIN_ENTITIES`，由 `MergeRules.from_settings()` 讀取，`.env.example` 也已同步。`cluster_recent_items` 的 `threshold=` 參數改成 `rules=`／`lexicon=`。候選素材依相似度由高到低逐一檢查，第一個「過門檻＋實體夠＋和事件重心夠像」的就併入；`ClusterRunStats.rejected_no_entity` 記下被實體條件擋掉的次數。代價（離線重編 10/27）：事件數 2,539 → 2,822，≥2 家出處的事件 264 → 220，≥3 家 104 → 66。被拆開的大多是 Title Case 標題，以及只共有一個名字的中段配對。這符合「不確定就不要合併」，11/07 拿到 dev 標註後再重調。👤 重調門檻要等標註員 A 交回 dev 標註。
- ✅ **3. 譯名表** `reddit_tracker/seeds/name_glossary.yaml`（手冊寫 `seeds/name_glossary.yaml`，專案的 seeds 目錄在套件裡）：50 筆，格式照手冊（`en`／`zh`／`also`），以中央社譯名為準，手冊舉的魯拉、佛拉維歐、武契奇三筆都在。撰稿與合併共用同一份：`DailyWriter.write` 的提示會列出證據中出現的譯名，要求一律使用中央社譯名（E08 的文字條件仍要等錄音，見下）。防偷看：`tests/test_entities.py::test_glossary_names_seen_before_cutoff` 用唯讀母本（`mode=ro&immutable=1`）驗證每一筆都在 10/31 00:00（台北）以前的素材標題出現過；母本不在時 skip。刻意不收美國、中國、俄羅斯這類幾乎每篇國際新聞都有的國名，避免不同事件被湊出「2 個共同實體」。👤 譯名表與常見字清單還要在實驗一打 tag `exp1-frozen` 凍結。
- ✅ **4. 跨語言合併**（新模組 `reddit_tracker/daily/desk.py`，`run._editorial_meeting` 改為呼叫它）：
  - 線上做法：在編輯會議的候選池（`desk_pool`）裡，中文事件 × 外文事件，只要某一對成員標題經譯名表統一後有 ≥ `CLUSTER_CROSS_LANG_MIN_ENTITIES`（2）個共同實體，就合併。不需要 LLM，模板模式也會做。
  - `find_same_events`（Codex）保留為第二意見。它說要合併的組，程式逐對確認共同實體 ≥ `CLUSTER_LLM_MERGE_MIN_ENTITIES`（1）；確認不了就剔除，原因寫進 `stats.rejected_merges` 與 log。`stats` 另外新增 `entity_merge_groups`、`llm_merge_groups`，實驗一方法 A 的重播仍然讀 `merged_groups`。
  - 🔁 順手修了 `apply_merges` 的重疊組 bug：A＋B、A＋C 而且 C 分數最高時，B 原本會遺失；現在被吸收事件之前併入的事件會一起帶過去。這是因為程式合併讓巴西的英文事件同時連到兩個中文事件。
  - 多語言 embedding（方法 B）沒做：手冊說它只在實驗一離線跑，是加分項。
- ✅ **回歸集結果**（離線重編、`find_same_events` 用 `1027_merges.json` 重播、沒有呼叫真 LLM）：已拿掉 xfail 並通過的有 **E01**（LLM 的 [NFL, 塞爾維亞] 組因沒有共同實體被剔除）、**E02**（沈伯洋後援會、蔣萬安競總三篇不再併入蘇清泉道歉）、**E03**（瑞士地圖不再併入 Block）、**E04**（Skydance 不再併入微軟）、**E06**（巴西中英文三個事件併成一則、只見報一次）、**E07**。E13 與 E05 的標題條件照舊通過。全套 182 passed、4 skipped、6 xfailed，母本 sha256 仍 OK。
  - 🔁 **E07 改了條件的錨點**：原本的中文標題「塞爾維亞學運開花結果 國會大選席次過半」（自由時報）在新規則下自成單一來源事件：它和其他中文稿只共有「塞爾維亞」，相似度 0.29，落在中段；這是刻意接受的漏合併，而且它沒見報。中英文塞爾維亞事件（英文 404＋中文 409）已經合併、只見報一次。所以 `must_merge_titles` 改用同一則刊出稿裡的 DW 中文標題「武契奇承認敗選　塞爾維亞學生運動贏得議會選舉」，並新增 `same_event_titles`（自由時報、公視、央廣三篇）：同一事件的素材最多只能出現在一則刊出稿，所以自由時報那篇日後若單獨見報，條件會抓到。原始刊出版仍抓得到錯（`test_detects_original_error` 通過）。
  - 🔁 E03 修好之後，Block 稿自成一則，而且已超出選題時間窗、不在候選裡。所以 runner（`tests/regression/rebuild.py`）也會列出「案例提到、但不是候選」的事件，讓「不得含某素材」能判定；不然只會得到「找不到事件」。
- ⚠️ **仍掛 xfail、等錄音（照協調者指示，本步驟不呼叫真 LLM）**：E03 與 E04 的正文條件。E03 的 Block 稿在重編版沒見報，所以目前是 skip；E04 的正文要錄音才能檢查。另外 E08、E12、E16 的文字條件，以及 E10、E14、E15。E04 的聚合已修好，xfail 原因已改成只差錄音。注意：新聚合下，E11（莫德納）與 E12（只有 arXiv 來源的稿件）在重編版都沒見報，條件是 skip，不是通過；做第 7 點時，arXiv 措辭最好另外補一個不依賴選題結果的單元測試。
- ℹ️ 規格已同步：`docs/v5/CLUSTERING.md`（新增「共同實體與兩段門檻」「譯名表」兩節、介面）、`docs/v5/DAILY_EDITION.md`（編輯會議、stats 鍵、`desk_merges`／`DailyWriter(lexicon=)` 介面）。

### 步驟 3｜修事件聚合 — 第 5–7 點（2026-10-29 完成；第 8 點另開步驟）

本次做手冊步驟 3 的第 5 點（證據包相關性過濾）、第 6 點（轉載辨識 E10）、第 7 點（arXiv E12、數據欄 E15、單一來源警語 E16）。第 8 點（`data/work/1027_rebuild.db` 前後對照＋週報）還沒做。沒有呼叫任何真 LLM；母本 sha256 仍 OK。

- ✅ **5. 證據包相關性過濾**（`daily/evidence.py`）：`build_evidence` 改回傳 `EvidencePack(items, notes)`。每一篇都要和事件代表標題（合併事件取主事件 `cluster_ids[0]` 的代表素材）有共同實體，用第 1 點同一套 `EntityLexicon.shared`（先用譯名表統一成中文，英文代表標題不會把中文來源全剔掉——單元測試：DW 英文「Serbia's Vucic…」為錨點時，中文「…武契奇承認敗選」保留、AP 美式足球剔除）。剔除紀錄照手冊格式「剔除：AP｜Jaxon Smith-Njigba leads…，原因：無共同實體」，經 `Planned.notes` 寫進該稿 `review_notes`（模板稿也有）。🔁 兩處補充：(a) 中文片段「少見」的分母要用當天素材，否則同一事件的 6 篇都有「塞爾維亞」就變常見而互相剔除；所以 `plan_edition` 先算 `title_context`（聚合時間窗 72 小時內的素材標題，與聚合同一定義）傳進去；(b) 代表標題本身抽不到任何實體（全是一般字的 Title Case 英文）時無從比對，不過濾、記「未做相關性過濾：…」，避免整包只剩代表那一篇。10/27 重編：39 則中只有金鐘獎一則剔除 3 篇（新人獎龍步晞的分稿），沒有誤剔中文來源。
- ✅ **6. 轉載辨識（E10）**，手冊列的三個地方都改了：
  - `collection/normalize.py`：`title_fingerprint` 先去掉開頭的 `[..]`／`【..】` 標籤（可連續多個）再算；新增 `strip_title_labels`、`title_key`。
  - `collection/clustering.py` 的 `_refresh_cluster`：`outlet_count` 排除 `duplicate_of_id` 非空的素材，也排除 `mark_reprints` 認出的轉載。
  - 新寫 `mark_reprints(members) -> {轉載 id: 原稿 id}`：重複稿一律算轉載；另外去標籤後標題相似度 ≥ 0.8，或轉載方內文帶中央社電頭（另一篇是中央社網域），且發布時間差 ≤ 2 小時。原稿依序取中央社網域 → 層級高 → 先發布（10/27 央廣「[兩岸] 中國擬加強保護商業秘密…」id 比中央社小、先收到，原稿仍是中央社）。前台：證據包把轉載併成原稿一列，來源列顯示「中央社（中央廣播電台轉載）」，`sources[]` 多 `reprinted_by`；帶中央社電頭的他站稿顯示「中央社（風傳媒轉載）」。
  - 「指紋改了要另外重算」：新增 `collector.recompute_duplicates(items)`（規則同 `store_outcome`，依收錄順序），回歸集 runner 重編前對全部素材重算（10/27：重複稿 352 → 401）。第 8 點在 `1027_rebuild.db` 重聚前也要先跑它。
  - 🔁 **相似度 ≥ 0.8 只用在兩篇都是中文**：英文各家獨立報導標題常幾乎一樣（10/27 微軟優離：The Verge 對 CNBC 0.89、FT 對 NYT 0.92、再串到 BBC），照套會把 7 家併成 1 家、把獨立報導當轉載。英文轉載（Yahoo Finance 轉 Reuters／TechCrunch）標題完全相同，已由指紋重複稿處理。記在 `docs/v5/CLUSTERING.md`。
  - ⚠️ 代價（10/27 重編）：≥2 家出處的事件 222 → 156（排除重複稿 222 → 170、再排除轉載 → 156），≥3 家 66 → 41；選題 39 則（report 33／single_source 6）。這是「轉載不算多來源」的直接結果，11/07 dev 標註後與門檻一起看。
- ✅ **7. 其他程式規則**：
  - arXiv（E12）：證據全部來自 `arxiv.org` 的稿（`writer.is_preprint_only`），撰稿請求帶 `"source_type":"preprint"`，提示加一句「正文第一句寫『一篇發表於 arXiv 的預印本論文指出』，不要寫報導、獨家」（只有這種稿時才加，其他版的 request_hash 不變）；審稿關卡：出現「獨家」「一家媒體」或沒寫「預印本」就不通過、改模板稿；模板稿以「一篇發表於 arXiv 的預印本論文指出：」開頭，文末「預印本未必經過同儕審查，研究結論仍待驗證。」；網頁標籤「預印本」取代「單一來源」。
  - 數據欄（E15）：`market.is_stale`——收盤日期距出刊日超過 1 個交易日，網頁數據欄與 Telegram 精選都加「資料更新延遲」。🔁 交易日只排除週末、沒有國定假日表：連假後第一期會多標一次（寧可多標）；日期不明也算延遲。
  - 單一來源警語（E16）：`writer.py` 提示詞第 4 條（single_source／social 要在正文明說）刪掉；新增 `finalize_story`，LLM 稿與模板稿最後都經過它，由程式在正文最後一段加警語（single_source、social、預印本各一句，report 不加；可重複呼叫不會加兩次）。模板稿本身不再自帶警語。審稿關卡新增：LLM 在標題／導言／正文／重要性任何地方自己寫「僅有／只有一家媒體／來源」就不通過、改模板稿（原因進 `review_notes`）。
- ✅ **回歸集**：拿掉 xfail 並通過 **E10**（`reprint_pairs` 六組全過）、**E15**（`market_stale_label`）。E01、E02、E03、E04、E05（標題條件）、E06、E07、E13 照舊通過。
  - 🔁 E15 的「刊出版必須抓得到錯」：刊出版面是用現在的 `render_html` 從 fixture 重畫的，修好後也會帶標示；所以 `published_view` 畫數據欄時把 `market_stale` 固定為 False（＝10/27 當時的版面），原始錯誤仍抓得到。
  - ⚠️ **仍掛 xfail、等錄音**（照協調者指示，本步驟不呼叫真 LLM）：E04、E05 正文（`text_must_not_contain`）、E12 `arxiv_rules`、E16 `single_source_notice`、E08；xfail 原因已改成「程式規則已實作、只差錄音」。E12 在重編版沒有只來自 arXiv 的刊出稿，是 skip。用 `--runxfail` 確認 E04、E16 失敗的唯一原因是 `require_written`（10 個 request_hash 找不到）；另把 `replay_misses` 清空、只看模板稿時，E16 條件在重編版已通過。E14 等步驟 4。
  - ✅ **不依賴選題結果的單元測試**（`tests/test_step3_rules.py`，18 個）：直接拿回歸案例的同一個條件函式（`checks.arxiv_rules`、`checks.single_source_notice`）檢查合成稿件——arXiv 稿 LLM 寫「據 arXiv 獨家報導，目前僅有一家媒體」→ 改模板稿、以預印本句開頭、E12／E16 條件通過，而原始錯誤文字在同條件下會被抓到；單一來源稿 LLM 沒寫警語 → 程式加在最後一段；把警語塞在段落中間 → 不過審；多來源稿不加；E16 條件通過、原始錯誤抓得到。另含轉載（指紋去標籤、`recompute_duplicates`、`mark_reprints` 中文相似度／中央社電頭／2 小時、英文不套相似度、`outlet_count`＝1、來源列「中央社（中央廣播電台轉載）」）、相關性過濾（剔除格式、notes 進 `review_notes`）、交易日計算與延遲標示（網頁＋Telegram）、預印本標籤。
- ℹ️ 介面變更（規格已同步 `docs/v5/CLUSTERING.md`「轉載辨識」、`docs/v5/DAILY_EDITION.md` 證據包／撰稿／審稿／數據欄／介面）：`build_evidence` 與 `story_evidence` 回傳 `EvidencePack`；`Planned` 多 `notes`、`EditionPlan` 多 `context`；`EvidenceItem` 多 `reprinted_by`、`display_name`；`writer._short_outlet` 移到 `evidence.short_outlet`。全套 202 passed、4 skipped、4 xfailed。
- ➡️ 下一步：步驟 3 第 8 點（`cp` 母本到 `data/work/1027_rebuild.db`，刪 10/27 06:00 後素材、清空聚合與所有期數、`recompute_duplicates`、`run.py --now`，前後來源清單並排附週報）。E04／E05／E12／E16 的文字條件要等協調者用真 Codex 在 `data/work` 複本錄音；11/04 到期前沒錄就會被 `test_overdue_cases_are_not_xfail` 擋下。
