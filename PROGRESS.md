# Reddit Tracker — 專案進度（現為 v2.0 AI 綜合日報）

> 跨 session 的單一狀態真相。每次有實質進展就更新。
> 現行企劃見 `docs/AI_NEWS_COMPANY_PROPOSAL.md`、規格入口見 `docs/v5/README.md`。
> 2026-11-23 以前的「本次變更」段落已搬到 `docs/archive/`（見文末「更早的紀錄」）；正文引用的舊段落請到那裡找。
> 下面各段裡的「➡️ 下一步」是當時寫的，現況一律以本節「下一步」為準。

**Last updated:** 2026-11-26 19:12（`claude-auto`：佇列第 12 項 (3) `FACT_CHECKER_EVENT_CLASSES`，預設關閉，見「本次變更（2026-11-26 晚）」）。前次：2026-11-26 14:55（前端精修併入 main 並重載）。更早的更新紀錄見 git log 與 `docs/archive/`。

## 線上現況（2026-11-25 19:00 查證）

資料來源：`launchctl`、`newsroom.log`、git、`rt-data-1123` 複本；沒有讀 production DB 與 `.env`。「開關」一列取自本檔紀錄。11/13 的舊現況見 git 歷史。

- **服務**：newsroom（11/24 17:01 重載後一直在跑，scheduler Python process 1 個）、rsshub 兩個 LaunchAgent。
- **出刊**：11/25 06:00–06:08 準備（P 影子＋M 組），12 篇、`degraded=[]`；08:35 發行（Telegram 557、558，`daily_editions` id 30）。11/24 同樣正常（555、556）。11/25 有一次 Codex 呼叫 150 秒逾時，重試成功。
- **開關**：`DAILY_MODE=mas`、P 影子開、人工核可關（`DAILY_REQUIRE_APPROVAL=false`，第一期是 11/15）、`MAS_NOISE_CHECK=true`（第一期 11/24；11/24、11/25 有沒有 HOLD 要看 DB，沒有查）。desk-v3 各開關、`MAS_FULL_EVIDENCE`、`FACT_CHECKER_PER_SOURCE` 都關。
- **版本**：Codex CLI 0.166.0，11/25 06:00 `codex version guard ok`；tag `final-1120` 已 push。
- **資料庫**：production 約 718 MB；Alembic 最新 `c5e1a9d3f207`（desk-v3 `item_fulltext`，11/14 部署；11/23 複本確認）。
- **git**：查證當下 main `a934e8b`，領先 origin/main（`73fddf5`）8 個 commit，**還沒 push**（👤）。
- ⚠️ **11/24 起，06:00 準備期間的收集會撞鎖**：重載讓 15 分鐘的 tick 改從重載時刻起算，從 06:09:47 變成 06:03:10（11/23 21:48 重載）、06:01:44（11/24 17:01 重載）。M 組從開始寫稿到出刊稿落地是同一個 write transaction（`daily/run.py` 的 `session_scope` 包住 `_finish_mas`，11/25 約 06:01:47–06:08:41），收集逐一來源等 30 秒後 `database is locked`：11/24 5 個來源、11/25 6 個來源寫入失敗（連同補寫健康紀錄共 13／16 次 `OperationalError`）。**不影響出刊**；失敗的來源沒有留下健康紀錄，依程式下一輪就到期重抓（06:16 那輪 29 個來源），但該時段的收集晚約 15 分鐘，健康報表看起來像沒抓。11/11 發生過同樣的事，當時只把等鎖 5→30 秒。
  - 不用改程式的做法：**下次重載選在每刻鐘的第 10–13 分（例如 19:10、19:25）**，tick 就會落在 06:10 之後（README「每日營運」已寫）。程式修法（準備期間收集讓開，或 M 組分段 commit）會動線上流程，沒有排進佇列。
  - **11/26 06:00 又撞，這次連聚合都失敗**：06:01:44 那輪 3 個來源（npr-news、nytimes-home、dw-en）寫入失敗，聚合在 06:05:33 `database is locked`、整個收集 job 拋例外（上一次是 11/11）；06:16 那輪正常。出刊沒受影響（06:08 備妥 12 篇、`degraded=[]`、id 31；有一次 Codex 150 秒逾時、重試成功）。同日 07:10:18 重載，tick 移到每刻鐘的 10:18，11/27 起應避開（要看 log 確認）。
- ⚠️ **Guardian 五個來源（world／tech／environment／culture／sport）11/24 01:03 起每次都 403**（11/24 93 次、11/25 到 18:46 76 次；11/20–11/23 是 0 次）。看起來是對方擋，還沒查是擋 UA 還是 IP；少了五個英文 T2 來源，會影響國際／科技版候選。登錄表沒動。
  - **2026-11-26 查出根因**：Guardian 擋開頭是 `Mozilla/5.0` 的 UA（同一個 IP，不帶 Mozilla 的 UA 五個 feed 都回 200）。`fix/ops-1126` 給五個來源設 `user_agent`，部署後生效。全文抓取（desk-v3，開關關著）仍用舊 UA，Guardian 文章頁同樣會 403。

## 時程與下一步（2026-11-23 起，以此為準；Claude 自主安排，志晨 11/23 授權）

**關鍵日期（志晨 2026-11-23 告知）**：👤 **專題發表申請單 12/16 截止**（要志晨本人繳交）；**專題發表 2027-01-08**。手冊原訂報告、簡報、模擬口試在 12/16–12/31，照走。

依序做（每項約一次自動開發 session；做完打 ✅ 並寫日期）：

1. ✅ 實驗三盲計與結果、試刊成本列、AIHOT 對照（2026-11-23）。
2. ✅（2026-11-23，已併入 main）**回放頁 R1：稿件協商串**。`daily/replay.py::build_replay` 加 `threads`：每篇稿依時間列出 PITCH → 記者撰稿 → CHALLENGE（查核員理由）→ REQUEST_REVISION → REVISION_DONE（v1→v2 diff）→ RELEASE／HOLD，含發送者→接收者、對應的 `llm_records` 耗時；`office.html` 的「稿件」分頁點開一篇就顯示整串，點任一步跳到那一步。介面寫進 `docs/v5/DAILY_EDITION.md`「回放時間線與 3D 編輯室」。
3. ✅（2026-11-23，已併入 main）**回放頁 R2：角色泳道時序圖**。新分頁「互動」：每個角色一條泳道、訊息畫成箭頭（顏色依訊息種類）、模型呼叫畫成區塊，點擊跳到該步；純 SVG，不加套件。
4. ✅（2026-11-23，已併入 main）**回放頁 R3：播放控制**。速度 1×／2×／4×、「只看互動」（略過收集與單純的模型思考）、「下一個 CHALLENGE」快捷鍵；發表 demo 用。
5. ✅（2026-11-23，已併入 main）**回放頁 R4：本期互動摘要卡**。誰對誰發幾則（角色×角色矩陣）、CHALLENGE 幾次／改稿成功幾次／HOLD 幾次、各角色呼叫次數與耗時；同一份數字可直接截圖進報告。
**2026-11-23 晚追加：外部稽核清單（`~/Desktop/reddit_tracker_improvement_plan.html`，12 項 P0–P3）已併進下面的佇列，志晨要求全部做完。** 定時任務 `reddit-tracker-daily-autodev` 一天跑三次（06:52／12:52／18:52），每次從上往下挑第一個沒打 ✅ 的；需要 DB 的一律用唯讀複本 `~/Documents/Developer/Lab/rt-data-1123/reddit_tracker.db`（11/23 21:45 `.backup`，CLI 用 `DATABASE_URL=sqlite:////Users/leroy/Documents/Developer/Lab/rt-data-1123/reddit_tracker.db`），要跑 Codex 的實驗一律在 `~/Documents/Developer/Lab/rt-data-1123/` 底下另建複本，不碰 production DB 與 `data/work/`。

