# Reddit Tracker — 專案進度（現為 v2.0 AI 綜合日報）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 現行企劃見 `docs/AI_NEWS_COMPANY_PROPOSAL.md`、規格入口見 `docs/v5/README.md`。
> 2026-10-29 以前的段落已搬到 `docs/archive/`（見文末「更早的紀錄」）。
> 下面各段裡的「➡️ 下一步」是當時寫的，現況一律以本節「下一步」為準。

**Last updated:** 2026-11-23（`claude-auto`：實驗三 B（agy）盲計 7 期完成、`docs/eval/exp3_results.md` 已寫入）。前次：2026-11-22（`claude-auto`：M 組出刊前模型雜訊檢查 `MAS_NOISE_CHECK`，預設關閉；志晨同意後 fast-forward 併入 main，開關沒開、不需重載）。前次：2026-11-21（`claude-auto`：merge main 解 PROGRESS.md／exp2_results.md 衝突；`report --write` 改成保留手寫分析；志晨同意後 fast-forward 併入 main `c335f2c`→`claude-auto`，不需重載）。前次：2026-11-19（`claude-auto`：實驗二報告補「被刪的來源」一節）。前次：2026-11-19（實驗二報告補上錯誤分析／結論／限制草稿，待志晨改寫）。前次：2026-11-19 06:20（實驗二三組完成，`docs/eval/exp2_results.md` 已寫入；(c) 雜訊掃描乾淨；main 已 push `4d7c61f`）。前次：2026-11-18 07:40（實驗二 `run` 第一天：(a)(b) 完成、(c) 停在 H-T807，11/19 接著跑；`claude-auto` 離線模型雜訊掃描，還沒併入 main）。前次：2026-11-17 14:30（實驗二：A＝grok 選完 15 篇、`build`、`draft --live` 25/25 完成；明天 `run`）。前次：2026-11-17（實驗二 `build` 檢查正常稿來自候選清單，已 fast-forward 併入 main，不需重載；main 還沒 push）。前次：2026-11-16（實驗二正常稿抽樣修正已 fast-forward 併入 main，不需重載；main 已 push）。前次：2026-11-15 19:08（HOLD 稿改標「暫扣」已併入 main 並部署；main 還沒 push）；再前次：2026-11-15 07:10（`claude-auto` 開發）；前次：2026-11-14 19:42（關閉人工核可＋併入 desk-v3 並部署；main 已 push）；再前次：2026-11-13 晚（實驗一結果已存檔：`docs/eval/cluster_pairs_v1.csv`、`exp1_results.md`，已併入 main；服務沒有重載、不需要；main **還沒 push**）

## 線上現況（2026-11-13 查證）

- newsroom、rsshub 兩個 LaunchAgent 都在跑。**Mac 在 11/12 18:56 重開機，newsroom 於 18:59 重新啟動，載入的已是 `feat/newsroom-3d` 併入後的程式**（下面 11/12 段落寫的「服務沒有重載」只到重開機前為止）。重開機那一輪 RSSHub 比 newsroom 晚起來，11 個 RSSHub 來源連線被拒，下一輪恢復。
- 11/13 是新程式的第一期：06:00–06:05 準備（P 影子 5 次、M 28 次 Codex），12 篇、`degraded=[]`；12 篇於 07:06 核准；08:35 發行（Telegram 533、534）。
- 查證當下 main 領先 origin/main 3 個 commit（`ff87ca0`、`7f72c69`、`4446959`）；部署後共 9 個，**還沒 push**。
- production DB 523 MB、Alembic `b8d4f0a17c33`。全套（production checkout，有母本）413 passed／4 skipped。

## 本次變更（2026-11-23 — 實驗三盲計與結果，`claude-auto`）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只唯讀讀了 production 的 `annotation/2026-11-{09..15}/`（blind.txt、mapping.sha256）、`annotation/_private/` 對照表與 `newsroom.log`；沒碰任何 DB、沒呼叫 Codex。`main` 沒有新 commit，merge 不需要。

- ✅ **起因**：實驗三（手冊 8.3，三個必做實驗之一）只差 B 的錯誤計數；B 改由 agy 代標（2026-11-17 志晨確認），一直沒有跑。
- ✅ 11/14、11/15 的對照表雜湊先 commit（`3e11801`）再交給 B。
- ✅ B＝agy 逐期盲計（提示詞 `docs/eval/exp3/prompt_B_count.md`、schema `schema_count.json`；空資料夾、`--mode plan --sandbox`；每期只跑一次），7 期 56 篇全部完成；解析後的標註與理由存 `docs/eval/exp3/B_labels.json`，原始輸出在 worktree `annotation/exp3/`（gitignored）。
- ✅ `reddit_tracker/eval/exp3.py`＋`scripts/exp3_results.py`：沿用 `analyze_blind`，逐期／合計主指標、M−P、exact 符號檢定、七類、猜組別、逐篇明細；對照表沿用 `analyze_blind_count._load` 驗雜湊；`--write` 保留手寫分析。介面見 README 腳本表。
- 📌 **結果**（`docs/eval/exp3_results.md`）：M 每 10 篇 3.2 個第 1–5 類錯誤、P 5.0 個（各 28 篇）；逐期 4 期 P 較多、3 期 M 較多，符號檢定 p=1 → 看不出一致差異。兩組最多都是無關來源（P 8、M 5）；P 的標題與內文不一較多（5 vs 2），多半是一次寫整版造成正文截斷（混淆因素）。7 期無降級、抽樣無 HOLD；B 猜組別 0.42，盲化沒失效。錯誤分析／結論／限制已直接定稿在報告標記以下。
- ⚠️ 11/14、11/15 雜湊比手冊要求晚記（交 B 前有 commit，但不是當天），報告已照實寫。
- 待補（需 production DB，只讀）：試刊 7 期成本列 `scripts/trial_metrics.py --start 2026-11-09 --end 2026-11-15`，填進 `exp3_results.md`「結論」的倍數。
- 測試：新增 `tests/test_exp3.py` 6 個；全套 514 passed／7 skipped（worktree 沒有母本）；ruff 通過。只動評估腳本與文件，不需要 migration、不需重載。
- ✅ 2026-11-23 07:29 已 fast-forward 併入 main（`dafaf4c`→`f1843f8`）；production 全套 517 passed／4 skipped，production 上不帶 `--write` 重產數字一致。只動評估腳本與文件，newsroom **沒有重載、不需要**。main **還沒 push**。

