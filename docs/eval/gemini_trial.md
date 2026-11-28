# Gemini 撰稿試跑（2026-11-28）

目的：評估把綜合日報的模型從 Codex CLI（`gpt-6.1-sol`）換成 Gemini API（Google AI Pro 每月 10 美元 Cloud 額度）。

## 做法

- 複本：`~/Documents/Developer/Lab/rt-data-1123/reddit_tracker.db`（11/23 21:45 `.backup`），每組各複製一份，在 `gemini-trial/` 底下。
- 期別：2026-11-24 M 組，`--now 2026-11-24T06:00`（訊息走真實時鐘，同 `desk-v3-demo/run_live.py`）；開關比照 production（只開 `MAS_NOISE_CHECK`，P 影子關）。
- 程式：分支 `feat/gemini-writer`（`GeminiClient` 送 `responseJsonSchema` 與 `thinkingLevel=low`、`MAX_TOKENS` 視為失敗）。
- 腳本：`gemini-trial/run_trial.sh gemini|codex [模型]`。

選稿是程式做的，四組刊出的 12 個 cluster 完全相同；差異只在撰稿、查核、編輯。

## 結果

| 組別 | 呼叫（成功） | 輸入詞元 | 輸出詞元 | 平均／最長秒 | 英文稿 | 修稿說明外洩 | 退回模板 | CHALLENGE／修完 |
|---|---|---|---|---|---|---|---|---|
| Codex `gpt-6.1-sol` | 30（30） | 333,408 | 6,826 | 8.8／13.2 | 0 | 0 | 0 | 2／2 |
| `gemini-3.5-flash-lite` | 29（29） | 16,686 | 5,482 | 1.2／1.9 | 1（94140） | 1（91713） | 0 | 2／2 |
| `gemini-3.7-flash` | 32（32） | 18,636 | 6,689 | 4.1／7.6 | 0 | 0 | 0 | 4／4 |
| `gemini-3.1-pro-preview` | 31（29） | 16,563 | 27,917 | 8.8／14.4 | 2（93922、94140） | 0 | 1（91992，記者稿 2 次 `MAX_TOKENS`） | 3／3 |

- Codex 的輸入詞元大多是 CLI 自帶的系統提示（每次約 1 萬），直接打 API 只有約 600／次。
- 輸出詞元含思考詞元。Pro 在 `thinkingLevel=low` 仍大量思考，2000 上限下會截斷。
- Flash-Lite：91713 的 deck 與「為什麼重要」寫成修稿說明（「移除S1中矛盾的30多年說法…」），雜訊檢查沒抓到；94140 整篇英文。不可用。
- 3.7 Flash：全中文、無外洩；正文平均 216 字（Codex 191）。91992 跟 Flash-Lite 一樣，漏了 Codex 有寫的「美國官員對間諜說法存疑」。

## 結論

改用 `gemini-3.7-flash`。每期 M 組成本約 0.04 美元（以推出價每百萬詞元輸入 0.75／輸出 3.75 美元計，此價到 2026-12-31，之後未知）；加上 P 影子仍遠低於每月 10 美元。

## 切換前待辦

1. HTTP 402／429 額度耗盡時整期退回 Codex（現在是逐次降級成模板稿，不停也不換模型；試跑時曾整期 30 次 402）。
2. P 影子（一次寫整版，`max_output_tokens=8000`）用 Gemini 跑一期確認。
3. production `.env`：`DAILY_WRITER=gemini`、`GEMINI_DAILY_MODEL=gemini-3.7-flash`、付費 key、放寬 `GEMINI_REQUESTS_PER_MINUTE`；`DAILY_MODEL_VERSION` 改成 Gemini 模型。
4. 報告註明：試刊與實驗一～三用 Codex，切換日起線上改用 Gemini。