6. ✅（2026-11-24，`claude-auto`）**P0-1 實驗三補「重複主稿數」＋M 組擋錯 trace**（12/05 前；⚠️ 查證結果和下面原本的前提不同，見「本次變更（2026-11-24）」）：`scripts/trial_metrics.py` 每期 P／M 刊出稿裡同一事件（同 cluster 或標題高相似）占兩篇的數目，成本表加一欄；挑 11/12 P #3（story 54413）或 11/15 P #8（story 69836）這類「P 混入無關來源、M 查核員擋下」的案例，用 `python -m reddit_tracker.daily trace --date … --variant mas`（指向複本）印出 M 組 CHALLENGE → v2 修稿，補進 `docs/eval/exp3_results.md`，「待補」清零。
7. ✅（2026-11-24，`claude-auto`；👤 剩本人填欄位與繳交）**P0-3a 發表申請單草稿** `docs/presentation/application.md`（12/10 前；題目、中文摘要、系統特色、成員分工、設備需求），👤 志晨照抄繳交（12/16 截止）。同時清掉 `docs/eval/exp*_results.md` 裡的內部交接字眼（`grep -n "Claude\|志晨" docs/eval/exp*_results.md`），改成正式分析語氣；exp1 明寫「跨模型 κ=0.44 是 grok vs agy，不是人類標註」。
8. ✅（2026-11-24，`claude-auto`）**P0-2 實驗二課後補充消融 (c+)**（12/08 前；⚠️ (c) 組的證據包也來自 `build_evidence_from_ids`，同一份證據三組共用，組間比較不受影響，報告照寫即可）：在複本以 `FACT_CHECKER_PER_SOURCE=true` 只重跑 (c) 有 CHALLENGE 的案例（H-T767、E02，必要時 H-T807），比較連帶誤刪 3 則 → ?；正式 (a)(b)(c) 檔案與結論不動，結果寫成 `docs/eval/exp2_results.md`「課後補充消融（Post-Freeze Ablation）」一節。要呼叫 Codex，先確認 `scripts/run_exp2.py` 能指定輸出目錄到 Lab 複本。
9. ✅（2026-11-25，`claude-auto`，整份初稿；剩截圖與老師確認事項，見「本次變更（2026-11-25）」）**P0-3b 報告 v2.0** `docs/report.md` 整份改寫（12/20 前初稿；可分兩次）：一 緒論；二 系統架構（RSS/RSSHub 來源 → TF-IDF＋實體兩段聚合 → 評分選題 → P 流水線 vs M 六角色編輯室）；三 MAS 角色協議與程式護欄（`protocol.py` 權限、T1/T2/T3、`request_hash` 錄音重播、回歸集 E01–E16）；四 資料庫（只寫現行核心表）；五 實驗一／二／三與七日試刊（整合三份 results）；六 限制與混淆因素（grok/agy 代標、P 組一次寫整版被截斷的混淆、11/14 起關閉人工核可、11/13 只有一期是發行前真人核准）與 AI 工具使用聲明。口試七題的防禦寫進第六章。
10. ✅（2026-11-25，`claude-auto`，初稿；👤 剩排練、錄備援影片、填封面個資）**P0-4 簡報＋Demo 腳本**（12/31 前；⚠️ 11/19 那兩次異議是誤報，腳本已改，見「本次變更（2026-11-25 午）」）：`docs/demo_slides.md`（問題 → 六角色編輯室與程式護欄 → 回放 R1–R4 → 三實驗誠實評估）、`docs/demo_script.md`（3–5 分鐘 live demo＋備援錄影逐字稿：`python -m reddit_tracker.web`，開 `/daily/2026-11-19/newsroom/office?only=1&speed=2`，R4 摘要卡 → R2 泳道 → 按 `C` 跳 CHALLENGE → R1 協商串 v1→v2 diff）。
11. ✅（2026-11-25，`claude-auto`）**P1-3b README／PROGRESS 對齊**：README 的測試數、Alembic revision、設定鍵表（補 `MAS_NOISE_CHECK` 與 desk-v3 四個開關）；本檔「線上現況」更新到最新日期。
12. ✅（2026-11-26，`claude-auto`；(1) 早、(2) 午、(3) 晚 `FACT_CHECKER_EVENT_CLASSES`，見三段「本次變更（2026-11-26 …）」）**P2-1 三個演算法盲區**（放新開關，預設關閉，不動 `exp1-frozen` 與實驗二重播）：(1) 早報／晚報／懶人包等彙整稿 `is_roundup_title` 不併入單一事件 cluster；(2) 查核員 `irrelevant_sources` 接當天 EntityContext，承認 ≥3 字、DF<5% 的中文共同片段（N-44224 蘇巧慧、N-54434 統一不再誤點名）；(3) 查核員提示詞加事件四分類（同次事件／後續進展／無關／彙整稿）——(3) 會改 `request_hash`，只在開關打開時生效。離線測試：T457/T523 不再錯併。
13. **P2-2 desk-v3 高互動 demo 期**（選做）：在 `rt-data-1123` 另一份複本開 `MAS_RICH_CONTEXT`／`MAS_OPEN_LAYOUT`／`MAS_MORE_INTERACTION` 跑一期 M 組 prepare（詳見 `docs/pr/desk-v3.md`），`build_replay` 輸出存成 `tests/fixtures/replay/` 下的 fixture，供簡報對比。
14. **P3-1 `run_mas` 只為候選池建 `Story` 列**（每期 ~4,800 → ≤30）：先確認分版主編（含 `MAS_OPEN_LAYOUT`）只需要 desk pool＋全站 top 10；改完全套測試＋回放 fixture 都要過；會動線上流程，併入後要 `newsroom-reload` 並看隔天 06:00 準備。
15. **P3-3 拆 `daily/mas/orchestrator.py`**（prompts.py／checks.py／desk_v3.py／orchestrator.py ≤600 行，對外名稱相容、測試不改）；`run.py` 視剩餘時間再拆。純重構，不能改任何 `request_hash`（錄音重播測試會抓）。
16. 👤 **P3-2 DB 瘦身（需志晨同意才做，自動開發不做）**：先完整備份 → 342 列 11/12 以前的 `pending` 訊息改 `handled` → Alembic drop v4/v5 殭屍表＋刪 ORM → `VACUUM`。動正式 DB、不可逆，排在 2027-01-08 發表後。
17. ✅ **P1-1**（2026-11-23 21:47–21:48，志晨同意）：`main`（`b1639bc`）與 `final-1120` 已 push 到 origin（其他本地 tag 沒 push）；production `.env` 加了 `MAS_NOISE_CHECK=true`（原檔備份在 `~/Documents/Developer/Lab/rt-data-1123/env.bak-1123`），`newsroom-reload` 後 log 有 `codex version guard ok`、三個 job 註冊、只有一個 scheduler Python process。11/24 06:00 起 M 組稿件出刊前會掃模型雜訊，命中轉 HOLD 標「暫扣」。