## 本次變更（2026-11-22 — M 組出刊前模型雜訊檢查 `MAS_NOISE_CHECK`，`claude-auto`，已 fast-forward 併入 main）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只讀了 `newsroom.log`（11/22 06:00 準備正常：12 篇、`degraded=[]`，06:05 完成）；沒碰任何 DB、沒呼叫 Codex。`main` 沒有新 commit，merge 不需要。

- ✅ **起因**：11/18 做好的雜訊偵測（`daily/noise.py`）寫明「凍結後接成輸出檢查」；11/20 已過，但 `final-1120` tag 還沒打（`trial-dates.md` 寫「待老師確認」），所以做成**預設關閉的開關**，production 行為不變，開不開由志晨決定。
- ✅ `orchestrator.noise_hold`：`run_mas` 在文稿編輯之後掃每篇最新版的標題／導言／正文／重要性，命中就發 `system → human` HOLD（payload 帶命中片段），寫進 `MasResult.noise_log`；`run.py` 有命中時 `edition.stats["noise_hold"]`。不重試、不多呼叫模型、不改請求與 `request_hash`；HOLD 稿照現有規則發行時只出標題（「暫扣」）。設計與介面見 `DAILY_EDITION.md`「模型雜訊檢查」。
- 選 HOLD 不選重試：重試會多呼叫 Codex、改變實驗紀錄的呼叫數；試刊與實驗二期間只有 69855 一篇命中，HOLD 的代價是偶爾少一篇全文。
- ⚠️ 雜訊若在 `headline`，暫扣稿的標題仍會印出（目前沒有案例）。
- 測試：新增 `tests/test_noise_hold.py` 3 個（關閉時 69855 原文照常出全文、開啟時只扣那一篇、重跑不重複發 HOLD）；全套 508 passed／7 skipped（worktree 沒有母本）；ruff 通過。不需要 migration。
- ✅ 志晨同意後已於 2026-11-22 fast-forward 併入 main（`eb0fe2f`→本筆紀錄）；**開關沒開**，`.env` 沒動，newsroom **沒有重載、不需要**。main **還沒 push**。
- 👤 要開的話：production `.env` 加 `MAS_NOISE_CHECK=true` → `deploy/install_launchd.sh newsroom-reload`（下一次 06:00 準備起生效）。

## 本次變更（2026-11-21 — 實驗二 `report --write` 保留手寫分析，`claude-auto`，已 fast-forward 併入 main）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。沒讀 production 資料、沒碰任何 DB、沒呼叫 Codex。

- ✅ **merge main**（`754ccaa`）：`PROGRESS.md`、`docs/eval/exp2_results.md` 兩個 Markdown 衝突，兩邊都保留。報告順序＝程式產生的「被刪的來源」在前、main 的錯誤分析／結論／限制草稿在後；兩節的數字互相核對過（(b) 正常稿刪 8 則、E02／H-T767／H-T807 的連帶誤刪數一致）。push 狀態兩邊說法不同，以 main 為準（`4d7c61f` 已 push）。沒有重跑 `report`（arm DB 與 results 在 production 的 `data/work/exp2/`，不碰）。
- ✅ **起因**：手寫分析放在 `exp2_results.md` 裡，`report --write` 會整檔覆寫，所以只能靠「不要再跑」的口頭規定；日後補跑（例如 `--per-source`）或改產生段落都會把分析洗掉。
- ✅ `eval/exp2.py` 新增 `MANUAL_MARKER`、`keep_manual(report, existing)`：舊檔有標記 → 標記那行以下原樣接回新報告；沒標記卻有程式不會產生的 `## ` 小節 → `Exp2Error` 停（exit 2），不覆寫。`run_exp2.py report --write` 寫檔前先過這一步。
- ✅ `exp2_results.md` 在手寫段落前加標記行（HTML 註解，渲染看不到），說明文字改成「重跑只重產標記以上」。
- 測試：`test_exp2.py` +2（標記保留／重跑不變／沒標記就停；以及實際報告檔有標記、手寫三節在標記之下）；全套 505 passed／7 skipped（worktree 沒有母本）；ruff 通過。只動評估腳本，不需要 migration、不需重載服務。
- ✅ 志晨同意後已於 2026-11-21 fast-forward 併入 main（`c335f2c`→本筆紀錄）；只動評估腳本，newsroom **沒有重載、不需要**。main **還沒 push**。之後在 production checkout 跑 `report --write` 會保留標記以下的手寫分析。

