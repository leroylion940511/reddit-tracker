# 綜合日報編採與發行規格（v2.0 試刊版）

從 `story_clusters` 到讀者手上的報紙：評分 → 各版選題 → 證據包 → 撰稿 → 審稿關卡 → 網頁報紙＋Telegram 精選。對應企劃 5.1 步驟 4–9。舊 v5 Reddit 日報（`newsroom_editions`）不受影響，兩者並行到新報紙試刊通過。

## 每日流程（Asia/Taipei）

| 時間 | 動作 |
| --- | --- |
| 每 15 分鐘 | 收集＋事件聚合（[COLLECTION.md](COLLECTION.md)、[CLUSTERING.md](CLUSTERING.md)） |
| `DAILY_PREPARE` 06:00 | 評分、選題、撰稿、審稿，產生 `site/daily/YYYY-MM-DD.html`，狀態 `drafted`；不發送 |
| 06:00–08:30 | 人工可在控制台或 HTML 檢視；需要時 `--refresh` 重寫 |
| `DAILY_DELIVERY` 08:35 | 只發行既有 draft：Telegram 頭版精選＋完整報紙 HTML 檔；與 v5 的 08:30 錯開 |

兩個排程只有 `DAILY_EDITION_ENABLED=true` 時才註冊。

## 1. 評分（程式計算）

事件範圍：`last_published_at` 在「報紙日期前一天 00:00 減 6 小時」到準備時間之間，且未出現在**更早日期**的日報中（含被合併進去的事件）。板塊在選題時依目前登錄表重新投票（T1／T2、非綜合 feed），聚合時存的板塊只是後備。

```
score = 10·log2(1 + outlet_count)
      + 6·[t1_count > 0]
      + 2·log2(1 + item_count)
      + 4·velocity            # 最近 12 小時新增成員比例，item_count ≥ 3 才計
      − age_hours / 6         # 最後更新距準備時間越久扣越多，最多扣 8
```

報導類型（`kind`），由證據決定，不由 LLM 決定：

| kind | 條件 | 呈現 |
| --- | --- | --- |
| `report` | `outlet_count ≥ 2` 或有 T1 成員 | 一般報導，可上頭版 |
| `single_source` | 只有一家 T2／T3 出處 | 標示「單一來源」，不上頭版 |
| `social` | 只有 T4 成員 | 標示「社群觀察」，只放社群觀察版 |

## 2. 各版選題

| 板塊 | 篇數上限 | 可用 kind |
| --- | ---: | --- |
| 台灣 | 5 | report、single_source |
| 國際 | 5 | report、single_source |
| 兩岸與亞太 | 3 | report、single_source |
| 財經 | 4 | report、single_source |
| 科技 | 4 | report、single_source |
| 科學與健康 | 3 | report、single_source |
| 生活與環境 | 3 | report、single_source |
| 文化娛樂 | 3 | report、single_source |
| 體育 | 3 | report、single_source |
| 社群觀察 | 3 | social |

- 各版依分數取前 N，`report` 優先於 `single_source`；不足時寧缺勿濫，MVP 版（台灣、國際、科技）顯示「本版今日無新稿」，其他版沒稿時顯示「本版未開放」（`render.MVP_SECTIONS`）。
- **已停用來源**（登錄表 `enabled: false`，例如 2026-10-28 停用的 24 個社群來源）以前抓到的素材：不進聚合、不算事件訊號、不進證據包；只由它們組成的事件不進選題。
- **編輯會議**（一次 LLM 請求）：各版取配額兩倍的候選，請 LLM 找出報導同一具體事件的組（通常是中英文各一），合併為一則，證據取兩邊聯集。失敗就略過。
- **頭版**：所有 `report` 中分數最高的 6 則，每版最多 2 則；頭版刊全文，對應板塊不重複刊登。
- 同一事件只會出現一次。

## 3. 證據包

每則事件最多取 6 篇成員：不同出處優先、層級高優先、同出處只取最新一篇。每篇提供出處名稱、層級、原標題、摘要（前 400 字）、發布時間、連結。**只給 LLM 摘要，不抓全文**；試刊期接受這個限制，並在報紙頁尾說明。

## 4. 撰稿

