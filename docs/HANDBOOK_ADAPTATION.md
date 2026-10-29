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

### 步驟 3｜修事件聚合 — 第 8 點＋步驟 3 做完的標準（2026-10-30 完成）

本次做手冊 3.8「重編 10/27 做前後對照」，並錄製回歸集需要的 LLM 回應。依協調者指示，這次允許**只在 `data/work` 複本**上呼叫真 Codex。

- ✅ **重編腳本** `scripts/rebuild_1027.py`（可重跑）：`cp` 母本 → `data/work/1027_rebuild.db`，照 3.8 子步驟：
  1. 刪 `first_seen_at > 2026-10-26 22:00`（UTC naive＝10/27 06:00 台北）的素材 18,774 篇，剩 5,865 篇。外鍵：先把 `cluster_id`、`duplicate_of_id`（自我參照）清成 NULL 再刪，刪完跑 `PRAGMA foreign_key_check`；其他參照 `source_items` 的表不存在。
  2. 清 `source_items.cluster_id` 與 `story_clusters`（13,023 個）。
  3. 刪**所有** `daily_articles`（126）與 `daily_editions`（3）；兩者沒有其他子表。之後 `collector.recompute_duplicates` 重算指紋：重複稿 437 篇。
  4. `daily/run.py` 新增 `--now`（`parse_now`：ISO，不帶時區＝台北，回傳 UTC）與 `--recluster`（`recluster(now)`：用同一個 `now` 呼叫 `cluster_recent_items`）。`prepare_daily(now=)` 本來就把 `now` 傳給評分、選題時間窗、證據包的當天素材與 `prepared_at`；沒給 `--date` 時出刊日＝`now` 的台北日期。單元測試 3 個（`tests/test_daily.py`：時區解析、CLI 的 `now` 同時到達聚合與評分、`now` 決定選題時間窗）。規格 `docs/v5/DAILY_EDITION.md` 已補。
  5. 一次重聚（3,180 篇在窗內 → 2,783 個事件，被實體條件擋下 503 次）→ 重編：39 則（Codex 38、模板 1；模板稿是審稿關卡擋下「證據中找不到的數字：23, 26」）。編輯會議程式合併 3 組，LLM 第二意見也是同樣 3 組，沒有被剔除的。
  - 🔁 數據欄：重編時不連網抓今天的證交所，改用母本 10/27 那期 `stats.market` 的數值（否則數據欄會是 10/30 的資料）。
  - 🔁 腳本直接呼叫 `run.recluster`／`run.prepare_daily(writer=…)`，而不是跑 CLI：撰稿要注入下面的錄音 client。CLI 的等價寫法記在規格裡。
- ✅ **真 Codex 與 `llm_records`**（強制指令 3）：
  - 新增 `scripts/llm_recorder.py`（不碰 `models.py`、migration、`llm/codex.py`，避免和步驟 6–7 的 `cursor/mas-steps-6-11-cc77` 分支衝突）：`RecordingCodexClient` 包住 `CodexClient`，自己做重試迴圈，**每一次 subprocess 嘗試**（含失敗、重試）寫一列；`request_hash` 用 `llm/replay.request_hash`；`model_version`＝`gpt-6.1-sol | codex-cli 0.164.0-alpha.11.1 | reasoning_effort=low`；`find_same_events` 記成 `role=desk`、撰稿記成 `writer`。同一個 hash 在任何一本帳已有 ok 就重用不呼叫。
  - 🔁 母本已經有一張舊版 `llm_records`（v4 時代，1 筆，沒有 request_hash 等欄位），所以 `CREATE TABLE IF NOT EXISTS` 之後會用 `ALTER TABLE ADD COLUMN` 補齊欄位（欄位名稱、型別與那個分支的 migration `b8d4f0a17c33` 一致）；只發生在複本。舊的那 1 筆不算本任務的呼叫。
  - 額度：`LLM_QUOTA_STATE_PATH=data/work/llm-quota-1027.json`（腳本內強制設定並 assert），`/tmp/reddit-tracker-llm-quota.json` 確認不存在；另有整個任務的硬上限 60（兩本帳加總）。
  - **實際用量：真 Codex 16 次嘗試、16 次成功、0 次失敗**（1 次試跑＋3.8 重編 11 次〔編輯會議 1＋撰稿 10〕＋回歸 runner 路徑 4 次），遠低於 60。額度 state 檔也記 16。總耗時約 9 分鐘（單次 6–57 秒）。
  - 帳本：`data/work/1027_rebuild.db` 的 `llm_records` 12 筆、`data/work/1027_regression_record/1027_rebuild.db` 4 筆。