- ❎ **P1-2 停用 mirrormedia-political／nikkei-asia：不做**。11/23 查證兩個來源都還在收（複本 `source_items`：鏡週刊 11/23 收 29 則、Nikkei 10 則，11/16–11/23 每天都有）；`newsroom.log` 只有 11/16–17 零星 16 次 503／連線被拒，不是每 15 分鐘失敗。`scripts/probe_news_sources.py` 對 RSSHub 回 403 是因為它沒帶 access key，不代表來源失效。
- ✅ **P1-3a**（2026-11-23）：已移除併入 main 的 worktree `rt-wt-cleanup`／`rt-wt-desk`／`rt-wt-noapproval` 與分支 `docs/exp1-results`／`feat/desk-v3`／`feat/no-approval`；`git worktree list` 只剩 main 與 `rt-wt-auto`。

- 開發回放頁用 `tests/fixtures/replay/2026-11-19_mas.json`（11/19 M 組真實 `build_replay` 輸出，2026-11-23 從 production DB 唯讀匯出；有 recorded 時間、3 次 CHALLENGE、改稿請求、版面異議），不必碰 DB。
- 回放頁只讀、不能改稿；不改 `request_hash`、提示詞、線上撰稿流程，所以不影響實驗數字。動到 `reddit_tracker/daily/replay.py`／`office.html` 會被 web 載入，但 newsroom 排程不載入 web，**不需要重載 newsroom**（web 是手動起的 FastAPI）。
- 視覺檢查：自動開發 session 沒有瀏覽器可用（production checkout 不能放 `launch.json`），改用 fixture 寫測試；畫面由互動 session 截圖確認。

## 本次變更（2026-11-26 晚 — 查核員事件四分類，佇列第 12 項 (3)，`claude-auto`，自動開發）

新開關 `FACT_CHECKER_EVENT_CLASSES`（預設關閉，`.env` 沒動）；沒碰 production DB。驗證在 `~/Documents/Developer/Lab/rt-data-1123/exp2-c4/`（從 `exp2-cplus` 複製 `cases.json`、`v1.json`、`results_c.json`、`ledger.db`），新的 Codex 呼叫 16 次，額度檔在該目錄。介面見 `docs/v5/DAILY_EDITION.md`「事件四分類」。

- ✅ `daily/mas/orchestrator.py`：`CHECKER_EVENT_CLASS_SUFFIX`／`CHECKER_EVENT_CLASS_SCHEMA`（`sources[].relation` ∈ `SAME_EVENT|FOLLOW_UP|UNRELATED|ROUNDUP`），`checker_source_verdicts` 依 `EVENT_RELATION_KEEP` 對應留／刪；`review_one(event_classes=None)` 讀設定，傳到 `_check_and_maybe_revise` 與 desk-v3 總編退稿重驗；優先於 `FACT_CHECKER_PER_SOURCE`。關閉時請求逐字不變（錄音重播、回歸集都過）。
- ✅ 實驗二工具：`run_ablation(event_classes=True)`＝(c4)、`scripts/run_exp2.py ablation|ablation-report --event-classes`（`results_c4.json`，不覆蓋 (c+)）。
- 📌 (c4) 結果寫進 `docs/eval/exp2_results.md`「課後補充消融：(c4) 事件四分類」：同 8 篇擋下 **7/7**（(c) 6/7、(c+) 5/7）、連帶誤刪 **3 → 1**；H-T767、H-T807 都擋下。新的誤刪是 H-T807 S2（另一位評論者評同一場辯論，被判 UNRELATED）。
- ⚠️ **提示詞是看過 (c+) 錯誤後寫的**（UNRELATED 的例子「事後另做的民調、旁人隔空喊話」對應 H-T807／H-T767），兩篇保留集案例已不算保留，不能當泛化成績；報告要提只能說「事後修正、離線驗證」。
- ℹ️ 沒有出現 FOLLOW_UP／ROUNDUP。E01 停在 `challenged` 是記者 v2 多寫「25」（抽樣差異），與分類無關。
- ⚠️ 開之前至少要：把 UNRELATED 說明改成不靠「做事的人」（評論、分析算同次事件），在複本跑一期 M 組看誤刪；和 `FACT_CHECKER_ZH_FRAGMENTS`、`MAS_FULL_EVIDENCE` 的開啟條件一起決定（三者都會改 `request_hash`）。
- 測試：`tests/test_checker_event_classes.py`（11 個）；worktree 全套 627 passed／7 skipped、ruff 通過。
- ✅ 併入 main（`b0909eb`，2026-11-26 19:09 fast-forward）並 `newsroom-reload`（19:10:20）：production 全套 630 passed／4 skipped；log 有 `codex version guard ok`、五個 job 註冊、scheduler Python process 1 個（另兩個是 uv 與 caffeinate 包裝層）；重載後第一輪收集正常。`FACT_CHECKER_EVENT_CLASSES` 沒開，線上行為不變。
- ➡️ 下一步：第 13 項 P2-2 desk-v3 高互動 demo 期（選做；要在複本跑 M 組 prepare）。

## 本次變更（2026-11-26 下午 — 前端精修交給 grok，Claude 驗收）

grok CLI（`dontAsk`＋白名單）在 worktree `rt-wt-front` 分支 `feat/frontend-polish`（`fd821ff`）改了四個檔，只動樣式與版面，沒碰 `replay.py` 資料、提示詞、`request_hash`、`telegram_digest`。

