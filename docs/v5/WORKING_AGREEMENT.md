# v5 協作準則（Codex 與 Claude Code 共用）

## 開始與結束

- 每次工作先讀 `PROGRESS.md` 與本目錄 `README.md`；只讀取目前任務所需的 v5 文件。
- 每個 task 先寫下目標、非目標、受影響模組與驗證方式；完成後回報實際檔案、命令與結果。
- 實質狀態改變才更新 `PROGRESS.md`，不得把願望或未驗證結果記成完成。

## Git 與 runtime 安全

- 在 feature branch／git worktree 開發（例如 `mas-handbook` 在 `/Users/leroy/reddit_tracker-mas`）；production checkout 是 `/Users/leroy/reddit_tracker` 的 `main`，launchd 從這裡跑，不在該目錄直接開發。
- 併入 `main` 只能在使用者同意後以 fast-forward 進行；不 force push、不改寫歷史。
- 不可直接把未驗證 migration 套用到正在使用的 SQLite DB。
- 不得在未經明確需求下停止／重啟 launchd、送 Telegram、修改 `.env` 密鑰或碰 production data。
- DB 變更必須有 Alembic migration、upgrade test、rollback 說明與 backup 程序。

## Agent 實作規則

- 程式位置：MAS 角色、訊息與工具白名單在 `reddit_tracker/daily/mas/`（`protocol.py`：`ROLES`、`ALLOWED`、`post_message`；`orchestrator.py`：各角色流程與 Pydantic 輸出模型）；角色訊息存 `agent_messages`（`reddit_tracker/models.py` 的 `AgentMessage`），稿件版本存 `StoryVersion`；LLM 層在 `reddit_tracker/llm/`（`codex.py`、`gemini.py`、`fake.py`、`quota.py`、`records.py`→`llm_records`）。
- 角色產出必須能追到證據來源（`reddit_tracker/daily/evidence.py`），並有可讀 summary。
- 介面只呈現 artifact、證據與決策碼；不存或顯示 chain-of-thought、cookie、token、prompt 中的敏感資料。
- 來源（RSS／RSSHub）是素材而不是事實保證：所有文字須歸因；不確定內容要標記，不能用自信語氣補洞。
- 支援重跑與 idempotency；同一 edition stage 的副作用不能重複發送 Telegram。

## 程式與測試

- 依賴只以 `uv` 管理：首次或 lockfile 變動後執行 `uv sync --all-groups`。
- 測試指令：`REDDIT_TRACKER_NO_DOTENV=1 uv run python -m pytest -q`（`dev` dependency group 由 `uv sync --all-groups` 安裝）。最少跑相關 tests；改 schema、MAS 協定、排程、render 或發行時必跑全套。
- 隔離方式：`REDDIT_TRACKER_NO_DOTENV=1` 讓 `config.py` 不讀 `.env`；`DATABASE_URL` 預設是 `sqlite:///./reddit_tracker.db`，要更保險可另設 `DATABASE_URL=sqlite:////tmp/<name>.db`。`tests/conftest.py` 的 `session` fixture 用 in-memory SQLite，並把 LLM 額度檔導到 `tmp_path`；`tests/llm_guard.py` 在 pytest 啟動時攔截執行 codex 與連線 Gemini API，測試一嘗試呼叫真 LLM 就失敗。
- 新行為先寫 fixture-driven test；外部服務用 fake/mock（LLM 用 `reddit_tracker/llm/fake.py`），不以 live RSS／Telegram／LLM 作為 unit test。
- 使用 Ruff 檢查變更檔案；不順手修改不相關的 legacy lint。

## Handoff 格式

交接訊息固定列出：完成內容、尚未做的下一步、影響資料或服務、驗證證據、仍存在的風險或決策。不要只說「已完成」。
