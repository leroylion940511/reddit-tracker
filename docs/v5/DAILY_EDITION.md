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

## 2. 各版選題（手冊步驟 4：併版與配額）

只做頭版＋台灣、國際、科技三個內版，**一期 12 篇正式稿**：

| 內版 | 篇數上限 | 可用 kind |
| --- | ---: | --- |
| 台灣 | 4 | report、single_source |
| 國際 | 4 | report、single_source |
| 科技 | 4 | report、single_source |

- **先改寫分版**（`daily/sections.py`，在 `score_candidates` 之後、編輯會議之前）。規則全部由程式判斷，詞表在 `seeds/section_rules.yaml`；比對事件內所有素材（已停用來源除外）的標題，先去開頭 `[..]`／`【..】` 標籤、簡轉繁。中文詞用子字串比對；英文詞不分大小寫，但前後不能緊接英數字（所以「AI太燒錢」算 AI，Thailand 不算）：
  | 原板塊 | 規則（依序） | 新板塊 |
  | --- | --- | --- |
  | `cross_strait` | 標題有台灣詞（台灣、陸委會、國台辦、立法院、台股、Taiwan…），或有台灣官方來源（登錄表 taiwan 版的 T1） | `taiwan` |
  | | 其他 | `world` |
  | `finance` | 台灣詞或台灣官方來源 | `taiwan` |
  | | 科技詞（晶片、輝達、微軟、AI、Microsoft、SpaceX…），或事件裡有登錄表科技版的來源 | `tech` |
  | | 素材全是 `zh-Hant`（台灣媒體），而且沒有國際詞（美股、美國、歐盟、中國…） | `taiwan` |
  | | 其他（外文來源或有國際詞） | `world` |
  | `life_env`（`society_sections`） | 教育、社會詞（教育部、學校、警方、地檢署、詐騙…），而且有台灣詞、台灣官方來源，或全是 `zh-Hant`（E14） | `taiwan` |
  | 其他版（科學、生活、文化、體育） | 不改 | 只出頭版標題短訊 |

  改過的事件在 `signals` 記 `original_section`、`section_rule`（命中的規則與詞）；`stats.section_rewrites` 記統計，例如 `{"cross_strait→world": 123}`。**只改配額不改分版的話，兩岸、財經稿會整篇消失**（`tests/test_sections.py` 證明）。
- 各內版依分數取前 4，`report` 優先於 `single_source`；不足時寧缺勿濫，顯示「本版今日無新稿」。
- **頭版從這 12 篇裡標記 `is_front`，不另佔名額**：依分數取 `report`，每版最多 2 則；不足 6 則時放寬每版上限，仍不足就少放（`single_source` 不上頭版）。頭版稿全文只刊在頭版；它所屬的內版放一則**連結**（標題＋「見頭版」，連到 `#story-{cluster_id}`），不重寫、不重印。
- `DailyArticle.position`：頭版稿＝頭版順位，其他＝內版順位；內版順位一律寫在 `signals.section_position`（render 依它排內版，舊期沒有就用 `position`）。
- **其他版（科學與健康、生活與環境、文化娛樂、體育）只出頭版「標題短訊」**（`select_briefs`）：每版取分數最高的 2 則 `report`／`single_source`（不與正式稿重複），標題取證據包裡的中文來源（沒有就第一篇，去分類標籤），附媒體名與原文連結；**不呼叫 LLM、不寫正文、不寫 `daily_articles`**，存在 `stats.briefs`（`[{cluster_id, section, kind, label, headline, outlet, url, outlet_count, score}]`）。這些版的選單保留，頁面顯示「本版未開放」（`render.MVP_SECTIONS`）。社群觀察版的來源已全部停用，`social` 事件不再選題。
- **已停用來源**（登錄表 `enabled: false`，例如 2026-10-28 停用的 24 個社群來源）以前抓到的素材：不進聚合、不算事件訊號、不進證據包；只由它們組成的事件不進選題。
- **編輯會議**（`daily/desk.py`，手冊步驟 3 第 4 點）：各版取配額兩倍的候選（`desk_pool`），合併報導同一具體事件的組，證據取兩邊聯集。
  - **程式合併（主要）**：中文事件 × 外文事件，某一對成員標題用譯名表統一成中文後有 ≥ `CLUSTER_CROSS_LANG_MIN_ENTITIES`（預設 2）個共同實體就合併（E06 巴西、E07 塞爾維亞）。不需要 LLM，模板模式也會做。
  - **LLM 第二意見**：`find_same_events` 一次請求（有 LLM writer 時）。它說要合併的組，程式逐對確認共同實體 ≥ `CLUSTER_LLM_MERGE_MIN_ENTITIES`（預設 1），沒有共同實體的配對剔除並記在 `stats.rejected_merges`（E01：美式足球稿不再被併進塞爾維亞）。LLM 失敗就只用程式合併。
  - 兩個事件的共同實體＝兩邊成員標題兩兩比對時最多的那一對（共同實體規則見 CLUSTERING.md）。
  - `apply_merges`：合併組可以重疊（A＋B、A＋C），被吸收的事件之前併入的事件會一起帶過去。
  - `stats`：`merged_groups`（實際套用）、`entity_merge_groups`（程式）、`llm_merge_groups`（LLM 原始回應）、`rejected_merges`（`{group, cluster_id, title, reason}`）。