## 本次變更（2026-11-19 — 實驗二報告補「被刪的來源」，`claude-auto`，2026-11-21 已併入 main）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只唯讀讀了 production 的 `data/work/exp2/{cases,v1,results_a,results_b,results_c}.json`；沒碰任何 DB、沒呼叫 Codex、不改線上流程。

- ✅ **起因**：`exp2_results.md` 只算「無關來源有沒有被刪」與「正常稿有沒有被刪」，看不出開發集／保留集裡**正當來源被連帶刪掉**的情況，報告寫 H-T807 取捨時會漏掉這個代價。
- ✅ `reddit_tracker/eval/exp2.py`：`removal_counts(outcomes, cases)`（刪除數／刪對／連帶誤刪）與 `render_report` 結尾新增「## 被刪的來源」：每組一列統計＋逐筆明細（item_id、來源、標題前 40 字、判定）。判定只用 `cases.json` 的 `wrong_item_ids`，不重跑、不讀 arm DB。
- ✅ `docs/eval/exp2_results.md` 用同一批 results 重產（主表與逐案表數字不變，只多一節；產生時間保留 06:18 並註明補產）。
- 📌 **新結果**（給報告用）：

  | 設定 | 刪除數 | 刪對（無關來源） | 連帶誤刪 |
  | --- | --- | --- | --- |
  | (b) 只開程式工具 | 22 | 10 | 12（E02 2、H-T767 1、H-T807 1；正常稿 6 篇共 8 則，N-54434 一篇就刪 3 則統一併購肯德基報導） |
  | (c) 程式＋LLM | 12 | 9 | 3（E02 兩則蘇清泉道歉報導、H-T767 中央社幣安） |

  - (c)「正常稿 0 誤擋」不等於沒有誤刪：開發集／保留集仍連帶刪了 3 個正當來源，這 3 個 (b) 也同樣刪了——查核員 LLM 沒有救回程式工具在**有無關來源的稿**上多刪的部分，只在正常稿上把程式工具的刪除全部否決。
  - H-T807：(b) 刪的 2 則裡 1 則是無關來源（自由時報 TVBS 民調）、1 則是連帶誤刪（風傳媒）；(c) 兩則都保留。
  - 👤 報告寫 H-T807 取捨時一起寫這點。
- 測試：`tests/test_exp2.py` 新增 1 個、擴充 1 個；全套 503 passed／7 skipped（worktree 沒有母本）；ruff 通過。不需要 migration、不需重載服務。
- 重產指令（日後 results 變動時）：在 production checkout `uv run python scripts/run_exp2.py report --write` 即可，會自帶新一節（產生時間會換成當下）。

## 本次變更（2026-11-18 — 離線模型雜訊掃描，`claude-auto`，已 fast-forward 併入 main：`0396c87`→`8b6cdbb`）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只讀了 `newsroom.log`（11/18 06:00 準備正常：12 篇、`degraded=[]`，06:08 畫完）與 `data/work/exp2/v1.json`；沒碰任何 DB、沒呼叫 Codex。

- ✅ **起因**：11/17 查到 11/15 刊出的 69855 `why_it_matters` 混進 Codex 推理文字，線上沒有擋、11/20 前也不改線上流程；但報告要「照實記」，得先知道試刊與實驗二還有沒有別篇。
- ✅ `reddit_tracker/daily/noise.py`：純函式 `model_noise(text)`／`story_noise(fields)`，規則保守（欄位名接冒號、`{"`／`"}`／`\"`、單獨的 `{`／`}`、英文第一人稱、含推理用語的小寫英文連續 3 字以上；大寫開頭的專有名詞不算）。**線上流程沒接**，凍結後做輸出檢查（重試或 HOLD）時直接沿用。
- ✅ `scripts/scan_model_noise.py`：`--db <檔> --start … --end …`（`mode=ro`，每一版都掃，標最新版／狀態／是否核准）或 `--json data/work/exp2/v1.json`，印 Markdown 表；沒命中印「沒有發現模型雜訊。」。
- ✅ 實跑（全部唯讀）：實驗二 v1（25 篇）、(a)(b)(c) 已跑的稿都沒有雜訊；production 11/01–11/18 兩組所有版本只有 **69855 一篇**（11/15 M 組、最新版、已刊出全文）。第一版規則把 11/15 P 組模板稿 69845 的英文摘要（“grand final”）誤報，已收緊為「小寫英文串要有 2 個以上不同推理用語」並加進測試。
- 👤 報告寫法建議：試刊與實驗二期間共 1 篇刊出稿混入模型雜訊（69855 `why_it_matters`），偵測規則與掃描指令如上；凍結後才接線上檢查。
- 測試：新增 `tests/test_model_noise.py` 6 個（含 69855 原文、帶英文專有名詞的正常中文稿不誤報、腳本唯讀）；全套 502 passed／7 skipped（worktree 沒有母本）；ruff 通過。不改提示詞、`request_hash`、線上流程；不需要 migration。
- 實驗二 (c) 跑完後再掃一次：`uv run python scripts/scan_model_noise.py --db /Users/leroy/reddit_tracker/data/work/exp2/arm_c.db --start 2026-11-17`（三組的稿在 `arm_{a,b,c}.db`，出刊日一律記成 2026-11-17）。

## 實驗二執行（2026-11-17 — 選稿、案例凍結、記者 v1）