- Provider 由 `DAILY_WRITER` 決定，預設 `codex`；只允許 `codex`／`gemini`／`template`／`fake`（`config.LLM_PROVIDERS`，設定驗證會拒絕 `web`；網頁備援已移除）。`fake`（`llm/fake.py`）離線、不扣額度，給開發測試用。只建立被選用的 client，日報預設不建 GeminiClient。每個板塊一次請求、頭版一次請求，加上編輯會議約 12 次／日。
- **Codex**（`reddit_tracker/llm/codex.py`）：subprocess 呼叫 ChatGPT.app 內建的 `codex exec`，吃本機 ChatGPT 訂閱登入（`~/.codex/auth.json`），不用 API key。模型 `CODEX_MODEL`（預設 `gpt-6.1-sol`、reasoning `low`），逾時 `CODEX_TIMEOUT_SECONDS`=300。輸出用 `--output-schema` 強制 JSON 形狀（`writer.STORIES_SCHEMA`／`GROUPS_SCHEMA`）。每次固定約 16k input tokens 的 agent 開銷，與使用者自己互動用 Codex 共用額度。
- **Codex 安全邊界**：證據是外部不可信內容，Codex 又是 agent，所以每次都在空暫存目錄、`-s read-only`、`--ephemeral --ignore-user-config --ignore-rules` 下執行，關掉 shell／code mode／子 agent／外掛／瀏覽器等工具（`_DISABLED_FEATURES`；CLI 升版新增工具類 feature 要補關），並丟棄含 Telegram token、Gemini／RSSHub key 的輸出。找不到 `CODEX_BIN` 時整期改用模板稿。
- **額度**（`llm/quota.py` 的 `ModelQuotaGuard`）：以 **model 字串**為鍵，同一模型所有用途（`purpose`）共用一個每日計數，`LLM_DAILY_LIMIT` 預設 60，太平洋時間換日，跨 process 共用 `LLM_QUOTA_STATE_PATH` state 檔。每次嘗試（含重試）扣一格；Codex 失敗重試 `CODEX_MAX_RETRIES`=1、Gemini 429 重試 `GEMINI_MAX_429_RETRIES`=1，外層 `WRITE_ATTEMPTS`=2，一版最壞吃 4 格。額度用完拋 `QuotaExhausted`，該版直接改模板稿、不再重試。
- **Gemini**（備用，`purpose="daily"`，`GeminiQuotaGuard` 是 `ModelQuotaGuard` 加每分鐘上限）。
- 指令：繁體中文、只能使用證據包內容、以「據某某報導」歸因、來源說法不一致時並陳、英文與簡體素材要轉為台灣用語、不得補造數字或引述。
- 產出 JSON：`headline`（≤40 字）、`deck`（一句話重點）、`body`（150–400 字）、`why_it_matters`。
- 每組請求失敗（JSON 格式錯、503 過載等）整組重寫最多 2 次（`WRITE_ATTEMPTS`），間隔 15 秒。
- 仍失敗、額度用完或該則未通過審稿關卡時，改用**模板稿**：優先以中文來源為主稿，原標題（簡轉繁）＋「據某某報導」＋摘要前 120 字＋其他出處清單。模板稿會在頁面上標示「摘要整理」。

## 5. 審稿關卡（程式）

逐則檢查，未通過就改用模板稿，並把原因記入 `review_notes`：

1. 標題與正文長度在範圍內。
2. **數字核對**：稿件中出現的阿拉伯數字（兩位數以上或含小數），必須能在證據文字中找到，或與證據中的某個數字只差 10 的整數次方（容許「400 億」對「40 billion」這類換算）。
3. 至少附一個來源連結；`single_source`／`social` 必須帶標示。

人工審閱（試刊期）：頭版與標示 `needs_review` 的稿件由專案成員在發行前看過；程式不會因為沒有人工審閱就停刊，但控制台會列出。

## 6. 發行

- **網頁報紙**：單一自含 HTML（無外部資源），報頭、頭版、各版、每則來源清單、頁尾方法說明；寫入 `site/daily/`（不進版控），控制台 `/daily/{date}` 可直接開。
- **Telegram**：一則文字精選（頭版 6 則標題＋一句重點＋各版篇數），再附上當期 HTML 檔，手機可直接開完整報紙。
- 冪等：`daily_editions.status` 為 `drafting → drafted → publishing → published`；送出途中失敗標 `delivery_failed`，不自動重送。

## 7. 數據欄

證交所 OpenAPI `MI_INDEX` 的發行量加權股價指數與臺灣 50 收盤、漲跌（數字直接取自資料，不經 LLM）。取不到時不顯示。匯率與天氣來源需另行處理（登錄表中停用）。

## 資料表

### `daily_editions`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | int PK | |
| `edition_date` | date, unique | |
| `status` | str(24) | 見上 |
| `window_start` / `prepared_at` | datetime(tz) | 事件範圍 |
| `writer` | str(32) | `codex`／`gemini`／`template`／`mixed` |
| `stats` | JSON | 各版篇數、`ai_articles`、`template_articles`、`llm_requests`、數據欄（10/27 首期為舊鍵 `gemini_articles`／`gemini_requests`） |
| `html_path` | text | |
| `telegram_message_ids` | JSON | |
| `published_at` | datetime(tz) | |
| `created_at` / `updated_at` | datetime(tz) | |