- `office.html`：開頁就看得到六個座位與名牌，訊息種類有圖例與各自的紙張／泡泡顏色，右側面板放大；`only=1`、`speed`、`C` 鍵照舊。
- `render.py`：報紙式襯線標題（系統字型堆疊，沒有外部資源）、「為什麼重要」框、淺色／深色、期別列表新的在前；日報文字內容和舊版逐字相同。
- `newsroom_page.py`：CSS 變數主題、訊息列依種類上色；狀態標籤 `HOLD` 改顯示「暫扣」（按鈕 value 與「核准／HOLD」按鈕字沒變，`docs/demo_script.md` 不用改）。
- `web.py`：`_newsroom_bar` 改樣式；**修 `/daily/index.html` 回 422**（原本被 `{edition_date}.html` 吃掉）。
- ✅ 併入 main（merge commit，2026-11-26 14:55）並 `newsroom-reload`（14:55:16；`render.py` 由排程器 in-process 載入，所以要重載）：production 全套 619 passed／4 skipped、ruff 通過；log 有 `codex version guard ok`、五個 job、scheduler Python process 1 個。收集 tick 仍在每刻鐘第 10 分（06:10），避開 06:00 準備。
- ⚠️ 已知：手機版右下回放入口會蓋到一點內文；3D 頁持續動畫讓 Chrome 無頭截圖卡住（只影響截圖，不影響瀏覽）。11/27 那期是第一份新版面，Telegram 附件也一樣。

## 本次變更（2026-11-26 午 — 查核員點名承認中文片段，佇列第 12 項 (2)，`claude-auto`，自動開發）

新開關 `FACT_CHECKER_ZH_FRAGMENTS`（預設關閉，`.env` 沒動）；沒呼叫模型、沒碰 production DB，離線比較用 `rt-data-1123` 複本（`immutable=1`）。介面見 `docs/v5/DAILY_EDITION.md`「查核員刪來源」的「中文片段」。

- ✅ `irrelevant_sources(evidence, day_context=None)`：給了當天的 `EntityContext`，S1 與來源共有當天少見的中文片段、合成後 **≥ 2 段互不相連**（`CHECKER_MIN_ZH_FRAGMENTS`）就不點名。`run_mas` 打開開關時建 `title_context`（`MAS_FULL_EVIDENCE` 開著就共用同一份），傳到 `review_one`、修稿重驗、desk-v3 總編退稿重驗。`collection/entities.py` 抽出 `rare_shared_fragments`，聚合的 `shared()` 改呼叫它，行為不變。
- ⚠️ **和佇列寫法不同：只看篇數 < 5% 分不開 5330。** 11/01 高雄辯論與台北辯論共有「市長選」41 篇、「長選戰」26 篇（當天 12,805 篇），比 N-44224 的「李四川」56、「蘇巧慧」64 篇還少見（選舉期間候選人名很常見），任何篇數門檻都會一起放掉。所以加了「至少兩段」：「市長選戰」是一段，「李四川」「蘇巧慧」是兩段。
- 📌 離線比較（`scripts/eval_checker_fragments.py`，10/31–11/01 的 10 篇＋實驗二 25 案）：N-44224、N-54434、N-44245、N-48575 和 10/31–11/01 的 14、5327、5331 等不再點名，有標註案例裡少點名的同一事件來源 **10 個**；5330 高雄辯論、5455、E01–E05 的無關來源照樣點名。**真無關但不再點名 1 個：H-T807 S3**（同樣是沈伯洋、蔣萬安，不同事件），名字分不出來，要靠 (3) 事件四分類。N-48569（只有「提彈劾案」一段）、N-69866（只有「董事會」）仍點名，照舊交給查核員 LLM。
- ⚠️ 打開的代價：不再點名的稿就不問查核員 LLM（H-T807 這種會直接過），也會改 `request_hash`。建議 (3) 做完、在複本跑一期 M 組比對後再決定開不開；實驗二與凍結的數字不受影響（`eval/exp2.py` 不傳 context）。
- 測試：`tests/test_checker_zh_fragments.py`（9 個：關閉不變、兩段放行、一段不放行、常見片段不算、只會少點名、`review_one` 不再叫查核員、5330 照樣 CHALLENGE、`run_mas` 只在開關打開時傳 context）；worktree 全套 614 passed／7 skipped、ruff 通過。
- ✅ 併入 main（`87efc1f`，2026-11-26 13:07 fast-forward）並 `newsroom-reload`（13:07:59）：production 全套 617 passed／4 skipped；log 有 `codex version guard ok`、五個 job 註冊（三個核心＋`db_backup`＋`daily_startup_catchup`）、scheduler Python process 1 個；重載後第一輪收集正常。`FACT_CHECKER_ZH_FRAGMENTS` 沒開，線上行為不變。
- ➡️ 下一步：第 12 項 (3) 查核員提示詞加事件四分類（同次事件／後續進展／無關／彙整稿；開關後面，會改 `request_hash`），用 H-T807、H-T767 驗證。

## 本次變更（2026-11-26 上午 — 四位 agent 檢查後的修正，互動 session，分支 `fix/ops-1126`）

志晨要求把四位 agent（claude／gpt／gemini／grok）檢查提出的改進做完。worktree `~/Documents/Developer/Lab/rt-wt-ops`（`fix/ops-1126`，含 grok 的 `fix/guards-1126` 合併）；605 passed、7 skipped，ruff 乾淨。

- ✅ **已部署**（志晨 11/26 同意）：10:25 fast-forward 併入 main（`9373a41`），production 全套 608 passed／4 skipped；`newsroom-deploy` 10:25:14（DB 備份 `reddit_tracker.backup-20261126-102514.db`）→ log 有 `codex version guard ok`、三個 job 註冊、scheduler Python process 1 個；重載後第一輪 `sources=42 ok=42`，Guardian 不再 403。已 push origin/main。10:30 志晨同意後 `.env` 加 `DB_BACKUP_DIR=/Users/leroy/Documents/Developer/Lab/rt-backup`、`DAILY_STARTUP_CATCHUP_MINUTES=180`、`DAILY_WITHHOLD_CHALLENGED=true`（原檔 `rt-backup/env.bak-1126`），`newsroom-reload` 10:30:47：五個 job（多 `db_backup` 09:30、一次性 `daily_startup_catchup`，當天已發行所以沒動作）。`NUMBER_CHECK_V2` 仍關（待複本重跑一期）。`rt-wt-ops`／`rt-wt-guards` worktree 與兩個本地分支已刪。11/27 06:00 要看 log 有沒有 `source collection deferred`、不再 `database is locked`。