- ℹ️ **2026-11-17 志晨確認：專題沒有人類標註員 A、B，改由 CLI 代替——A＝grok CLI（`grok -p`，grok-4.7），B＝agy CLI。** 手冊寫「A／B 做」的步驟（選稿、標註、盲計計數）都直接用這兩個工具跑，提示詞與原始輸出存 `annotation/`；報告要註明是 AI 工具代標。
- ✅ **候選 25 篇**：production DB 唯讀重算 `sample_exp2`（11/09–11/15、種子 `20261211`），清單 `data/work/exp2/candidates_for_A.md`；給 A 的全文＋來源題目檔 `annotation/exp2/candidates_packet.txt`。
- ✅ **A（grok）選稿**：提示詞 `annotation/exp2/prompt_A_pick.md`、schema `schema_pick.json`、原始輸出 `A_pick_raw.json`、解析後 `A_pick.json`。判定 ok 18／problem 7，picks 15：`41480,44224,44227,44229,44245,48568,48569,48575,54425,54434,59775,64577,69852,69866,69869`（全在候選內、無重複、全為 ok；排除較沒把握的 59769、59771、64571）。grok 只跑一次，沒有重抽或挑結果。
- ✅ `build --force --normal-ids … --sample-dates 2026-11-09,…,2026-11-15`：開發集 5、保留集 5（T106、T457、T523、T767、T807）、正常稿 15；舊的 11/13 試跑版改名 `cases.trial-20261113.json`。
- ✅ `draft --live`（14:23–14:28）：v1 25/25，帳本 25 次 Codex 嘗試、沒有重試；人工掃過沒有模板稿或模型雜訊。
- ⚠️ **線上品質問題（A 發現、已查證）**：11/15 已刊出的 M 組稿 69855（許淑華／蔣萬安）`why_it_matters` 在 `[S1]` 後面夾著模型雜訊「内 wait stop wrong? final already text need close proper. } … I'm generating need valid JSON exact.」。Codex 回傳的 JSON 欄位混進推理文字，目前流程沒有擋。11/20 前不改線上流程；凍結後加輸出檢查（欄位出現英文雜訊／JSON 字樣就重試或 HOLD），報告照實記。
- ✅ **11/18 07:19–07:22 `run --arm all --live`（Claude 依志晨指示在 production checkout 跑）**：本次 25 次新的 Codex 嘗試全部用完（(a) 1、(b) 13、(c) 11），沒有失敗重試。
  - (a) 全關：dev 0/5、保留集 0/5 擋下，正常稿誤擋 0/15。
  - (b) 只開程式工具：dev 5/5、保留集 2/5 擋下，正常稿誤擋 **6/15**。
  - (c) 程式＋LLM：跑到保留集最後一篇 H-T807 時額度用完（`degraded=['copy_editor','fact_checker']`），**這一組不算**，`results_c.json` 沒寫；已成功的 11 次在帳本，重跑會重播。
  - 沒有跑 `report --write`（(c) 沒完成，報告會缺一組）。
- ✅ **11/19 06:17–06:18 `run --arm all --live`（Claude 依志晨 11/18 交代在這個 session 排程執行；06:00 準備已於 06:08 跑完）**：(a)(b) 全部重播；(c) 新的 Codex 嘗試 10 次，全部成功、沒有重試、沒有 `degraded`。三組 `results_{a,b,c}.json` 都寫好。
  - **最終結果**（[`docs/eval/exp2_results.md`](docs/eval/exp2_results.md)，`report --write` 06:18）：

    | 設定 | 開發集擋下 | 保留集擋下 | 正常稿誤擋 | LLM 呼叫（查核員） |
    | --- | --- | --- | --- | --- |
    | (a) 全關 | 0/5 | 0/5 | 0/15 | 1（0） |
    | (b) 只開程式工具 | 5/5 | 2/5 | 6/15 | 14（0） |
    | (c) 程式＋LLM | 5/5 | 1/5 | 0/15 | 21（14） |

  - 讀法：程式工具抓得到可疑來源，但單獨用會誤刪 6/15 篇正常稿的來源；加 LLM 查核員後誤擋降到 0/15，代價是保留集少擋一篇——**H-T807**：(b) 刪 2 個來源，(c) 查核員有跑（1 次）但判定保留，維持 v1。保留集只有 5 篇，只能說「在這些案例上」。
  - 模型雜訊：`scan_model_noise.py --db data/work/exp2/arm_c.db --start 2026-11-17` →「沒有發現模型雜訊。」
  - ✅ 2026-11-19 `exp2_results.md` 已補「錯誤分析」（4 類：(b) 認不出中文名字而誤擋、H-T807 事件定義寬嚴、同人物不同事件程式不點名、擋下時連正確來源一起刪——H-T767 是 `FACT_CHECKER_PER_SOURCE` 關閉造成的）、「結論」、「限制」，是 Claude 寫的草稿。⚠️ **不要再跑 `report --write`**，會覆寫這幾節（2026-11-21 已解除：`report --write` 改成保留標記以下的手寫段落，已併入 main）。
  - 👤 志晨讀過改成自己的話。原本列的要寫：H-T807 的取捨（(c) 少擋一篇換正常稿 0 誤擋）、保留集樣本小、A／B 是 AI 工具代標、11/18 那輪 (c) 因額度中斷而在 11/19 接續（帳本重播，已成功的呼叫沒有重做）。
- 原計畫（已完成）：`run --arm all --live`（約 25–35 次；不要在 06:00–06:10 跑；額度不夠 11/19 用同一指令接著跑）→ `report --write`。✅ `FACT_CHECKER_PER_SOURCE` **定案維持關閉**（2026-11-17，志晨交給 Claude 決定）：(c) 與試刊七期／實驗三的 M 組是同一個查核員設定，結果才能對照；手冊只有三組，額度也緊，所以不另跑 `--per-source`。報告註明逐來源判斷是已實作但未評估的選項。

