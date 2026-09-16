# v5 協作準則（Codex 與 Claude Code 共用）

## 開始與結束

- 每次工作先讀 `PROGRESS.md` 與本目錄 `README.md`；只讀取目前任務所需的 v5 文件。
- 每個 task 先寫下目標、非目標、受影響模組與驗證方式；完成後回報實際檔案、命令與結果。
- 實質狀態改變才更新 `PROGRESS.md`，不得把願望或未驗證結果記成完成。

## Git 與 runtime 安全

- v5 工作使用 `codex/ai-newsroom-*` branch；不可直接把未驗證 migration 套用到正在使用的 SQLite DB。
- 不得在未經明確需求下停止／重啟 launchd、送 Telegram、修改 `.env` 密鑰或碰 production data。
- DB 變更必須有 Alembic migration、upgrade test、rollback 說明與 backup 程序。

## Agent 實作規則

- 每個 agent 接受與產出 `newsroom.contracts` 模型，產出必須包含 source refs 與可讀 summary。
- 介面只呈現 artifact、證據與決策碼；不存或顯示 chain-of-thought、cookie、token、prompt 中的敏感資料。
- Reddit 是來源而不是事實保證：所有文字須歸因；不確定內容要標記，不能用自信語氣補洞。
- 支援重跑與 idempotency；同一 edition stage 的副作用不能重複發送 Telegram。

## 程式與測試

- 依賴只以 `uv` 管理：首次或 lockfile 變動後執行 `uv sync --all-groups`。
- 最少跑相關 tests；改 schema、contracts、排程、formatter 或 callback 時必跑完整 `uv run --group dev python -m pytest -q`。此 workspace 的舊 `pytest` console script 指向已搬遷的 venv，故不可直接呼叫 `pytest`。
- 新行為先寫 fixture-driven test；外部 API 用 fake/mock，不以 live Reddit／Telegram 作為 unit test。
- 使用 Ruff 檢查變更檔案；不順手修改不相關的 legacy lint。

## Handoff 格式

交接訊息固定列出：完成內容、尚未做的下一步、影響資料或服務、驗證證據、仍存在的風險或決策。不要只說「已完成」。