### `daily_articles`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | int PK | |
| `edition_id` | FK → `daily_editions.id`, index | |
| `cluster_id` | FK → `story_clusters.id`, index | |
| `section` | str(32) | |
| `position` | int | 版內順序；頭版另以 `is_front` 標示 |
| `is_front` | bool | |
| `kind` | str(16) | `report`／`single_source`／`social` |
| `score` | float | |
| `signals` | JSON | 評分各項與原始計數 |
| `headline` / `deck` / `body` / `why_it_matters` | text | |
| `sources` | JSON | `[{outlet, source_id, tier, title, url, published_at}]` |
| `writer` | str(16) | `codex`／`gemini`／`fake`／`template` |
| `review_notes` | JSON | 審稿關卡結果 |

## 介面

```python
# reddit_tracker/daily/scoring.py
score_candidates(session, *, edition_date, now, general_sources=frozenset(), disabled_sources=frozenset()) -> list[ScoredCluster]
select_articles(scored) -> list[Selection]
# reddit_tracker/daily/evidence.py
build_evidence(session, cluster_ids, source_names, disabled_sources=frozenset()) -> list[EvidenceItem]
# reddit_tracker/daily/writer.py
DailyWriter(name="codex", *, client=None)   # name: codex / gemini / fake
DailyWriter.find_same_events(candidates) -> list[list[int]]
DailyWriter.write(section, stories) -> dict[int, WrittenStory]
# reddit_tracker/llm/codex.py、llm/gemini.py、llm/fake.py、llm/replay.py：介面相同
CodexClient(*, binary=None, model=None, reasoning_effort=None, timeout=None, purpose="daily", max_retries=None, guard=None)
GeminiClient(*, purpose, api_key=None, model=None, daily_limit=None, requests_per_minute=None, state_path=None, timeout=None, max_retries=None)
# reddit_tracker/llm/quota.py
ModelQuotaGuard(*, state_path, daily_limit, requests_per_minute=None)
ModelQuotaGuard.acquire(*, model, purpose) -> None   # 用完拋 QuotaExhausted
ModelQuotaGuard.used(model) -> int
# reddit_tracker/llm/replay.py（手冊步驟 2／7：重播錄好的回應，找不到就丟 ReplayMissing，不呼叫真模型）
request_hash(*, system, prompt, model, schema) -> str   # sha256(JSON [system, prompt, model, schema])；prompt＝user 訊息以空行相接
load_records(path) -> dict[str, str]   # .json（[{request_hash, response_text, ok}]）或含 llm_records 表的 SQLite；只收 ok
ReplayClient(records, *, model)   # .misses：找不到的 request_hash
client.complete(*, system, messages, max_output_tokens, temperature, json_mode=False, json_schema=None) -> result(.content, .input_tokens, .output_tokens, .cached_tokens)
template_story(evidence, kind) -> WrittenStory
review_story(story, evidence) -> list[str]   # 空 list 代表通過
# reddit_tracker/daily/run.py
plan_edition(session, *, edition_date, now, writer, registry) -> EditionPlan   # 評分→編輯會議→選題→證據包；不撰稿、不寫 DB
#   EditionPlan(candidates: list[ScoredCluster], candidate_count, merged_groups, planned: list[Planned(key, selection, evidence)])
story_evidence(session, cluster: ScoredCluster, registry) -> list[EvidenceItem]   # 選題與回歸集共用
prepare_daily(edition_date, *, writer_mode=None, refresh=False, now=None, writer=None) -> int   # writer：直接指定撰稿者（回歸集 replay），不看 writer_mode
publish_daily(edition_date) -> DailyEdition
```

CLI：

```bash
uv run python -m reddit_tracker.daily prepare [--date YYYY-MM-DD] [--writer codex|gemini|template] [--refresh]
uv run python -m reddit_tracker.daily publish [--date YYYY-MM-DD]
```

## 試編紀錄（2026-10-26，production DB 複本，報紙日期 10/27）

- 1,743 個候選事件 → 編輯會議合併 8 組（巴西、塞爾維亞、委內瑞拉的中英文報導；五中全會三個事件；福田康夫；Anthropic IPO 等）→ 42 則：頭版 6、各版 36。
- Gemini 撰稿 37 則、模板稿 5 則；共 16 次請求，約 6 分鐘（本機限速每分鐘 5 次）。
- 實測遇到的 Gemini 失敗：503 過載（重試後成功）、JSON 格式壞掉、直接回傳陣列而缺外層物件（已改為兩種形狀都接受）。
- 試編中修正：重編時誤把本期舊草稿當成已刊登而排除大事件；板塊在選題時重新投票（Yahoo 股市 feed 改標綜合 feed）；頭版每版最多 2 則；模板稿與證據包優先保留中文來源。
