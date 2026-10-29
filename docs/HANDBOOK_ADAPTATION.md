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
