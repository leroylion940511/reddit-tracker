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