- 同一事件只會出現一次。

## 3. 證據包

每則事件最多取 6 篇成員：不同出處優先、層級高優先、同出處只取最新一篇。每篇提供出處名稱、層級、原標題、摘要（前 400 字）、發布時間、連結。**只給 LLM 摘要，不抓全文**；試刊期接受這個限制，並在報紙頁尾說明。

- **轉載併成一列**（E10）：`mark_reprints` 認出的轉載與重複稿只放原稿一列，`sources[].outlet` 顯示「中央社（中央廣播電台轉載）」並多一個 `reprinted_by`；撰稿時歸因給原稿。
- **相關性過濾**（手冊步驟 3 第 5 點、E01、E05）：每一篇都要和事件代表標題（合併事件取主事件 `cluster_ids[0]` 的代表素材）有共同實體，判斷方法與聚合相同（先用譯名表統一成中文；中文片段的「少見」以聚合時間窗 72 小時內的素材標題為準，`title_context`）。沒有就剔除，`review_notes` 記「剔除：AP｜Jaxon Smith-Njigba leads…，原因：無共同實體」。代表標題本身抽不到任何實體時不過濾，記「未做相關性過濾：…」。10/27 重編只有金鐘獎一則剔除了 3 篇（新人獎的分稿）。

## 4. 撰稿