## 本次變更（2026-11-17 — 實驗二 `build` 檢查正常稿來自候選清單，`claude-auto`，已併入 main）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只讀了 `newsroom.log`，沒碰 production DB、沒呼叫 Codex。

- 線上：11/17 06:00 準備正常（版本守門 ok、12 篇、`degraded=[]`；06:05 有一次 Codex 150 秒逾時，重試成功，06:08 畫完）。⚠️ `mirrormedia-political`（RSSHub `/mirrormedia/category/political`）從 11/15 19:54 起每次都 503，`nikkei-asia` 11/16 晚起偶發 503；是上游／RSSHub 路由問題，沒改來源設定（11/20 前不動收集條件），👤 要不要設 `keep_items: true` 停用等凍結後決定。
- ✅ **問題**：`run_exp2.py build --normal-ids` 只檢查 id 重複與「有寫過正文」，A 若打錯成另一篇有寫過稿的 story（或抄到別天），會默默變成正常稿案例。
- ✅ **修正**：`eval/exp2.py` 新增 `check_normal_pick`；`build` 新增 `--sample-dates`（＋可選 `--sample-seed`，預設 `EXP2_SEED`），給了就在 production 唯讀 session 重算 `sample_exp2`，選稿不在 25 篇候選裡就停（`Exp2Error`，exit 2）。沒給只印警告，舊指令照舊能跑。腳本說明與 `EXP2_DESIGN.md` 已同步。
- 不改提示詞、`request_hash`、線上流程；不需要 migration。
- 測試：`test_exp2.py` +1；全套 496 passed／7 skipped（worktree 沒有母本）；ruff 通過。沒有用真實資料跑 `build`（worktree 沒有實驗一的快照與標註檔）。
- ✅ 志晨同意後已於 2026-11-17 fast-forward 併入 main（`42726de`→`376f840`）；只動評估腳本，newsroom **沒有重載、不需要**。production checkout `test_exp2.py`＋`test_blind_sampling.py` 28 passed。main **還沒 push**。
- 👤 實驗二 `build` 請用 `--normal-ids … --sample-dates 2026-11-09,2026-11-10,2026-11-11,2026-11-12,2026-11-13,2026-11-14,2026-11-15`（日期要和給 A 清單時的 `sample_exp2.py --dates` 相同）。

## 本次變更（2026-11-16 — 實驗二正常稿抽樣修正，`claude-auto`，已併入 main）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只讀了 `newsroom.log`（11/16 06:00 準備正常：版本守門 ok、12 篇、`degraded=[]`），沒碰 production DB、沒呼叫 Codex。

- ✅ **問題**：`sample_exp2`（給 A 挑 15 篇正常稿的 25 篇候選）從當天**全部** M 組 `stories` 抽；但 `run_mas` 會把快照裡每個候選事件（每天約 4,800 個）都寫成 `stories`，真的寫過稿的只有 12 篇，所以抽到的幾乎都是沒寫過稿的候選。另外 `scripts/sample_exp2.py` 沒把專案根目錄加進 `sys.path`，照文件跑會 `ModuleNotFoundError`；輸出只有 id，A 看不到標題。
- ✅ **修正**：`daily/blind.py` `sample_exp2` 改從 `_written`（送核准前最新版、正文非空，含 HOLD）抽，依 story id 排序後再抽、輸出也排序；新增 `describe_exp2`。`scripts/sample_exp2.py` 補 `sys.path`，第一行仍是逗號分隔 id，下面印 Markdown 表（日期、版別、狀態、來源數、標題）。`eval/exp2.py` `normal_cases` 遇到重複 id 或沒寫過正文的 story 直接停（`Exp2Error`）。
- 不改提示詞、`request_hash`、線上流程；不需要 migration。`EXP2_DESIGN.md` 已同步。
- 測試：`test_blind_sampling.py` +2、`test_exp2.py` +1；全套 495 passed／7 skipped（worktree 沒有母本）；ruff 通過。用暫存 DB 實跑 `sample_exp2.py` 確認候選池的 story 不會被抽到。
- ✅ 志晨同意後已於 2026-11-16 fast-forward 併入 main（`cf61c30`→`8e4ea93`）；只動評估腳本，newsroom **沒有重載、不需要**。production checkout 相關測試 56 passed。main 已於 2026-11-16 push（`a315e42`）。
- 👤 **11/17 實驗二**：A 選稿前在 production checkout 跑 `uv run python scripts/sample_exp2.py --dates <日期>`。日期範圍設計文件沒寫死，建議用試刊七期（11/09–11/15）。若已經用舊版抽過並給了 A，舊清單要作廢重抽。

## 部署（2026-11-14 19:42 台北 — 關閉人工核可＋併入 desk-v3，依志晨指示）