- ✅ **回歸集錄音**：回歸 runner 是逐輪聚合，和 3.8 一次重聚不同，所以另寫 `scripts/record_regression_1027.py`：走 `tests/regression/rebuild.py` 同一條路徑，錄音檔沒有的 request_hash 才交給 recorder。runner 需要 10 個撰稿 hash，其中 6 個和 3.8 重編**完全相同**（這幾版的證據包一樣）、直接重用，只多呼叫 4 次。匯出 `tests/regression/fixtures/1027_llm_records.json`：16 筆 ok 紀錄、66,967 bytes，欄位為 request_hash、response_text、ok、provider、model、model_version、purpose、role、run_variant、edition_date、latency、tokens、called_at（不放 prompt；Codex client 會丟棄含本機機密的輸出，另外掃過沒有路徑或 key）。`--check` 模式只重播、列出缺的 hash，不呼叫。重播結果：0 miss，39 則中 38 則用錄音、1 則被審稿關卡擋下改模板稿。測試仍由 `llm_guard` 擋 codex subprocess。
  - ⚠️ 錄音只對當下的提示詞與證據包有效；之後改到撰稿提示、譯名表、證據包規則，回歸集會因 miss 失敗，要重跑 `record_regression_1027.py`（會再呼叫 Codex）。
- ✅ **前後對照** `scripts/compare_1027.py`（可重跑；母本 `mode=ro&immutable=1`、重編複本 `mode=ro`）→ `docs/weekly/1027_compare.md`，週報已連結。內容：總覽、錯誤案例表（**用 `tests/regression/checks.py` 同一套條件**判斷舊期與新期）、62 列稿件並排（版別、標題、來源「媒體｜標題」，用來源網址配對，「－」移除、「＋」新增）、`llm_records` 明細。註明「重編時不排除前幾期已刊事件」。新期的文字條件用的是 3.8 真 Codex 稿。
- ✅ **母本完整性**：`tests/test_snapshot_integrity.py` 母本在就驗 sha256 等於 `data/snapshots/2026-10-27.db.sha256`，不在就 skip。最後 `shasum -a 256 -c` OK，權限仍 `r--r--r--`。
- **步驟 3 做完的標準：**
  - ✅ **11/04：E01、E03、E04、E05、E10、E12、E13、E15、E16 回歸測試通過**（`tests/regression`，離線錄音重播）。已拿掉 xfail：E04 `text_must_not_contain`、E16 `single_source_notice` 用錄音的 Codex 稿通過；E03、E05 `text_must_not_contain` 與 E12 `arxiv_rules` 也拿掉 xfail，但在重編版是 **skip（不適用）**：Block 稿、SpaceX 單一來源稿、只有 arXiv 來源的稿件在新聚合下都沒見報，所以不會產生撰稿請求，也就沒有東西可錄。🔁 這三條改由其他方式把關：E03／E05 的事件層條件（`must_not_contain_titles`）通過；E12 的規則由 `tests/test_step3_rules.py` 用同一個條件函式測合成稿。3.8 前後對照的判斷結果相同：新期 E01、E03（事件層）、E04（事件＋正文）、E05（事件層）、E10、E13、E15、E16 ✅；E03／E05 正文、E12 —（沒見報）。日後若這些稿件見報，條件會自動生效（有錄音才會通過，沒有就失敗）。
  - ✅ **母本雜湊值跟複製時一樣**：見上。
  - ✅ **11/08：E02、E06、E07 回歸測試通過**（步驟 3.1–3.4 已過，3.8 新期也是 ✅）。
  - ✅ **10/27 前後對照已附在週報**：`docs/weekly/2026-11-03.md` →`docs/weekly/1027_compare.md`。
  - 附帶：E08（11/15）錄音後通過（巴西稿全用「魯拉／佛拉維歐」），已拿掉 xfail。E11 的莫德納稿在重編版沒見報，維持 xfail。E14（11/15）兩邊都還是 ❌，等步驟 4。
