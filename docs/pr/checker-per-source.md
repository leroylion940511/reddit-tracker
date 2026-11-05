# 查核員逐來源判斷（`feat/checker-per-source`）

基於 `fix/newsroom-1106`（未部署）。**只供 review，不部署。** 本分支開發時沒有呼叫 Codex，也沒有重錄任何錄音。

## 摘要

- M 組查核員可以對每個程式點名的可疑來源各回一個 `KEEP`／`REMOVE`，不必再全部一起刪。
- 新設定 `FACT_CHECKER_PER_SOURCE`，**預設 `false`**。關閉時查核員請求和現在逐字相同，`request_hash` 不變，既有錄音照常重播。
- 解讀新舊格式都收。數字規則、LLM 失敗／額度用完的行為都不變。

## 問題

`CHECKER_SCHEMA` 只有全域 `action`（OK／CHALLENGE）。程式點名 S2、S3，查核員回 CHALLENGE 時，S2、S3 一起刪。

11/01 story 5330（台北市長辯論）：

| 來源 | 內容 | 實際 | 應該 |
| --- | --- | --- | --- |
| S1 自由時報 | 台北市長選戰首場辯論 | 保留 | 保留 |
| S2 央廣 | 台北市長選舉電視辯論會 31 日登場 | **刪** | 保留（同一場） |
| S3 公視 | 高雄市長選戰辯論會 | 刪 | 刪 |

查核員的 detail 其實寫了「S2 與 S1 為同一場台北市長辯論…S3 則是高雄市長辯論」，但格式裝不下這個判斷。

## 改動

| 檔案 | 內容 |
| --- | --- |
| `reddit_tracker/config.py` | `fact_checker_per_source: bool = False` |
| `reddit_tracker/daily/mas/orchestrator.py` | `CHECKER_PER_SOURCE_SCHEMA`、`checker_source_verdicts()`、`_checker_relevance_prompt()`；`review_one(..., per_source=None)`，沒給就讀設定 |
| `scripts/recheck_factcheck.py` | 改用 `checker_source_verdicts`（fixture 結果不變） |
| `tests/test_factcheck_relevance.py` | 新增 7 個測試 |
| 文件 | `HANDBOOK_ADAPTATION.md` 新增一節；`DAILY_EDITION.md` 介面；README 設定表；`.env.example` |

### 介面

旗標開啟時，可疑時那一次查核員請求：

- system：`CHECKER_SYSTEM`＋原本的「另檢查每個來源…」＋逐來源說明；
- user：開頭多一行 `程式點名的可疑來源：S2、S3`；
- schema：

```json
{"action": "OK|CHALLENGE", "problem": "...", "detail": "...", "required_action": "...",
 "sources": [{"sid": 2, "verdict": "KEEP|REMOVE", "reason": "一句話"}]}
```

`checker_source_verdicts(assessment: str | None, flagged: list[int]) -> dict[int, bool]`（True＝保留）：

| 情況 | 結果 |
| --- | --- |
| 點名來源有 `KEEP`／`REMOVE` | 照它 |
| 點名來源沒提到、或舊格式（沒有 `sources`） | 全域 OK 留，其他刪（＝11/01 規則） |
| 沒點名的來源回 `REMOVE` | 不算；刪來源要程式先點名 |
| 沒回應、格式錯、額度用完、查核員已降級 | 全刪（照程式，不變） |
| 沒出處的數字 | 只看程式，KEEP／OK 都不能放行（不變） |

百分比的第二次查核只在全域 OK 時跳過。全域 CHALLENGE 但來源都 KEEP（異議講的是別的事）時，照原規則再問一次 `_checker_llm`。

## 為什麼用旗標、預設關閉

`request_hash`＝sha256(system＋prompt＋model＋schema)。改提示詞或 schema，hash 就變。

- **選擇：設定旗標，預設關閉。** 關閉時請求逐字不變（`test_per_source_flag_off_sends_the_old_request` 鎖住 schema、user 開頭、system 結尾），`1027_t2a_records.json`、`1027_mas_records.json` 都不用動。開啟由 production `.env` 決定，程式預設不變。
- **不選 replay fallback**（新 hash 找不到就改用舊 hash 的回應）：重播的請求會跟錄到的請求不同，等於重播一個模型沒看過的提示。這違反 `llm/replay.py`「找不到就丟 `ReplayMissing`，不默默替代」的規則，回歸測試也就不再證明什麼。
- **不選直接換成新格式＋重錄**：要呼叫 Codex（本 session 不允許），而且會在試刊前改到線上行為；用旗標可以先 review、再決定開不開。

## 測試

全部用假 client，沒有真 LLM／Codex 呼叫。

- `test_5330_per_source_keeps_same_debate_and_drops_kaohsiung`：查核員回 S2 KEEP、S3 REMOVE → v2 來源＝[S1, S2]、`drop_sids=[3]`、`cleared_sids=[2]`，修稿重驗沒有 STILL_BAD，請求帶逐來源 schema 與點名清單。
- `test_per_source_verdict_parsing`：新格式、舊 OK／CHALLENGE、部分提到、`"S3"` 寫法、未點名的 REMOVE、無效判斷、None、壞 JSON。
- `test_per_source_flag_off_sends_the_old_request`：預設關閉，請求與舊版相同，5330 照舊刪 S2、S3。
- `test_per_source_flag_comes_from_settings`：`FACT_CHECKER_PER_SOURCE=true` 生效。
- `test_per_source_mode_still_accepts_old_global_answers`：旗標開但回舊格式：CHALLENGE 全刪、OK 全留。
- `test_per_source_keep_cannot_clear_unsupported_numbers`：來源全 KEEP，沒出處的數字仍 CHALLENGE。
- `test_per_source_mode_checker_failure_falls_back_to_program`：查核員失敗 → 照程式全刪。