- ✅ `feat/desk-v3` 併入 `feat/no-approval`（只有 `config.py` 設定區衝突，兩邊都保留），全套 491 passed／7 skipped；main fast-forward `ada70ef`→`da0bd4b`。
- ✅ 備份 `~/Documents/Developer/Lab/reddit_tracker_backups/deploy-20261114/`（sqlite `.backup`、integrity ok；`.env` 複本）。
- ✅ `uv run alembic upgrade head`：`b8d4f0a17c33`→`c5e1a9d3f207`（新表 `item_fulltext`，只新增表）。
- ✅ production `.env` 加 `DAILY_REQUIRE_APPROVAL=false`；`deploy/install_launchd.sh newsroom-reload` 一次。log 有 `codex version guard ok: codex-cli 0.166.0`、三個 job 已註冊、scheduler Python process 1 個；首輪收集 19:42 ok。rsshub 未動。
- desk-v3 的開關（`MAS_RICH_CONTEXT`、`MAS_OPEN_LAYOUT`、`MAS_MORE_INTERACTION`、`FULLTEXT_ENABLED`、`MAS_REPORTER_FULLTEXT`）**全部維持關閉**，M 組請求與 `request_hash` 不變；開啟順序、風險與要人工確認的事見 [`docs/pr/desk-v3.md`](docs/pr/desk-v3.md)。原本計畫 11/20 後才併入，提前併入但未開啟任何行為。
- 👀 11/15 06:00 是第一期不需核可：08:35 發行的稿應全部是全文，只有 HOLD 的稿只出標題。
- ⚠️ 試刊最後一天（11/15）與實驗紀錄從此沒有 `approved_by`；回放頁沒有 approve 階段。報告要說明「11/15 起關閉人工核可」。

## 部署（2026-11-15 19:08 台北 — HOLD 稿改標「暫扣」，依志晨指示）

- ✅ main fast-forward `bc8b03c`→`ddc75b6`（`claude-auto` 的兩個 commit）。不需要 migration、`.env` 沒動。
- ✅ 備份 `~/Documents/Developer/Lab/reddit_tracker_backups/deploy-20261115/`（sqlite `.backup`、integrity ok）。
- ✅ `uv sync` 後 `deploy/install_launchd.sh newsroom-reload` 一次。log 有 `codex version guard ok: codex-cli 0.166.0`、三個 job 已註冊、scheduler Python process 1 個；首輪收集 19:08 ok。rsshub 未動。
- ⚠️ main 領先 origin/main 2 個 commit（加上這筆紀錄是 3 個），**還沒 push**。
- 👀 11/16 08:35 若有 HOLD 稿，網頁應顯示「暫扣」而不是「未核准」。11/15 已發行的那期沒有重畫。

## 本次變更（2026-11-15 — HOLD 稿不再誤標「未核准」，`claude-auto`，已部署）

自動開發 session，worktree `~/Documents/Developer/Lab/rt-wt-auto`。只讀了 `newsroom.log`（11/15 06:00 準備正常：版本守門 ok、Codex 呼叫全部成功），沒碰 production DB、沒呼叫 Codex。

- ✅ **問題**：`DAILY_REQUIRE_APPROVAL=false`（production 11/14 起）時只有 HOLD 的稿會被扣，但網頁仍印標籤「未核准」與「未核准，本期不發行全文。」，原因寫錯。
- ✅ **修正**（`cc27143`）：`ViewArticle.withheld_reason`（`hold`／`unapproved`，`daily/view.py` `_withheld_reason`）；`render.py` 依原因選字：HOLD →「暫扣」／「本稿暫扣，本期不發行全文。」，要核可而沒核可才是「未核准」。核可開啟時 HOLD 的稿也改寫「暫扣」（`daily hold` 後重畫的網頁同樣）。Telegram 摘要本來就不列被扣的稿，不受影響。
- 不改提示詞、`request_hash`、發行規則（哪些稿出全文完全不變）；不需要 migration。README、`DAILY_EDITION.md` 已同步。
- 全套 492 passed／7 skipped（worktree 沒有母本）；ruff 通過。
- ✅ 志晨同意後已於 2026-11-15 19:08 部署，見上一節。

## 本次變更（2026-11-14 — 可關閉人工核可，`feat/no-approval`）

- ✅ 新設定 `DAILY_REQUIRE_APPROVAL`（預設 `true`＝原行為）。`false` 時 mas 發行不需要 `daily approve`：checked／draft／challenged 都發全文，只有 HOLD 的稿照樣只出標題。閘門在 `daily/view.py` `_withheld_status`，網頁與 Telegram 共用。
- ⚠️ 關掉會改變試刊（到 11/15）與實驗紀錄的條件：`approved_by` 不再有值、回放頁的 `approve` 階段消失；手冊步驟 10 原本要求真人核可，交報告時要說明。
- 全套 428 passed／7 skipped（worktree 沒有母本）。不需要 migration、不改提示詞與 `request_hash`。
- ✅ 已部署，見上一節。

## 本次變更（2026-11-13 晚 — 實驗一結果存檔，`docs/exp1-results`）

- ✅ `scripts/exp1_results.py --write` 正式跑一次：`docs/eval/cluster_pairs_v1.csv`（100 組，**寫了就不能改**；sha256 `01466b64…cd084`）與 [`docs/eval/exp1_results.md`](docs/eval/exp1_results.md)（結果表、信賴區間、McNemar、κ、3 個錯誤分析、結論、標註限制）。`exp1-frozen`＝`5f31fab`。
- **結果（test 50 組）：C 沒有比 A 好。** C：Precision 0.68／Recall 0.43／F1 0.53／錯誤合併率 0.30；A：0.80／0.67／0.73／0.25；exact McNemar p = 0.115（A 對 14、C 對 6），不顯著。C 判錯 23 組，漏併 17、錯併 6。
- 3 個錯誤分析：彙整型「早報」被併進單一事件（T457、T523）；英文標題相似度低於 0.28 且句首 Binance 不算名字（T336、T425）；譯名表沒有「幣安」（T446、T629）。⚠️ 錯誤分析是 Claude 依快照與凍結的程式查出來寫的草稿，手冊要求開發者寫，請志晨看過再交。
- ⚠️ 標註是 AI 工具標的（老師同意），報告裡的 κ = 0.44 是兩個模型之間的一致程度；報告「標註的限制」一節有寫。
- 不要因為這個結果在 11/20 前回頭改聚合規則：test 只能跑一次，而且會動到試刊與實驗二、三的條件。要改留到凍結後，並在報告說明。