- 全套 `uv run python -m pytest -q`：213 passed、4 skipped（E03／E05 正文、E11、E12 不適用）、1 xfailed（E14）。

### 步驟 4｜併版與配額＋E14（2026-10-30 完成）

- ✅ **1. 先改寫分版**：新模組 `reddit_tracker/daily/sections.py`，詞表放在 `reddit_tracker/seeds/section_rules.yaml`。`plan_edition` 在 `score_candidates` 之後、編輯會議之前呼叫 `rewrite_sections`。規則如下，全部由程式判斷，詳細表格在 `docs/v5/DAILY_EDITION.md` §2：
  - 兩岸版：有台灣詞或台灣官方 T1 來源就改到台灣版，其他改到國際版。
  - 財經版依序判斷：台灣詞改台灣版；科技詞或事件裡有科技版來源改科技版；全是繁中（台灣媒體）而且沒有國際詞改台灣版；其他改國際版。
  - 生活版的教育、社會類（E14）：有社會詞，而且有台灣詞、台灣官方來源或全是繁中，就改到台灣版。
  - 英文詞前後不能緊接英數字，所以「AI太燒錢」算 AI，Thailand 不算。
  - 改過的事件在 `signals` 記 `original_section`／`section_rule`，`stats.section_rewrites` 記統計。
  - 🔁 手冊說「關鍵字／來源地區／譯名表」。這裡用關鍵字＋來源（台灣官方 T1、科技版來源、語言 `zh-Hant`）判斷。譯名表沒用到，因為它只有人名，判斷不了主題。
  - 🔁 E14 這類只在生活版套用：科學版的「大學」研究、體育版的「學生」選手不改，避免誤判。
  - 測試：`tests/test_sections.py` 有 19 個分類案例，都是 10/27 的真實標題。另有一個測試證明「只改配額不改分版，兩岸、財經事件會整篇消失」，改寫後兩岸、財經、教育稿都進了三個內版。
- ✅ **2. `SECTION_QUOTAS = {taiwan: 4, world: 4, tech: 4}`**，共 12 篇。`SECTION_KINDS` 只剩三版，`social` 事件不再選題（社群來源已全停用）。
- ✅ **3. `select_articles`**：三內版各取 4 篇，頭版 6 則從這 12 篇裡標記，不另佔名額。
  - 頭版依分數取 report，每版最多 2 則；不足 6 則先放寬每版上限，仍不足就少放。
  - 🔁 手冊沒寫不足時怎麼辦。這裡選擇讓 single_source 不上頭版，維持舊規格的「單一來源不上頭版」。
  - `DailyArticle.position`：頭版稿是頭版順位，其他稿是內版順位。內版順位另寫在 `signals.section_position`，不改 schema。
  - `render.py`：內版遇到頭版稿，放標題連結到頭版那篇（`#story-{cluster_id}`，標「見頭版」），全文只印一次。舊期沒有 `section_position` 就用 `position`。
  - 撰稿分組不變：頭版一次、三內版各一次（只寫非頭版稿），所以頭版稿不會被重寫。
- ✅ **4. 其他版只出頭版標題短訊**：`select_briefs` 處理科學、生活、文化、體育四版。
  - 每版取分數最高 2 則；標題取證據包裡的中文來源，去掉分類標籤。
  - 不呼叫 LLM，也不寫 `daily_articles`，存在 `stats.briefs`。頭版有一個「短訊」清單，附版別、媒體、原文連結。
  - 這些版的選單保留，頁面顯示「本版未開放」。Telegram 精選多一行「短訊 N」。
  - 🔁 短訊放在 `stats` JSON 而不是新資料表，因為本步驟不改 schema。正式的 `page_plans` 屬步驟 9。