- Provider 由 `DAILY_WRITER` 決定，預設 `codex`；只允許 `codex`／`gemini`／`template`／`fake`（`config.LLM_PROVIDERS`，設定驗證會拒絕 `web`；網頁備援已移除）。`fake`（`llm/fake.py`）離線、不扣額度，給開發測試用。只建立被選用的 client，日報預設不建 GeminiClient。頭版一次請求、三個內版各一次（只寫非頭版的稿），加上編輯會議一次，一期最多 5 次（＋重試）；短訊 0 次。
- **Codex**（`reddit_tracker/llm/codex.py`）：subprocess 呼叫 ChatGPT.app 內建的 `codex exec`，吃本機 ChatGPT 訂閱登入（`~/.codex/auth.json`），不用 API key。模型 `CODEX_MODEL`（預設 `gpt-6.1-sol`、reasoning `low`），逾時 `CODEX_TIMEOUT_SECONDS`=300。輸出用 `--output-schema` 強制 JSON 形狀（`writer.STORIES_SCHEMA`／`GROUPS_SCHEMA`）。每次固定約 16k input tokens 的 agent 開銷，與使用者自己互動用 Codex 共用額度。
- **Codex 安全邊界**：證據是外部不可信內容，Codex 又是 agent，所以每次都在空暫存目錄、`-s read-only`、`--ephemeral --ignore-user-config --ignore-rules` 下執行，關掉 shell／code mode／子 agent／外掛／瀏覽器等工具（`_DISABLED_FEATURES`；CLI 升版新增工具類 feature 要補關），並丟棄含 Telegram token、Gemini／RSSHub key 的輸出。找不到 `CODEX_BIN` 時整期改用模板稿。
- **額度**（`llm/quota.py` 的 `ModelQuotaGuard`）：以 **model 字串**為鍵，同一模型所有用途（`purpose`）共用一個每日計數，`LLM_DAILY_LIMIT` 預設 60，太平洋時間換日，跨 process 共用 `LLM_QUOTA_STATE_PATH` state 檔。每次嘗試（含重試）扣一格；Codex 失敗重試 `CODEX_MAX_RETRIES`=1、Gemini 429 重試 `GEMINI_MAX_429_RETRIES`=1，外層 `WRITE_ATTEMPTS`=2，一版最壞吃 4 格。額度用完拋 `QuotaExhausted`，該版直接改模板稿、不再重試。
- **Gemini**（備用，`purpose="daily"`，`GeminiQuotaGuard` 是 `ModelQuotaGuard` 加每分鐘上限）。
- 指令：繁體中文、只能使用證據包內容、以「據某某報導」歸因、來源說法不一致時並陳、英文與簡體素材要轉為台灣用語、不得補造數字或引述。2026-10-29 刪掉原第 4 條（單一來源／社群要在正文明說）：警語改由程式加（手冊 6.6、E16）。
- **警語由程式加在正文最後一段**（`finalize_story`，LLM 稿與模板稿都經過）：`single_source`「目前僅有單一媒體報導，後續發展待確認。」、`social`「此為網路社群討論，不代表整體民意，內容亦未經證實。」、只來自 arXiv 的稿「預印本未必經過同儕審查，研究結論仍待驗證。」；`report` 沒有警語。
- **arXiv 預印本**（E12）：證據全部來自 `arxiv.org` 的稿件，請求裡帶 `"source_type":"preprint"`，提示加一段「正文第一句寫『一篇發表於 arXiv 的預印本論文指出』」（只有這種稿件時才加）；模板稿也以這句開頭；標題旁標籤是「預印本」不是「單一來源」，導言【預印本】。
- 產出 JSON：`headline`（≤40 字）、`deck`（一句話重點）、`body`（150–400 字）、`why_it_matters`。
- 每組請求失敗（JSON 格式錯、503 過載等）整組重寫最多 2 次（`WRITE_ATTEMPTS`），間隔 15 秒。
- 仍失敗、額度用完或該則未通過審稿關卡時，改用**模板稿**：優先以中文來源為主稿，原標題（簡轉繁）＋「據某某報導」＋摘要前 120 字＋其他出處清單。模板稿會在頁面上標示「摘要整理」。

## 5. 審稿關卡（程式）

逐則檢查，未通過就改用模板稿，並把原因記入 `review_notes`：

1. 標題與正文長度在範圍內。
2. **數字核對**：稿件中出現的阿拉伯數字（兩位數以上或含小數），必須能在證據文字中找到，或與證據中的某個數字只差 10 的整數次方（容許「400 億」對「40 billion」這類換算）。
3. 至少附一個來源連結；`single_source`／`social` 必須帶標示。
4. **不得自己寫警語**：標題、導言、正文、重要性任何地方出現「僅有／只有一家媒體／來源」這類句子就不通過（警語只能是程式加的最後一段，E16）。
5. **預印本稿**：不得寫「獨家」「一家媒體」，正文要有「預印本」（E12）。

人工審閱（試刊期）：頭版與標示 `needs_review` 的稿件由專案成員在發行前看過；程式不會因為沒有人工審閱就停刊，但控制台會列出。

## 6. 發行