- **06:00 撞鎖改程式修**（`newsroom/scheduler.py`）：準備期間到期的收集延後、準備結束（成功或失敗）立刻補一輪；準備開始前先等進行中的那輪寫完（最多 300 秒）；收集不會兩輪重疊。重載時間不用再挑。手動 CLI `daily prepare` 不在保護範圍。
- **冷啟動補做** `DAILY_STARTUP_CATCHUP_MINUTES`（預設 0＝關）：啟動時在準備～發行時刻之間且當天沒有版次就補準備；發行時刻後 N 分鐘內仍是 `drafted` 就補發；`publishing`／`delivery_failed` 只記 ERROR。
- **每日備份** `DB_BACKUP_DIR`（預設空＝關）、`DB_BACKUP_KEEP=3`、09:30：SQLite online backup＋`quick_check`；手動 `uv run python -m reddit_tracker.backup --dir …`。已手動備份一次：`~/Documents/Developer/Lab/rt-backup/reddit_tracker-2026-11-26.db`（728 MB，含 11/26 那期）。⚠️ Time Machine 目的地掛載失敗（`tmutil latestbackup`），異地備份要志晨處理。
- **來源**：Guardian 五個來源加 `user_agent`（見「線上現況」）；`hn-api-top`（`method: json`，collector 沒實作）改成停用並註明，測試鎖住「啟用來源都抓得到」（數據版證交所 JSON 由 `daily/market.py` 讀，排除）。
- **核可路由只收 POST**（`web.py`）：表單自己解析 urlencoded，不需要 `python-multipart`；回放頁表單改 `method="post"`。
- **three.js 本機化**：`reddit_tracker/daily/vendor/three.module.js`（0.160.0，sha256 與 jsDelivr 套件清單一致，MIT 授權檔一起放），發表教室斷網也能開 3D 編輯室。
- **grok（`fix/guards-1126`）**：`DAILY_WITHHOLD_CHALLENGED`（預設關；關核可時 `challenged` 只出標題、標「暫扣」）、`NUMBER_CHECK_V2`（預設關；數字核對排除日期時間片段、認 m／mn／k／trillion／千）、Telegram 摘要／HTML 各自入庫訊息 ID，HTML 明確失敗只補 HTML，逾時標 `stats.delivery.needs_review` 不重送（沒改 schema）。
- **文件**：`PROGRESS.md` 10/30–11/23 的「本次變更」搬到 `docs/archive/PROGRESS_2026-10-30_to_11-23.md`（94→34 KB）；CLAUDE.md／AGENTS.md 的 codex 凍結字樣改成「2027-01-08 發表前」；README 設定鍵表、`.env.example`、`docs/v5/DAILY_EDITION.md` 已補。
- **刻意沒做**（四位一致）：拆 `orchestrator.py`、Story 只建候選池、VACUUM、開 desk-v3 或 `CLUSTER_ISOLATE_ROUNDUPS`、`newsroom.log` 輪替（launchd 導 stdout，4 MB 不急）。佇列第 12 項 (2)(3) 留給自動開發照排。
- ➡️ 部署建議：fast-forward 併入 main → `.env` 加 `DB_BACKUP_DIR=/Users/leroy/Documents/Developer/Lab/rt-backup`、`DAILY_STARTUP_CATCHUP_MINUTES=180`、`DAILY_WITHHOLD_CHALLENGED=true` → `deploy/install_launchd.sh newsroom-deploy`。`NUMBER_CHECK_V2` 會改哪些稿被點名，建議先在複本重跑一期再開。

## 三項決定（2026-11-24 傍晚 — 志晨 16:5x 回「你來決定」，互動 session）

1. **M 組證據包：修，但不開**。新增 `MAS_FULL_EVIDENCE`（預設關閉，`.env` 沒動）：帶當天 context、白名單改認各來源實際文章網域。複本重建 84／84 篇和 P 一致（255 → 416 個來源）；介面與限制見 `docs/v5/DAILY_EDITION.md`「證據包對齊」。
   - 不開的理由：試刊與實驗三是關閉狀態跑的，開了會讓線上行為和已寫好的實驗數字不同；而且查核員的中文點名（佇列第 12 項 (2)）還沒修，多給來源會多誤刪。
   - ➡️ **開啟條件**：第 12 項 (2) 做完、用複本跑一期 M 組比對過，再問志晨改 `.env`（自動開發不改 `.env`）。
2. **push：做**。push 前掃過 `origin/main..main` 的新增行，沒有金鑰、token、電話、學號。
3. **P3-2 DB 瘦身：2027-01-08 發表前不做**（不可逆、動正式 DB，發表前沒有好處）；發表後仍要志晨當下同意才做。佇列第 16 項維持 👤。
- 測試：`tests/test_full_evidence.py` 5 個；worktree 全套 535 passed／7 skipped、ruff 通過；關閉時請求不變（錄音重播與回歸集都過）。

- ✅ 併入 main 並重載 newsroom（2026-11-24 17:01）：production 全套 538 passed／4 skipped；log 有 `codex version guard ok`、三個 job 註冊、scheduler Python process 1 個。`MAS_FULL_EVIDENCE` 沒開，線上行為不變。main 隨後 push 到 origin。

## 本次變更（2026-11-26 早 — 彙整稿不併入事件，佇列第 12 項 (1)，`claude-auto`，自動開發）

新開關 `CLUSTER_ISOLATE_ROUNDUPS`（預設關閉，`.env` 沒動）；沒呼叫模型、沒碰 production DB，離線驗證用 `rt-data-1123` 複本（`immutable=1`）。規則與完整數字見 `docs/v5/CLUSTERING.md`「彙整稿不併入事件」。

- ✅ `collection/entities.py::is_roundup_title`＋`MergeRules.isolate_roundups`：聚合時彙整稿自成事件、也不當橋；`desk_merges` 不拿彙整稿的標題與別名當合併依據（T523 是中英配對，只改聚合擋不住 LLM 第二意見那條路）。
- ✅ 用實驗一的 `simulate` 重跑 40,618 篇：關閉時 100／100 組和凍結的 `c_merged` 相同；打開時只有 T457、T523 由「合併」變「沒合併」（標註都是「不是」）。併在別的事件裡的彙整稿 24 → 0；其他素材只有一個 NFL 事件被拆成兩個。
- ⚠️ **和佇列寫法不同：「懶人包」不算彙整稿。** 看複本裡的素材，懶人包、一次看幾乎都是單一事件的整理（產假延長、核電公投），併進該事件是對的；算進去會多拆對的合併。
- ⚠️ 規則是看過 test 錯誤以後寫的，**不能**拿來改 `exp1_results.md` 或當方法 C 的成績；簡報若要提，只能說「事後修正、離線驗證」。
- ℹ️ 中央社「早安世界》」「晚間影音新聞／」佔了 24 篇的一半：標題是頭條、看起來合併沒錯，但「早安世界》」內文列當天多則新聞，會把別的事件的數字帶進證據包，所以算彙整稿。打開後這些事件會少一篇中央社（`t1_count`、`item_count` 變小，`outlet_count` 只有在中央社沒有別的稿時才變）。
- ℹ️ 彙整稿自成事件後仍可能被選成一篇稿（只有一家出處、分數低），這次沒有擋選題。
- 測試：`tests/test_roundups.py`（35 個；fixture `roundup_1030.json`）；worktree 全套 576 passed／7 skipped、ruff 通過。
- ✅ 併入 main（`ecc956d`，2026-11-26 07:10 fast-forward）並 `newsroom-reload`（07:10:18）：production 全套 579 passed／4 skipped；log 有 `codex version guard ok`、三個 job 註冊、scheduler Python process 1 個；重載後第一輪 `isolated_roundups=0`（開關關著）。重載刻意選在第 10 分：收集 tick 從 06:01:44 移到每刻鐘的 10:18（06:10:18），在以往 06:00–06:08 的準備之後，11/27 06:00 要看 log 確認不再撞鎖。
- ➡️ 下一步：第 12 項 (2) 查核員 `irrelevant_sources` 接當天 EntityContext（N-44224、N-54434 不再誤點名；注意既有註解「『市長選戰』這種片段高雄、台北辯論都有」，要確認 5330 的高雄辯論仍被點名），再做 (3)。