- ✅ **5. LLM 次數**：一期正式稿剛好 12 篇（10/27 重編驗證）。撰稿請求是頭版 1＋三內版各 1，加上編輯會議 1，一期最多 5 次（WRITE_ATTEMPTS／client 重試另計），短訊 0 次（有測試）。手冊 6.7 的 P 組每版一次撰稿、分版主編／總編等 MAS 角色都沒做（步驟 6–9）。
- ⚠️ **與 `cursor/mas-steps-6-11-cc77` 的合併衝突風險點**（沒改 DB schema、migration、models、store、writer、evidence）：
  - `daily/run.py`：`plan_edition` 多了 `rewrite_sections`、`select_briefs` 兩個呼叫，`EditionPlan.briefs` 欄位，import 一行，`prepare_daily` 的 stats 多 `front_articles`／`briefs`／`section_rewrites`、讀 `plan.briefs`。那個 PR 大改 run.py，合併時要把這幾個呼叫點搬到它的 P 組流程（`plan_edition` 或其等價處）。
  - `daily/render.py`：`_anchor`／`_link_html`／`_section_order`／`_briefs_html` 四個新函式；`render_html` 的內版迴圈（頭版稿改連結、依 `section_position` 排序）、頭版加短訊；`telegram_digest` 的各版計數。那個 PR 也改 render.py（加 page_plans／回放頁），衝突集中在 `render_html`。
  - `daily/scoring.py`：`SECTION_QUOTAS`、`SECTION_KINDS`、`Selection.section_position`、`select_articles` 全部重寫。那個 PR 沒列 scoring.py，但它的 MAS orchestrator 若依賴舊的 10 版配額或「頭版另選」語意，要改成三內版。
  - `sections.py` import 了 `evidence.EvidenceItem`／`short_outlet` 與 `writer.story_label`；那個 PR 改 evidence.py、writer.py，若改名要跟著改。
  - `tests/regression/rebuild.py` 多了 `Story.signals`、`EditionView.stats`（那個 PR 也改了這個檔 3 行）；`tests/test_daily.py` 的 fixture 把社群稿換成台灣版單一來源稿。
  - 錄音 `fixtures/1027_llm_records.json` 綁定現在的分組與提示詞；那個 PR 若改撰稿提示，合併後要重錄。
- ✅ **6. 測試**（都不呼叫真 LLM）：
  - `tests/test_sections.py`：配額 12、19 個分類案例、英文詞邊界、不改分版會消失、兩岸／財經／教育稿進三內版、短訊不呼叫 writer、頭版只從正式稿標記。
  - `tests/test_daily.py`：12 篇＋頭版 6 則（每版 ≤2）、放寬上限、內版放頭版連結且全文只印一次。
  - `tests/regression/test_step4_layout.py` 在離線重編的 10/27 上驗證：剛好 12 篇（各版 4）、頭版 6；兩岸、財經事件全部改寫到三內版；短訊只有標題、撰稿請求 ≤ 5；內版頭版稿是連結。
  - **E14 拿掉 xfail 並通過**；其他回歸案例照舊全過。
  - 錄音重錄：分組改了，4 個撰稿 request_hash 對不上。用 `scripts/record_regression_1027.py --max-attempts 41`（本步驟上限 25＝先前 16＋25）在 `data/work/1027_regression_record/` 錄：**真 Codex 4 次、4 次成功**，帳本該檔 `llm_records` 4→8 筆，任務累計 20 次（額度檔 `data/work/llm-quota-1027.json` 也是 20，`/tmp` 預設檔不存在）。`fixtures/1027_llm_records.json` 更新為 20 筆、81,979 bytes，重播 0 miss；12 篇中 11 篇用錄音、1 篇被數字審稿關卡擋下改模板稿。沒有刪除任何條件或改回 xfail。