## 本次變更（2026-11-13 晚 — 實驗二執行腳本＋清理，`feat/exp2-runner`）

- ✅ **實驗二三組執行**：`scripts/run_exp2.py`（`build`／`draft`／`run`／`report`）＋`reddit_tracker/eval/exp2.py`，設計與理由在 [`docs/eval/EXP2_DESIGN.md`](docs/eval/EXP2_DESIGN.md)。`review_one` 多了 `checker_mode`（`full`／`program`／`off`）與 `draft`（已存檔的 v1）兩個參數，**預設值就是線上原本的行為，請求與 `request_hash` 不變**（錄音重播測試照過）。
- ✅ 用真實資料試過 `build`（唯讀）：開發集 5（E01–E05）、保留集 5（T106、T457、T523、T767、T807）。沒有呼叫 Codex。
- ℹ️ **實驗一標註**：2026-11-13 志晨轉述老師同意直接用現有的標註（grok bot 與 agy 標的），不另外重標；保留集就用這份產生。`docs/eval/cluster_pairs_v1.csv` 與 `exp1_results.md` 還沒寫（`scripts/exp1_results.py --write`，寫了就不能改）。
- ✅ **清理（志晨授權）**：production 根目錄 7 個舊 DB 備份、`bot.log`、`scheduler.log` 已刪；`Lab/reddit_tracker_backups` 刪掉 7 個舊的 DB 備份資料夾（3.6 GB → 534 MB），留 `cleanup-20261113` 與幾個小資料夾；8 個舊 worktree 與本機分支已移除（內容比對過都在 main，origin 上的同名分支沒動；`rt-wt-e11` 的錄音 DB 先複製到 production `data/work/1027_e11.db`）；`.env` 刪掉 12 個沒有作用的舊鍵（改之前的複本在 `cleanup-20261113/.env.before-key-cleanup`）。
- 全套 427 passed／7 skipped（worktree 沒有母本）。不需要 migration。

## 本次變更（2026-11-13 — 專案梳理與小修，`chore/cleanup-1113`）

worktree `~/Documents/Developer/Lab/rt-wt-cleanup`。開發時 production 只做唯讀查詢，沒有呼叫 Codex。

- ✅ **已部署（2026-11-13 19:12 台北，依志晨指示）**：fast-forward 併入 main（`4446959`→`b8208b6`），備份 `~/Documents/Developer/Lab/reddit_tracker_backups/cleanup-20261113/`（sqlite `.backup`、integrity ok；`.env` 複本），`uv sync` 後 `deploy/install_launchd.sh newsroom-reload` 一次。log 有 `codex version guard ok: codex-cli 0.166.0`、三個 job 已註冊、scheduler Python process 1 個；首輪收集 19:13 ok 23/23。rsshub 未動，不需要 migration。
- 👀 11/14 06:00 是第一期用新額度檔：準備後 `~/.local/state/reddit-tracker/llm-quota.json` 應該出現。

- ✅ **SQLite 等鎖 5 秒→30 秒**（`db.py`）。11/11 06:06 收集 tick 寫 `ltn-politics` 時撞上 06:00 準備的寫入（`database is locked`），補寫健康紀錄又撞一次，整輪 tick 丟例外。`collect_due_sources` 補寫健康紀錄失敗時改成只記 log，其他來源照常寫入。
- ✅ **額度檔移出 `/tmp`**：`LLM_QUOTA_STATE_PATH` 預設改 `~/.local/state/reddit-tracker/llm-quota.json`（`/tmp` 重開機會被清掉）。⚠️ 部署當下會換檔，當天已用的次數從 0 重新算一次；請在 08:35 發行後部署。
- ✅ **E11 xfail 拿掉**（11/15 到期）：回歸重編這則沒入選，條件是 skip（不適用）；同一個條件由 `tests/test_e11_replay.py` 用 11/06 的錄音離線重播把關，理由寫在 `E11.json` 的 `note`。回歸集現在沒有任何 xfail。
- ✅ 11/13 盲計雜湊寫進 `docs/eval/blind_mapping.sha256`（與 06:05 log 的 sha256 相同）。
- ✅ ruff 4 個未使用的 import／變數清掉；README 的測試基準、來源數、Web 路由更新。
- ✅ PROGRESS 2026-10-29 以前的段落搬到 `docs/archive/PROGRESS_2026-09_to_10-29.md`。
- ✅ 實驗一結果計算腳本 `scripts/exp1_results.py`＋`tests/test_exp1_results.py`（8 個測試，含手冊 8.1 的計算例子）。
- ⛔ 實驗二三組執行腳本這次沒做：要動 `_check_and_maybe_revise`（加「相關性檢查關閉」一組）、v1 只產生一次三組共用、保留集要等實驗一 test 的人工標註、正常稿要等 A 選完，還要先定額度與 `FACT_CHECKER_PER_SOURCE`。先定設計再寫。
- 全套 420 passed／7 skipped（worktree 沒有母本快照，多 3 個 skip）。不需要 migration、不改提示詞與 `request_hash`。

## 下一步（2026-11-13 現況）

日期都是方案 B，見 [`docs/weekly/trial-dates.md`](docs/weekly/trial-dates.md)。依期限排：