- **網頁報紙**：單一自含 HTML（無外部資源），報頭、頭版、各版、每則來源清單、頁尾方法說明；寫入 `site/daily/`（不進版控），控制台 `/daily/{date}` 可直接開。
- **Telegram**：一則文字精選（頭版 6 則標題＋一句重點＋各內版篇數（含頭版稿）＋短訊則數），再附上當期 HTML 檔，手機可直接開完整報紙。
- 網頁頭版：6 則全文＋「短訊」清單（其他版的標題、版別、媒體、原文連結）；內版：頭版稿是連結、其餘全文。
- 冪等：`daily_editions.status` 為 `drafting → drafted → publishing → published`；送出途中失敗標 `delivery_failed`，不自動重送。

## 7. 數據欄

證交所 OpenAPI `MI_INDEX` 的發行量加權股價指數與臺灣 50 收盤、漲跌（數字直接取自資料，不經 LLM）。取不到時不顯示。匯率與天氣來源需另行處理（登錄表中停用）。

**延遲標示**（E15）：收盤日期距出刊日超過 1 個交易日（`market.is_stale`；06:00 出刊時最新應是前一個交易日），網頁數據欄與 Telegram 精選都加「資料更新延遲」。交易日只排除週末、不含國定假日：連假後第一期會多標一次（寧可多標）。日期不明也算延遲。

## 資料表

### `daily_editions`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | int PK | |
| `edition_date` | date, unique | |
| `status` | str(24) | 見上 |
| `window_start` / `prepared_at` | datetime(tz) | 事件範圍 |
| `writer` | str(32) | `codex`／`gemini`／`template`／`mixed` |
| `stats` | JSON | 各版篇數、`ai_articles`、`template_articles`、`llm_requests`、`front_articles`、`briefs`（頭版短訊）、`section_rewrites`（改寫分版統計）、數據欄（10/27 首期為舊鍵 `gemini_articles`／`gemini_requests`） |
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
| `position` | int | 頭版稿＝頭版順位（`is_front`）；其他＝內版順位。內版順位一律另寫在 `signals.section_position` |
| `is_front` | bool | |
| `kind` | str(16) | `report`／`single_source`／`social` |
| `score` | float | |
| `signals` | JSON | 評分各項與原始計數 |
| `headline` / `deck` / `body` / `why_it_matters` | text | |
| `sources` | JSON | `[{outlet, source_id, tier, title, url, published_at, reprinted_by?}]`；`outlet` 是顯示名稱（轉載併列時如「中央社（中央廣播電台轉載）」） |
| `writer` | str(16) | `codex`／`gemini`／`fake`／`template` |
| `review_notes` | JSON | 證據包相關性過濾剔除的來源＋審稿關卡結果 |

## 介面