- ✅ **7. 10/27 驗證**（`scripts/validate_step4_1027.py`：`data/work/1027_rebuild.db` 複製成 `data/work/1027_step4.db`，template writer，0 次 LLM）：
  - 正式稿 12 篇：台灣 4、國際 4、科技 4。
  - 頭版 6 則：巴西魯拉（國際）、柯米起訴（國際，原財經）、iPhone Duo（科技）、微軟優離（科技，原財經）、蔡康永（台灣）、蘇清泉（台灣）。
  - 短訊 8 則：科學、生活、文化、體育各 2。
  - 改寫統計：`cross_strait→world` 123、`cross_strait→taiwan` 6、`finance→world` 148、`finance→tech` 119、`finance→taiwan` 79、`life_env→taiwan` 7。
  - 財經稿刊出 3 篇：柯米→國際、微軟與 SpaceX→科技。
  - ⚠️ 兩岸稿 10/27 沒有入選：全部改寫到國際／台灣版參與選題，但國際版很擠，兩岸最高分的福田康夫（26.8）排國際第 17 名；洪秀柱（台灣版）是 single_source。這是分數競爭的結果，不是消失；合成資料測試證明兩岸稿在名額內會刊出。
- ✅ **做完的標準**：
  - ✅ 一期剛好 12 篇正式稿，頭版 6 則從中標記（回歸集＋驗證腳本）。
  - ✅ 兩岸、財經稿有出現在台灣／國際／科技版：財經在 10/27 實際刊出 3 篇。兩岸在 10/27 只做到改寫進內版、分數不夠沒入選；刊出由 `tests/test_sections.py` 以合成資料驗證（兩岸→台灣、兩岸→國際都刊出）。
  - ✅ E14 回歸測試通過。
- 全套 `uv run python -m pytest -q`：243 passed、4 skipped（E03／E05 正文、E11、E12 在重編版不適用）。母本 `shasum -a 256 -c` OK。

### 步驟 5｜給標註員的配對試算表＋8.1 抽樣規則（2026-10-30）

本步驟沒有呼叫任何 LLM，也沒有碰 production DB。

- ✅ **抽樣程式與種子已 commit**：`cff09fa`（第一個 commit，試抽在它之後才跑）。
  - 程式：`reddit_tracker/eval/exp1.py`、`scripts/sample_exp1.py`。種子 `exp1.SEED = 20261104` 寫在程式裡。
  - 新依賴 `openpyxl`（`uv add`，lock 已 commit）。操作說明在 `docs/eval/EXP1_SAMPLING.md`。
  - 規則摘要：
    - 方法 A＝現行聚合程式加參數 `METHOD_A_RULES`（相似度 ≥ 0.28、不要求共同實體＝舊規則，沒有另抄一份），用收集當時的重複稿標記、停用來源也參與。跨語言重播各期 `stats.merged_groups`（live cluster id → 素材 → A 的事件），沒紀錄的日期寫在 manifest。
    - 方法 C＝步驟 3 現行版（設定門檻＋共同實體＋譯名表），加每個出刊日 06:00 的 desk 跨語言規則。
    - 兩者都在暫存 SQLite 逐輪增量重跑。系統合併含遞移（`Components`）。
    - 分層：同語言 4×15、中英 4×10。dev／test 名額同語言 8/7 交錯、中英 5/5，所以各 50。
    - 中英不足就用 48 小時內同版別的隨機中英配對補；同語言不足照實記錄。
    - 錯誤案例每案最多 1 組、只進 dev，test 排除錯誤案例素材。跨 dev／test 的配對不抽。
    - B 複標 dev、test 各隨機 15 組。
    - 匯出 CSV（utf-8-sig）與 xlsx（「說明」頁、dev／test 工作表、判斷欄下拉選單）。欄位只有 `pair_id｜標題 1｜摘要 1｜時間 1｜標題 2｜摘要 2｜時間 2｜判斷｜一句理由`，台北時間；分層與答案對照放 `annotation/exp1/_private/`。`annotation/` 已 gitignore。
  - 測試 `tests/test_exp1.py`（15 個，合成資料）：
    - 出刊日切分與 06:00 邊界；
    - 可標素材篩選；
    - 遞移合併；
    - merged_groups 重播；
    - 方法 A＝舊門檻；
    - 暫存 DB 重跑時 A 會併微軟／Skydance、C 不會；
    - 不跨 dev／test；
    - 各層數量與 B 複標；
    - 種子可重現；
    - 中英補抽、同語言不補；
    - 錯誤案例只進 dev；
    - 匯出無洩漏欄位，CSV、xlsx 表頭正確；
    - 列順序打亂但可重現。