1. 👤 **試刊到 11/15**：11/14 起已關閉人工核可，不用再 `approve`；交 B 之前 `scripts/collect_blind_hashes.py --write` 並 commit（11/09–11/13 已記）。
2. ✅ **push main**：2026-11-14 已 push（`bcf0ae3`）。`chore/cleanup-1113` 已於 11/13 19:12 部署。
3. 👤 **實驗一結果**：已存檔（見上）。剩下志晨讀一遍 `exp1_results.md` 的 3 個錯誤分析與結論，改成自己的話；11/22 前。
4. 👤 **請老師確認** `trial-dates.md` 的時程與用本機 Codex 當 LLM（手冊 6.9 第 1 條要正式 API），並告知 A、B。這裡沒有收到確認的紀錄；B 的七類錯誤計數練習（原訂 11/08 前）也沒有紀錄。
5. 👤 **`FACT_CHECKER_PER_SOURCE`**：試刊已用預設關閉在跑；要不要在實驗二 (c) 組打開，最晚 11/17 前定案（`docs/pr/checker-per-source.md`）。
6. ✅ **實驗二**：2026-11-19 三組完成、`docs/eval/exp2_results.md` 已寫入（見「實驗二執行」）。分析／結論／限制草稿已寫進 `exp2_results.md`，剩 👤 志晨讀過改寫。
6b. ✅ **實驗三**：2026-11-23 B（agy）盲計 7 期完成，`docs/eval/exp3_results.md` 已寫入並定稿分析；剩試刊 7 期成本列（`trial_metrics.py`，需 production DB）。
7. **11/20 打 `final-1120` 功能凍結**；之前不要 `brew upgrade codex`。
8. **凍結後的清理**（都不要在 11/20 前做）：
   - `run_mas` 把整個候選池（每天約 4,800 個事件）都寫成 `stories` 並建證據包，實際只用 12 篇；先確認分版主編要不要全池，再改成只處理入選稿。
   - v4／v5 遺留資料表（`candidate_posts` 186 MB、`agent_artifacts` 58 MB、`scoring_records` 12 MB…）與 `models.py` 裡約 20 個遺留 class：交付後寫 drop migration 再 `VACUUM`。
   - origin 上已併入的舊分支還在（本機的 11/13 已刪）；`.env` 備份裡還有舊的 `MINIMAX_API_KEY`，不再用就去撤銷。
   - `docs/v5/` 的歷史檔移到 `docs/archive/`；`CLAUDE.md` 與 `AGENTS.md` 內容相同，擇一為主。
   - `orchestrator.py`（1,163 行）、`run.py`（1,004 行）交付不要求就不拆。
   - ✅ 模型雜訊輸出檢查：2026-11-22 做成 `MAS_NOISE_CHECK`（預設關閉），已併入 main；👤 決定什麼時候開。

- ℹ️ `agent_messages` 有 342 列 11/12 以前的訊息停在 `pending`（結案邏輯 11/13 才生效）。是試刊資料，不回填，報告裡註明。
- ⚠️ 11/04、11/05、11/07–11/12 的 M 組稿都是 08:35 之後才核准，讀者只收到標題短訊；11/13 起是發行前核准。報告照實記。

## 本次變更（2026-11-12 — 手冊對照盤點＋3D 編輯室，`feat/newsroom-3d`）

worktree `~/Documents/Developer/Lab/rt-wt-3d`。查證用 production DB 唯讀複本，沒有呼叫 Codex、沒動 production。細節見 ADAPTATION「2026-11-12 手冊對照盤點與 3D 編輯室」。

- ✅ 3D 編輯室回放 `/daily/<date>/newsroom/office`（`daily/replay.py`、`office_page.py`、`office.html`）；日報頁右下與表格版回放都有入口。three.js 從 jsDelivr 載入，放一份到 `reddit_tracker/daily/vendor/three.module.js` 就能離線。
- ✅ 補齊：`agent_messages.llm_call_id`、訊息真實時間、訊息結案、報頭期號／台北出刊時間、「多來源」標籤、來源列時間、頁尾聲明、盲計雜湊（11/09–11/12）、`scripts/trial_metrics.py`、週報草稿 `docs/weekly/2026-11-10.md`。
- ⚠️ 2026-11-12 晚上依志晨指示 fast-forward 併入 main，但 **newsroom 服務沒有重載**：常駐 process 還是舊程式，06:00 出刊照舊。新程式（訊息時間、llm_call_id、結案、報頭）要等 `deploy/install_launchd.sh newsroom-reload` 或服務自己重啟才生效；試刊到 11/15，👤 決定什麼時候重載。不改提示詞與 `request_hash`，不需要 migration。3D 回放用 `uv run python -m reddit_tracker.web` 就看得到，不用重載。
- ⚠️ **11/07–11/12 的 M 組稿是 11/12 11:03 一次補核准的**（晚於各期 08:35 發行）；試刊 11/09–11/12 四期讀者都只收到標題短訊。
- ⚠️ **實驗一的 100 組是 AI 工具標的**（`annotation/exp1/exp1_resolution.md`），手冊不允許；要標註員 A、B 本人重標。
- ⛔ 還沒有：實驗一結果計算腳本、實驗二三組執行腳本。
- 全套 410 passed／7 skipped。

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

## 更早的紀錄

- 2026-09-13 – 2026-10-29：[`docs/archive/PROGRESS_2026-09_to_10-29.md`](docs/archive/PROGRESS_2026-09_to_10-29.md)
- v4（已廢棄）：[`docs/archive/PROGRESS_v4.md`](docs/archive/PROGRESS_v4.md)