## 本次變更（2026-11-25 晚 — README／PROGRESS 對齊，`claude-auto`，自動開發）

沒有改線上程式；沒呼叫模型、沒碰 production DB、沒讀 `.env`。

- ✅ README：測試數（11/25）、Alembic 最新 revision、設定鍵表補 16 個鍵（`MAS_NOISE_CHECK`、`MAS_FULL_EVIDENCE`、desk-v3 四個開關與護欄、`FULLTEXT_*`）、實驗工具補 6 支腳本與 exp2 的 `ablation`、文件索引補實驗結果／申請單／`docs/pr`、狀態與路線圖改成現況。
- ✅ README 更正不實敘述：「兩組差別只在撰稿與審稿方式」補上證據包參數不同；關閉核可時 `challenged` 稿會照發全文；`brew upgrade codex` 的說明不再寫「11/20 凍結前」。
- ✅ `.env.example` 同步補鍵（只有註解行，沒有改任何預設值）。`tests/test_config.py` 加檢查：`Settings` 的每個鍵都要出現在 README 與 `.env.example`，以後加開關漏寫會失敗。
- ✅ 本檔「線上現況」改成 11/25；查證時發現兩個線上問題（收集撞鎖、Guardian 403），寫在該節，**沒有動手修**。
- ℹ️ `CLAUDE.md`／`AGENTS.md` 的「Do not `brew upgrade codex` before the 11/20 freeze」字面已過期，規則檔由志晨決定要不要改。
- 測試：worktree 全套 541 passed／7 skipped；ruff 通過。
- ✅ 併入 main（`7b66760`，2026-11-25 19:05 fast-forward）：production 全套 544 passed／4 skipped；只動文件、`.env.example`、測試，沒有重載；scheduler Python process 1 個。
- ➡️ 下一步：第 12 項 P2-1 三個演算法盲區（新開關、預設關閉；可分次做）。

## 本次變更（2026-11-25 午 — 發表簡報與 Demo 腳本，`claude-auto`，自動開發）

資料庫另開複本（`rt-data-1123/demo-check.db`，用完已刪）起本機網頁，在瀏覽器走過腳本第 1、3、4 步（第 2 步看過畫面、第 5 步只比對影子版 HTML 內容）；沒呼叫模型、沒碰 production DB、沒讀 `.env`。

- ✅ `docs/demo_slides.md`：Marp 20 頁（正文 15＋問答附錄 5），依手冊 11.6 的 12 分鐘配置；轉成圖檢查過，沒有溢出（之後只改第 13 頁一句，沒有重轉）。數字取自 `docs/report.md`。產生 PDF：`marp --no-stdin docs/demo_slides.md --html --pdf -o slides.pdf`（少 `--no-stdin` 在非終端機會卡住；少 `--html` 方塊畫不出來）。
- ✅ `docs/demo_script.md`：事前準備（開資料庫與 `site/daily` **兩份複本**，因為表格版回放頁的「核准／HOLD」會寫資料庫並重畫網頁）、現場 5 分鐘六步、應變表、備援影片 5–8 分鐘逐字稿、口徑提醒。時間是估計，沒有排練過。
- ✅ v4 舊簡報與舊講稿移到 `docs/archive/demo_slides_v4.md`、`demo_script_v4.md`（只改連結與加註），README 索引同步。
- ✅ `office.html`：點過分頁按鈕後焦點留在按鈕上，`C`／`I`／方向鍵都沒反應（實際點出來的，Demo 會當場失靈）；改成只有空白鍵留給按鈕。只有 web 載入這個檔。
- ⚠️ **佇列原訂拿 11/19 當「跳 CHALLENGE → 改稿」示範，但那兩次異議都是誤報**：86093 的「11, 4000」是 `November 19` 與 `40m`（4,000 萬），86123 的「1500」是 `15mn`（1,500 萬）。腳本照實講成誤報；`docs/report.md` 3.5 補一句。86123 的查核員模型另外質疑 CNBC 那則，v2 正文拿掉了，但 CNBC 標題有提到德意志銀行，拿得對不對有爭議，來源清單也沒跟著改。
- ✅ **改用 11/01 科技版當「擋對」示範**：5455 v1 把 CNBC 的 Microsoft 財報預告寫進 Amazon 財報，查核員點名 S2，v2 刪除；P 影子稿 5326 用同一則 CNBC 把兩家公司寫成一篇。這是事後挑的單一案例、在試刊 7 期之外，**不改變**實驗三「7 期找不到 M 擋下、P 刊出的無關來源」的結論。同期 5330 刪對了高雄辯論（S3），但連同一場辯論的央廣（S2）也刪了，腳本沒有用它。案例判讀由 AI 工具做，沒有第二人複核。
- ℹ️ 數字檢查誤報可能比報告寫的多：54431（1,250 萬）、64572（3,000 萬）看起來也是單位換算，沒有對原始素材，所以沒有寫進報告。修法（排除日期片段、換算 m／mn／bn／萬／億）會改線上行為，要排進佇列、放開關。
- ℹ️ 11/01 的摘要卡不要拿來展示：最後一篇 11/06 才核可，`span_secs` 算成約 130 小時。
- 👤 剩：真人排練計時、錄備援影片、封面填姓名學號與指導老師、決定要不要把 three.js 0.160.0 放到本機（沒網路時 3D 出不來，右側分頁照常）。
- 測試：worktree 全套 539 passed／7 skipped；ruff 通過。
- ✅ 併入 main（`ea757fd`，2026-11-25 13:10 fast-forward）：production 全套 542 passed／4 skipped；沒有重載（`office.html` 只有手動起的 web 會載入，import 排程模組確認過）；scheduler Python process 1 個。
- ➡️ 下一步：第 11 項 P1-3b README／PROGRESS 對齊。