- 🔁 **手冊沒寫死、這裡的定義**：
  - **dev／test 依「出刊日」切**：`first_seen_at` 在 (D-1 06:00, D 06:00] 台北 → D。如果用發布日，10/27 那期的錯誤案例素材多半是 10/26 發布，會掉出 dev。
  - **重複稿不抽**：轉載、同標題重複稿一定是同一事件，不值得標。所以 E10 的轉載配對與 E05（PTT 已停用）不會出現。
  - **所有配對都限制發布時間差 ≤ 48 小時**：與聚合規則、標註規則一致。
  - **方法 C 的跨語言不含 `find_same_events` 第二意見**：本工具不呼叫 LLM。
  - **增量聚合每 3 小時一輪**：線上是 15 分鐘；`--round-hours` 可調，3 小時一次約 4 分鐘。
- ✅ **試抽**（用母本，`mode=ro&immutable=1` 唯讀，輸出到 `annotation/exp1-trial/`，不給標註員）：
  - 2 萬 4,639 篇素材，到 10/29 18:40；dev 可標 18,611 篇；候選配對 82,761 組；約 3.75 分鐘。
  - **dev 抽滿 50 組**（各層都足額）：同語言 8/7/8/7、中英 5/5/5/5，沒有補抽。錯誤案例 E01、E02、E03、E04、E06、E07 各 1 組進 dev。
  - **test 0 組**：母本沒有 10/31–11/02 的素材，8 層都記為不足。**B 複標只有 dev 15 組。**
  - dev 各層候選數：
    - 同語言：都合併 10,647、只 A 18,229、只 C 1,199、都不合併 47,990；
    - 中英：都合併 60、只 A 2,484、只 C 1,798、都不合併 354。
  - merged_groups 重播：10/27 17 組、10/28 2 組、10/29 4 組；10/30–11/02 母本沒有那幾期，記「沒有紀錄」。
  - commit 後重跑一次，兩次的 `exp1_key.csv`、`exp1_A_100.csv` 逐位元相同。
- 👤 **11/04 前 A、B 都拿到試算表：留給人工（需要日曆時間）。** test 期 10/31–11/02 還沒發生，現有母本只到 10/29。
  - 11/03 由開發者從當時的 production DB 做新的唯讀快照 `data/snapshots/2026-11-03.db`（同母本做法：online backup、`chmod 444`、記 sha256）。
  - 再跑 `uv run python scripts/sample_exp1.py --db data/snapshots/2026-11-03.db` 正式抽樣，輸出到 `annotation/exp1/`。
  - 11/04 把 `exp1_A_100.xlsx` 交 A、`exp1_B_30.xlsx` 交 B，`_private/` 不給標註員。
  - 步驟見 `docs/eval/EXP1_SAMPLING.md`。實作代理不得碰 production DB，所以本步驟無法代做。
- ⚠️ 正式抽樣時方法 C 要用「11/04 當下的暫定版」，也就是抽樣當下的 HEAD（manifest 會記 commit）。之後 11/12 前要打 `exp1-frozen` tag（手冊 8.1 第 3 點，另一步）。
- 全套 `uv run python -m pytest -q`：258 passed、4 skipped。母本 sha256 OK。