全套 `REDDIT_TRACKER_NO_DOTENV=1 uv run python -m pytest -q`：**392 passed、7 skipped、1 xfailed、1 xpassed**（基準 385／7／1／1；xpassed 是 `trial-dates.md` 已寫，跟本分支無關）。

離線檢查：`FACT_CHECKER_PER_SOURCE=true` 跑 `test_live_codex_t2a_on_1027_copy` 會失敗，2 個 miss（查核員 1＋記者修稿 1；記者修稿提示含 CHALLENGE payload，所以也換 hash）。記者初稿 hash 不變。預設關閉時通過。

## 重錄估計（沒有執行）

| 錄音 | 旗標開啟時要重錄的請求 | 真 Codex 次數 |
| --- | --- | --- |
| `1027_t2a_records.json`（3 筆） | 查核員 1＋記者修稿 1（記者初稿 hash 不變，錄音工具會重用） | **2 次**；每次最多重試 1 次（`CODEX_MAX_RETRIES=1`），最壞 4 次 |
| `1027_mas_records.json`（43 筆，只有 `verify_mas_merge.py` 用，不在 pytest 裡） | 2 筆查核員紀錄；若查核結果變成刪來源或數字異議，各再加 1 次記者修稿 | 2–4 次，最壞 8 次 |

建議：要錄就另存 `1027_t2a_per_source_records.json`，不覆蓋舊檔，新增一個 `per_source=True` 的重播測試。兩條路徑都能重播。順序要先查核員、再記者修稿（修稿提示要用查核員的真實回應）。

## 對實驗二（查核員開與關，11/17–11/18）的影響

手冊 8.2 三組：(a) 全關、(b) 只開程式工具、(c) 程式工具＋查核員 LLM。誤擋＝正常稿被 HOLD，或正確的來源被刪掉。

**哪些組會變：** 只有 (c)。(a)、(b) 不呼叫查核員 LLM，完全不受影響。

**(c) 會怎麼變：**

- **誤擋可能減少**：5330 這類「一次 CHALLENGE 裡一個對、一個錯」的稿，同一事件的來源不再陪葬。正常稿、保留集都適用：保留集是把錯的素材加進別的事件，程式可能同時點名錯的那則和沒有共同名字但其實相關的來源（實際比例要等保留集做出來才知道）。
- **擋下可能小幅減少**：舊規則下，任何 CHALLENGE 都會連帶刪掉錯的來源；新規則下，錯的來源要模型明確回 REMOVE（或沒提到它，同時全域不是 OK）才刪。模型把錯的來源判成 KEEP，就會漏擋。這是用召回換精確，結果要照實報。
- **LLM 呼叫數不變**：一樣是可疑時叫一次，只多一點 output token。
- 報告要寫明 (c) 用哪個設定（`FACT_CHECKER_PER_SOURCE=true/false`）。

**要不要在 11/20 凍結前決定：要，而且期限其實更早。**

1. **最晚 11/17 實驗二開跑前**：(c) 整個實驗要用同一個設定。實驗二 11/17–11/18 先跑，11/20 才凍結，所以 `final-1120` 應該就是實驗二用的設定。
2. **建議 11/09 試刊前決定**：實驗二的正常稿從 7 期試刊 M 稿抽，試刊的 M 組（實驗三）也用同一個查核員。11/09 前定下來，實驗三的 M 和實驗二的 (c) 就是同一個查核員。11/09 後才切換，報告就要說明「實驗三的 M 與實驗二的 (c) 查核員設定不同」。
3. **11/09 前還沒決定**：就維持關閉到 11/18，等凍結後再處理，不要在試刊或實驗中途切換。

**錄音影響：**

- 實驗二本身會呼叫真 Codex（手冊估約 1 天額度），每次嘗試照常寫 `llm_records`。不管旗標開或關，都是新的錄音，不靠 `1027_*` fixture。
- 記者 v1「只產生一次並存檔」（手冊 8.2 第 3 點），不受旗標影響：v1 的提示不含查核員內容。
- 旗標只改 `.env`、程式預設保持 false：`1027_t2a_records.json` 繼續驗證舊路徑，不用重錄；但逐來源路徑只有假 client 測試，沒有真錄音。要有真錄音，就照上面的估計多花 2 次（最壞 4 次）。
- 如果要把程式預設改成 true：`test_live_codex_t2a_on_1027_copy` 會失敗，要先重錄 T2a（或測試明確傳 `per_source=False`）。

**可選（不建議，除非額度夠）：** 把 (c) 拆成 (c-global)、(c-per-source) 兩組比較。v1 共用，查核員要多跑一輪，最多約 30 篇（開發集 5＋保留集 ≤10＋正常稿 15）× 1 次，加上修稿。超出手冊的三組設計，額度也緊。

## Review 重點

1. `checker_source_verdicts` 的退回規則（沒提到的點名來源跟全域 action 走）是否合理。
2. 全域 CHALLENGE＋全部 KEEP 時不跳過百分比查核的取捨。
3. 是否在 11/09 前開 `FACT_CHECKER_PER_SOURCE`；開的話要不要先花 2 次 Codex 錄 T2a 逐來源版。
4. 本分支基於 `fix/newsroom-1106`，部署要等那支先上。

🤖 Generated with [Claude Code](https://claude.com/claude-code)