## 本次變更（2026-11-25 — 報告 v2.0 初稿，`claude-auto`，自動開發）

只改文件。線上數字從 `rt-data-1123` 複本用 `immutable=1` 唯讀查；沒呼叫模型、沒碰 production DB、沒讀 `.env`。

- ✅ `docs/report.md` 整份改寫（七章＋附錄，約 3.4 萬字元）：緒論、系統架構、MAS 協議與護欄、資料庫、三實驗與試刊、限制／答辯八題（手冊 11.7）／AI 工具聲明、結論。實驗數字沒有改。舊 v4 報告移到 `docs/archive/report_v4.md`（只改連結）；README 文件索引同步。
- ⚠️ **更正：11/14 那期讀者只收到標題短訊。** 關閉人工核可是 11/14 19:42 部署，晚於當天 08:35 發行；`site/daily/2026-11-14.html`（11/14 08:35 產生）印「未核准」。第一期不需核可的是 **11/15**。所以試刊 7 期裡讀者當天拿到全文的只有 11/13、11/15。`exp3_results.md` 的「發行前核准」欄與限制已改（主指標計錯點在核可之前，數字不受影響）；本檔較早段落的「11/14 起」是當時寫的，以本段為準。
- 📌 24 期互動實況（報告 3.5，10/31–11/23）：改版 41／288 篇、CHALLENGE 實質 43 則、REVISION_DONE 44；**REBUT 0、HOLD 0、T1 爭稿 0、T3 超量 0**；總編換主稿 7 期、換入選名單 0 期；每期 2 則 PAGE_OBJECTION 是固定流程，不是真的衝突。簡報、申請單不要把 T1／T3 說成線上自然發生。
- ⚠️ 已知護欄缺口（沒修，報告已寫）：(1) 改稿後重驗仍不過（`STILL_BAD`）或縮稿丟譯名時，稿件停在 `challenged`，不會自動轉 HOLD；人工核可關閉後會**照發全文**（過去 3 篇：16038、32609、48567，都在關閉核可之前；11/15–11/23 沒有發生）。(2) 數字檢查把日期時間片段（「10 月」「1 時 04 分」）當成沒有出處：20 則數字異議有 9 則是這種、1 則是單位換算，白花一次改稿。兩個都會改線上行為（(2) 還會改請求），要做得另外排進佇列、放開關。
- 👤 **需要問老師**（報告 6.1／6.3 已照實寫「沒有確認紀錄」）：實驗二、三由 AI 標註（手冊 8.1／11.5 禁止；只有實驗一有「老師同意」的轉述紀錄）、用本機 Codex CLI 代替正式 API（手冊 6.9／10.1）、試刊與凍結提前的方案 B 時程。有結果後改這幾句即可。
- 剩：報紙與回放頁截圖（手冊要求附圖，自動開發 session 沒有瀏覽器，互動 session 補）、封面個資由作者在印製版填。
- 測試：worktree 全套 539 passed／7 skipped；ruff 通過。不需要重載 newsroom。
- ✅ 併入 main（`11f4e1a`，2026-11-25 07:07 fast-forward）：production 全套 542 passed／4 skipped；只動文件，沒有重載；scheduler Python process 1 個。
- ➡️ 下一步：第 10 項 P0-4 簡報＋Demo 腳本。

## 本次變更（2026-11-24 夜 — 磁碟清理：舊 DB 備份已清，互動 session）

志晨授權；沒改程式、沒碰 production DB、沒重載服務。下面各段裡提到的舊備份路徑是當時寫的，以本段為準。

- ✅ **已移到垃圾桶**（連同 `-wal`／`-shm`，約 2.4 GB；垃圾桶清空後無法還原），都在 `~/Documents/Developer/Lab/`：`reddit_tracker_backups/cleanup-20261113/reddit_tracker.db`、`reddit_tracker_backups/deploy-20261114/reddit_tracker.db`、`rt-data-3d/prod-copy.db`、`rt-data-1106/prod-copy-20261105.db`（和 `data/snapshots/2026-11-05.db` sha256 相同）、`reddit_tracker-fixes-1101-data/prod-copy-20261101.db`。資料夾裡的其他檔案（`.env` 複本、查證輸出）沒動。
- 📌 **不能刪**：`data/snapshots/`（10/27 母本與實驗一快照，不在 git，腳本與測試寫死路徑）、`Lab/rt-data-1123/`（自動開發唯讀複本與 (c+) 結果）、`Lab/reddit_tracker_backups/exp1-annotate-20261106/`（實驗一標註檔）、`Lab/rt-wt-auto/`、`~/rsshub/node_modules`（RSSHub 正在用）。`deploy-20261115` 的 DB 是目前最新的部署備份，留到 2027-01-08 發表後。
- ℹ️ 另外清了 uv／pnpm／Homebrew／npm 快取。`uv cache clean` 要加 `--force`（newsroom 的 `uv run` 持有 cache lock），並避開 06:00 準備與自動開發時段。
- ✅ 清完後（21:28–21:32）：production 全套 542 passed／4 skipped；兩份快照 sha256 OK；`uv sync --dry-run` 在 production 與 worktree 都不需變更；newsroom／RSSHub PID 不變，21:31 那輪收集 5／5 成功。11/25 06:00 的準備當時還沒跑到。

## 本次變更（2026-11-24 晚 — 實驗二課後補充消融 (c+)，`claude-auto`，自動開發）

在 `~/Documents/Developer/Lab/rt-data-1123/exp2-cplus/` 跑（從 production `data/work/exp2/` 只複製 `cases.json`、`v1.json`、`results_c.json` 三個 JSON，沒讀 `*.db`）；新的 Codex 呼叫 16 次，額度檔在該目錄，線上計數沒動。