```python
# reddit_tracker/daily/scoring.py
score_candidates(session, *, edition_date, now, general_sources=frozenset(), disabled_sources=frozenset()) -> list[ScoredCluster]
select_articles(scored) -> list[Selection]   # 三內版各 4 篇；頭版 6 則從中標記；頭版在前
#   Selection(cluster, section, position, is_front, section_position=None)
#   SECTION_QUOTAS = {"taiwan": 4, "world": 4, "tech": 4}
# reddit_tracker/daily/sections.py（手冊步驟 4）
rewrite_sections(session, scored, *, registry, rules=None) -> list[ScoredCluster]   # 就地改寫板塊
classify(section, members: Members, rules: SectionRules) -> (new_section, rule | None)
load_section_rules(path=seeds/section_rules.yaml) -> SectionRules
rewrite_summary(scored) -> dict[str, int]   # {"finance→tech": 119, ...}
select_briefs(scored, selections, evidence_for, *, sections=BRIEF_SECTIONS, per_section=2) -> list[dict]
# reddit_tracker/daily/evidence.py
build_evidence(session, cluster_ids, source_names, disabled_sources=frozenset(), *, lexicon=None, context=None) -> EvidencePack
#   EvidencePack(items: list[EvidenceItem], notes: list[str])   # notes：剔除紀錄，進 review_notes
#   EvidenceItem(outlet, source_id, source_name, tier, lang, title, summary, url, published_at, reprinted_by=[])
#   EvidenceItem.display_name / as_source()
title_context(session, now, lexicon, disabled_sources=frozenset()) -> EntityContext   # 聚合時間窗內的素材標題
short_outlet(name) -> str   # 「中央社 政治」→「中央社」
# reddit_tracker/daily/market.py
trading_days_between(close: date, edition: date) -> int
is_stale(close: str | date | None, edition: date) -> bool   # 超過 1 個交易日
# reddit_tracker/daily/writer.py
DailyWriter(name="codex", *, client=None, lexicon=None)   # name: codex / gemini / fake；撰稿提示附上證據中出現的譯名表名字
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
template_story(evidence, kind) -> WrittenStory   # 不含警語
review_story(story, evidence) -> list[str]   # LLM 稿審稿（加警語前跑）；空 list 代表通過
finalize_story(story, evidence, kind) -> WrittenStory   # 文末加警語（單一來源／社群／預印本），可重複呼叫
is_preprint_only(evidence) -> bool / notice_for(evidence, kind) -> str | None
# reddit_tracker/daily/run.py
plan_edition(session, *, edition_date, now, writer, registry) -> EditionPlan   # 評分→編輯會議→選題→證據包；不撰稿、不寫 DB
#   EditionPlan(candidates: list[ScoredCluster], candidate_count, merged_groups, planned: list[Planned(key, selection, evidence, notes)], desk: DeskMerges, context: EntityContext, briefs: list[dict])
# reddit_tracker/daily/desk.py
desk_merges(session, pool, llm_groups, *, lexicon, rules, disabled_sources=frozenset(), context_cluster_ids=None) -> DeskMerges
#   DeskMerges(groups, entity_groups, llm_groups, rejected: list[{group, cluster_id, title, reason}])
apply_merges(scored, groups) -> list[ScoredCluster]   # scoring.py；重疊的組會把已併入的事件一起帶過去
story_evidence(session, cluster: ScoredCluster, registry, context=None) -> EvidencePack   # 選題與回歸集共用
prepare_daily(edition_date, *, writer_mode=None, refresh=False, now=None, writer=None) -> int   # writer：直接指定撰稿者（回歸集 replay），不看 writer_mode
publish_daily(edition_date) -> DailyEdition
parse_now(text) -> datetime   # --now 的值：ISO；不帶時區＝出刊時區（台北），回傳 UTC aware
recluster(now) -> ClusterRunStats   # 用同一個 now 跑 cluster_recent_items（重編舊期用）
```

CLI：

```bash
uv run python -m reddit_tracker.daily prepare [--date YYYY-MM-DD] [--writer codex|gemini|template] [--refresh] [--now ISO] [--recluster]
uv run python -m reddit_tracker.daily publish [--date YYYY-MM-DD]
```

`--now`（手冊步驟 3 第 8 點）：把「現在」固定在某個時間，評分、選題時間窗、證據包相關性的當天素材、
版次 `prepared_at` 都用它；加 `--recluster` 時先用**同一個** `now` 聚合一輪。沒給 `--date` 時出刊日＝`now` 的台北日期。
重編 10/27：`DATABASE_URL=sqlite:///data/work/1027_rebuild.db … prepare --now 2026-10-27T06:00 --recluster --refresh`；
完整流程（刪截止後素材、清聚合與所有期數、重算重複稿）見 `scripts/rebuild_1027.py`。

## 試編紀錄（2026-10-26，production DB 複本，報紙日期 10/27）

- 1,743 個候選事件 → 編輯會議合併 8 組（巴西、塞爾維亞、委內瑞拉的中英文報導；五中全會三個事件；福田康夫；Anthropic IPO 等）→ 42 則：頭版 6、各版 36。
- Gemini 撰稿 37 則、模板稿 5 則；共 16 次請求，約 6 分鐘（本機限速每分鐘 5 次）。
- 實測遇到的 Gemini 失敗：503 過載（重試後成功）、JSON 格式壞掉、直接回傳陣列而缺外層物件（已改為兩種形狀都接受）。
- 試編中修正：重編時誤把本期舊草稿當成已刊登而排除大事件；板塊在選題時重新投票（Yahoo 股市 feed 改標綜合 feed）；頭版每版最多 2 則；模板稿與證據包優先保留中文來源。
