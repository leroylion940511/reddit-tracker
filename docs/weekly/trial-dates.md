# 試刊日期與連續 3 天 live 紀錄（手冊步驟 10、11、12）

> 2026-11-06 寫。日期依方案 B（ADAPTATION 文末「🔁 時程提前（方案 B）」）；**凡標「待老師確認」的都還沒經老師同意**，老師改日期時以老師為準，並同步改本檔、`PROGRESS.md`、ADAPTATION 對照表。

## 連續 3 天 live（11/04–11/06，實際情形）

每天 06:00 由 newsroom 排程以 `DAILY_MODE=mas` 準備（P 影子同跑），08:35 發行。M 組未核准的稿只發標題短訊，這是程式照規則做的，不是故障。

| 出刊日 | M 組稿件在 08:35 前核准？ | 讀者收到 |
| --- | --- | --- |
| 11/04 | 否 | 只有標題短訊 |
| 11/05 | 否 | 只有標題短訊 |
| 11/06 | 排定 06:25 由自動化流程核准（志晨授權） | 依核准結果；實際送出內容以當天 `daily_editions` 與 Telegram 紀錄為準 |

- ⚠️ 11/04、11/05 兩天「產出到待審」有做到，但讀者沒拿到全文；寫報告時照實記，不能算成兩天完整出刊。
- ⚠️ 11/06 的核准是自動化流程代為執行、不是人逐篇看過；實驗三「真人核准」的條件要在試刊期間另外滿足，或在報告註明。

## 方案 B 時程（全部待老師確認）

| 項目 | 日期 | 狀態 |
| --- | --- | --- |
| 七日試刊＋實驗三（7 期） | 11/09–11/15 | 待老師確認 |
| 實驗二 | 11/17–11/18 | 待老師確認 |
| 功能凍結，打 tag `final-1120` | 11/20 | 待老師確認 |

- 手冊原日期：試刊 12/01–12/10 中 7 天、實驗二 12/11–12/12、凍結 12/15 `final-1215`。
- 試刊（11/09–11/15）與 A 的實驗一 test 標註（11/12 前）重疊，A 那週工時會疊在一起。

## 用本機 Codex 當 LLM（待老師確認）

- 撰稿、編輯會議、MAS 各角色都走本機 Codex CLI（Homebrew cask `codex-cli 0.166.0`、`gpt-6.1-sol`、reasoning low，吃志晨的 ChatGPT 訂閱登入）。P、M 兩組用同一個模型。版本鎖定與守門見 ADAPTATION「Codex CLI 改用 Homebrew＋版本守門」。
- ⚠️ 這跟手冊 6.9 第 1 條「只能走正式 API……不能用寫程式工具的訂閱額度」不一致，**要老師確認可以用**；老師不同意的話，試刊前要換成正式 API client 並重跑回歸集（6.9 第 5 條），模型定案期限是 11/15（6.9 第 2 條）。
- 11/20 凍結前不要 `brew upgrade codex`。

## 試刊期間每天的盲計對照表雜湊（👤 志晨）

06:00 準備後，P、M 都有稿的日子會自動匯出到 `annotation/YYYY-MM-DD/`（blind.txt、spot-check.txt、mapping.sha256），對照表本體在 `annotation/_private/YYYY-MM-DD/mapping.json`。每天**交給 B 之前**：

1. 確認當天資料夾裡只有 blind.txt、spot-check.txt、mapping.sha256（或 0 篇時的 README.txt），沒有 `_private/`。
2. 先看要記的那一行（不寫檔）：

   ```bash
   uv run python scripts/collect_blind_hashes.py --start 2026-11-09 --end 2026-11-09
   ```

3. 寫進 `docs/eval/blind_mapping.sha256` 並 commit（只 commit 雜湊，對照表本體與 `annotation/` 都不進 repo）：

   ```bash
   uv run python scripts/collect_blind_hashes.py --start 2026-11-09 --end 2026-11-09 --write
   git add docs/eval/blind_mapping.sha256
   git commit -m "docs(eval): blind mapping hash for 2026-11-09"
   ```

4. commit 之後才把 `annotation/YYYY-MM-DD/` 交給 B。

- 腳本只讀 `annotation/YYYY-MM-DD/mapping.sha256`，不讀 `_private/`；已記過的日期跳過，同一天雜湊不同會停（表示當天重匯出過，要人工確認交給 B 的是哪一份）。
- 沒有 mapping.sha256 的日子（0 篇只有 README.txt、或兩組沒有都出稿）會跳過並在 stderr 註明，照實記進週報。
- 第一次 commit 這個檔之後，`tests/test_mas_steps.py::test_real_blind_mapping_hash_is_committed` 會變 XPASS，到時拿掉 xfail。