- ✅ `scripts/run_exp2.py`：新增 `--work-dir` 與 `ablation`／`ablation-report`（原本寫死 `data/work/exp2`）；`reddit_tracker/eval/exp2.py` 加 `select_cases`／`run_ablation`／`source_verdicts`／`render_ablation`。介面見 `docs/eval/EXP2_DESIGN.md`。不改線上流程與 `request_hash`。
- 📌 結果（8 篇：(c) 有 CHALLENGE 的 7 篇＋H-T807）：連帶誤刪 **3 → 0**，但擋下 **6/7 → 5/7**。**和預期相反**：H-T767 的無關來源被查核員判 KEEP，漏擋，而且 v2 正文還引用了它。寫進 `docs/eval/exp2_results.md`「課後補充消融」，正式 (a)(b)(c) 數字與結論沒動。
- 📌 判讀：問題不在開關，在查核員的「同一事件」定義比標註寬（和 H-T807 同一類）。要先做第 12 項 (3) 事件四分類，再評估 `FACT_CHECKER_PER_SOURCE`；線上維持關閉。
- ⚠️ 限制：6 篇 (c) 靠查核員救回的正常稿沒重跑，(c+) 的誤擋率沒有評估到；每個請求只跑一次，H-T767 的翻轉可能是模型抽樣差異。
- ⚠️ 附帶發現（沒修，開關關閉時不會發生）：全部 KEEP 又因百分比另起異議時，逐來源判斷不會寫進 `agent_messages`。日後要開這個開關時先補。
- 測試：`tests/test_exp2.py` 加 4 個；worktree 全套 539 passed／7 skipped、ruff 通過；(c+) 用帳本離線重播結果相同。不需要重載 newsroom（只動 `reddit_tracker/eval/`、`scripts/`、`tests/`、文件）。
- ✅ 併入 main（`e7096ae`，2026-11-24 19:07 fast-forward）：production 全套 542 passed／4 skipped；只動 `reddit_tracker/eval/`、`scripts/`、測試、文件，沒有重載；scheduler Python process 1 個。
- ➡️ 下一步：第 9 項 P0-3b 報告 v2.0（可分次，12/20 前初稿）。

## 本次變更（2026-11-24 午 — 發表申請單草稿，`claude-auto`，自動開發）

只改文件；沒呼叫模型、沒碰 production DB（出刊期數從 `rt-data-1123` 複本唯讀查）。

- ✅ `docs/presentation/application.md`：題目、約 500 字與 144 字兩版摘要、系統特色、主要結果、設備需求、AI 工具聲明、照抄前檢查、數字出處。結果照實寫（實驗一 C 沒有比 A 好、實驗二保留集 1/5、實驗三看不出一致差異）。
- 👤 **志晨要本人填、12/16 前繳交**：姓名、學號、指導老師、聯絡方式、成員分工（repo 是公開的，這些個資沒有寫進檔案）；英文題目是草擬的，題目以學校登記為準；沒有看過學校的正式表單，欄位與字數上限要照表單調整。
- ✅ `docs/eval/exp1~3_results.md` 的交接字眼（「志晨轉述」「請志晨看過改成自己的話」等）改成正式語氣，數字與結論沒動。exp1 在標註一致程度與限制兩處寫明 κ = 0.44 是 grok 對 agy 的跨模型一致程度，不是人類標註。
- ℹ️ 刻意保留兩處「AI 工具（Claude）」：exp2 分析文字的撰寫者、exp3 重複主稿的認定者。這是方法與 AI 使用揭露，不是交接字眼；拿掉會讓讀者以為是人工寫的或人工認定的。
- ℹ️ 順帶發現：README「兩種編採模式」寫兩組「差別只在撰稿與審稿方式」，和 11/24 查出的證據包差異不符，留給第 11 項一起改。
- 測試：worktree 全套 530 passed／7 skipped；ruff 通過。不需要重載 newsroom。
- ✅ 併入 main（`3cda270`，2026-11-24 13:03 fast-forward）：production 全套 533 passed／4 skipped；只動文件，沒有重載；scheduler Python process 1 個。
- ➡️ 下一步：第 8 項 P0-2 實驗二課後消融 (c+)（要呼叫 Codex，只在複本上跑）。

## 本次變更（2026-11-24 早 — 實驗三補重複主稿數與 M 組 trace，`claude-auto`，自動開發）

只讀 `rt-data-1123` 複本；沒呼叫模型、沒碰 production DB、沒改線上流程。

- ✅ `scripts/trial_metrics.py`：加「P／M 重複候選」兩欄與候選清單（`duplicate_candidates`，共用 cluster／素材或標題相似度 ≥0.15，以事件為單位）；`open_ro` 讓沒有 `-wal` 的複本也讀得到。測試 `tests/test_trial_metrics.py`（6 個）。
- ✅ 結果：7 期候選 7 對、認定重複 2 對，**P＝M**（兩組刊同一批 84 個事件，指標分不出兩組）。
- ⚠️ **原前提不成立**：11/12 P #3（54413）、11/15 P #8（69836）的 M 版都沒有 CHALLENGE；前者 M 的證據包本來就沒有那些來源，後者無關來源照刊。7 期裡 IRRELEVANT_SOURCE 只有 2 次（54480、64568），都不是有效擋錯。`exp3_results.md` 的「M 少錯來自查核員」已改寫，誠實列為混淆因素。
- ⚠️ **根因（線上仍在）**：P 用 `build_evidence`（帶當天 EntityContext、不限網域），M 用 `build_evidence_from_ids`（沒帶 context、套 `registry_domains` 白名單）。`scripts/exp3_evidence_gap.py` 重建：M 84／84、P 80／84 和資料庫 v1 一致；7 期證據來源 P 416、M 255，只有 1 個來源的稿 P 2、M 19。白名單用 feed 網址的網域，中央社（feedburner）、ETtoday、風傳媒、三立、BBC、聯合早報等正規媒體被當成「假來源」剔除（P 的證據裡有 172 個素材）。
- ✅（2026-11-24 傍晚已做，見下一段「三項決定」）~~要不要修 M 的證據包，等志晨決定~~：會改 M 記者看到的來源與 `request_hash`、也改凍結後的線上行為。建議做法：加開關（預設關閉），開啟時 M 的 `run_mas` 傳當天 `context`，白名單改成「登錄表來源 id 對應的實際文章網域」，不是 feed 網域。
- 📝 唯讀複本的小坑：`python -m reddit_tracker.daily trace` 會用讀寫方式開 WAL 複本，關閉時清掉空的 `-wal`／`-shm`，之後 `mode=ro` 打不開；資料沒變，用 `?immutable=1` 讀（`open_ro` 已處理）。
- 測試：worktree 全套 530 passed／7 skipped；ruff 通過。不需要重載 newsroom。
- ✅ 併入 main（`554d0fb`，2026-11-24 07:07 fast-forward）：production 全套 533 passed／4 skipped；只動文件、`scripts/`、測試，沒有重載；scheduler Python process 1 個。
- ➡️ 下一步：第 7 項 P0-3a 申請單草稿。

## 更早的紀錄

- 2026-09-13 – 2026-10-29：[`docs/archive/PROGRESS_2026-09_to_10-29.md`](docs/archive/PROGRESS_2026-09_to_10-29.md)
- 2026-10-30 – 2026-11-23：[`docs/archive/PROGRESS_2026-10-30_to_11-23.md`](docs/archive/PROGRESS_2026-10-30_to_11-23.md)
- v4（已廢棄）：[`docs/archive/PROGRESS_v4.md`](docs/archive/PROGRESS_v4.md)
