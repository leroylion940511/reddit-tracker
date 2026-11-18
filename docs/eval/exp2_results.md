# 實驗二結果：查核員開與關

- 產生時間：2026-11-19 06:18 台北；腳本 `scripts/run_exp2.py`
- 模型：`gpt-6.1-sol | codex-cli 0.166.0 | reasoning_effort=low`；`FACT_CHECKER_PER_SOURCE`＝關（只影響 (c) 組）
- 案例：開發集 5（E01–E05）、保留集 5、正常稿 15。保留集用實驗一的最終標註產生。
- 記者 v1 只產生一次（25 篇，各 1 次模型呼叫），三組共用；下表的 LLM 呼叫數不含這 25 次。
- 擋下＝最終版不再引用無關來源，或稿件 HOLD。誤擋＝正常稿 HOLD，或有來源被刪掉。
- 只能說「在這些案例上」；結論以保留集為主，開發集是查核工具設計時就看過的案例。

| 設定 | 開發集擋下 | 保留集擋下 | 正常稿誤擋 | LLM 呼叫數（其中查核員） |
| --- | --- | --- | --- | --- |
| (a) 全關 | 0/5 | 0/5 | 0/15 | 1（0） |
| (b) 只開程式工具 | 5/5 | 2/5 | 6/15 | 14（0） |
| (c) 程式＋LLM | 5/5 | 1/5 | 0/15 | 21（14） |

保留集只有 5 篇（上限 10）：實驗一 test 裡符合條件的配對就這麼多，照實報。

## 逐案結果

每格：最終狀態／版本數／被刪的來源數；✅＝擋下，❌＝沒擋，⚠️＝誤擋。

| 案例 | 類別 | (a) 全關 | (b) 只開程式工具 | (c) 程式＋LLM | 說明 |
| --- | --- | --- | --- | --- | --- |
| E01 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 1 | ✅ checked／v2／刪 1 | 來源混進 AP 美式足球報導（Seahawks 20-3 win） |
| E02 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 5 | ✅ checked／v2／刪 5 | 6 個來源有 3 個是蔣萬安競總／沈伯洋後援會 |
| E03 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 1 | ✅ checked／v2／刪 1 | 併入 HN「Switzerland. Block by block」，正文還寫了瑞士地圖 |
| E04 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 2 | ✅ checked／v2／刪 2 | 併入 Skydance 優離：都有 buyout，但是兩件事 |
| E05 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 1 | ✅ checked／v2／刪 1 | 附了不相關的 PTT「Anthropic 遞交 IPO」，正文也寫進去 |
| H-T106 | holdout | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | 實驗一 T106：same／only_a，方法 A 合併、最終答案不是 |
| H-T457 | holdout | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | 實驗一 T457：same／both，方法 A 合併、最終答案不是 |
| H-T523 | holdout | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | 實驗一 T523：cross／both，方法 A 合併、最終答案不是 |
| H-T767 | holdout | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 2 | ✅ checked／v2／刪 2 | 實驗一 T767：cross／only_a，方法 A 合併、最終答案不是 |
| H-T807 | holdout | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 2 | ❌ checked／v1／刪 0 | 實驗一 T807：same／both，方法 A 合併、最終答案不是 |
| N-41480 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-09 M 組稿 41480 |
| N-44224 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-10 M 組稿 44224 |
| N-44227 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-10 M 組稿 44227 |
| N-44229 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-10 M 組稿 44229 |
| N-44245 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-10 M 組稿 44245 |
| N-48568 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-11 M 組稿 48568 |
| N-48569 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-11 M 組稿 48569 |
| N-48575 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-11 M 組稿 48575 |
| N-54425 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-12 M 組稿 54425 |
| N-54434 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 3 | checked／v1／刪 0 | 2026-11-12 M 組稿 54434 |
| N-59775 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-13 M 組稿 59775 |
| N-64577 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-14 M 組稿 64577 |
| N-69852 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-15 M 組稿 69852 |
| N-69866 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-15 M 組稿 69866 |
| N-69869 | normal | checked／v2／刪 0 | checked／v2／刪 0 | checked／v2／刪 0 | 2026-11-15 M 組稿 69869 |
