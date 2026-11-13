# 綜合日報編採與發行規格（v2.0 試刊版）

從 `story_clusters` 到讀者手上的報紙：評分 → 各版選題 → 證據包 → 撰稿 → 審稿關卡 → 網頁報紙＋Telegram 精選。對應企劃 5.1 步驟 4–9。（舊 v5 Reddit 日報 `newsroom_editions` 已於 2026-10-27 停刊、程式已移除，資料表保留。）

## 每日流程（Asia/Taipei）

| 時間 | 動作 |
| --- | --- |
| 每 15 分鐘 | 收集＋事件聚合（[COLLECTION.md](COLLECTION.md)、[CLUSTERING.md](CLUSTERING.md)） |
| `DAILY_PREPARE` 06:00 | 評分、選題、撰稿、審稿，產生 `site/daily/YYYY-MM-DD.html`，狀態 `drafted`；不發送 |
| 06:00–08:35 | 人工可在 web 或 HTML 檢視；需要時 `--refresh` 重寫。`DAILY_MODE=mas` 需逐則 `approve`，未核准只出標題 |
| `DAILY_DELIVERY` 08:35 | 只發行既有 draft：Telegram 頭版精選＋完整報紙 HTML 檔（當初為與已停刊的 v5 08:30 錯開而定） |

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
  | `finance` | 台灣詞或台灣官方來源（台灣詞含勞動基金、勞退、勞保、國安基金） | `taiwan` |
  | | 科技詞（晶片、輝達、微軟、AI、Microsoft、SpaceX…） | `tech` |
  | | 一半以上的標題有政治詞（選舉、參議員、國會、民主黨、Senate、midterms…；2026-11-06 加） | `world` |
  | | 事件裡有登錄表科技版的來源 | `tech` |
  | | 素材全是 `zh-Hant`（台灣媒體），而且沒有國際詞（美股、美國、歐盟、中國…） | `taiwan` |
  | | 素材全是 `zh-Hant`，有台灣上市櫃公司名（`taiwan_company_terms`：環球晶、日月光、中信金…；2026-11-06 加） | `taiwan` |
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
  - 給 LLM 看的標題是每個事件**證據包的 S1**（`run.lead_titles`，記者實際會寫的那篇），沒有證據才用事件代表標題（2026-11-01 起）。代表稿可能過時：11/01 事件 13410 的代表稿是 10/29 高雄市長辯論，25 篇成員有 23 篇是台北市長辯論，S1 也是台北，LLM 只看到「高雄」就沒和台北辯論 18416 併，同一場辯論見報兩次。
  - 確認 LLM 的組時，標題對不上再看成員**摘要裡的別名**（`EntityLexicon.summary_names`：譯名表名字、中文摘要裡的英文名，例如「幣安（Binance）」），一邊有別名、另一邊的標題名字或別名也有，就算共同實體（2026-11-01 起；10/31 LLM 正確提出中文幣安＋英文 Binance，卻因譯名表沒有幣安被剔除，國際版、科技版各刊一篇）。程式合併（上一點）不看摘要，實驗一方法 C 不受影響。
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
- **Codex**（`reddit_tracker/llm/codex.py`）：subprocess 呼叫 Homebrew 的 `codex exec`（`CODEX_BIN`＝`/opt/homebrew/bin/codex`，2026-10-31 前是 ChatGPT.app 內建 CLI），吃本機 ChatGPT 訂閱登入（`~/.codex/auth.json`），不用 API key。模型 `CODEX_MODEL`（預設 `gpt-6.1-sol`、reasoning `low`），逾時 `CODEX_TIMEOUT_SECONDS`=150（2026-11-06 前 300）；排程的 06:00 準備另有截止 `DAILY_PREPARE_DEADLINE`=08:20（`llm/deadline.py`：每次嘗試前檢查，剩不到 20 秒就丟 `DeadlinePassed`、不扣額度；單次逾時不超過離截止的秒數；M 組把過了截止當成額度 0 照順序降級，P 撰稿直接退模板稿），P 影子另限 `DAILY_SHADOW_MAX_MINUTES`=30 分鐘。輸出用 `--output-schema` 強制 JSON 形狀（`writer.STORIES_SCHEMA`／`GROUPS_SCHEMA`）。每次固定約 16k input tokens 的 agent 開銷，與使用者自己互動用 Codex 共用額度。
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
DailyWriter(name="codex", *, client=None, lexicon=None, purpose="daily")   # purpose＝額度用途； name: codex / gemini / fake；撰稿提示附上證據中出現的譯名表名字
DailyWriter.find_same_events(candidates) -> list[list[int]]
DailyWriter.write(section, stories) -> dict[int, WrittenStory]
# reddit_tracker/llm/codex.py、llm/gemini.py、llm/fake.py、llm/replay.py：介面相同
CodexClient(*, binary=None, model=None, reasoning_effort=None, timeout=None, purpose="daily", max_retries=None, guard=None)
GeminiClient(*, purpose, api_key=None, model=None, daily_limit=None, requests_per_minute=None, state_path=None, timeout=None, max_retries=None)
# reddit_tracker/llm/quota.py
ModelQuotaGuard(*, state_path, daily_limit, requests_per_minute=None, purpose_limits=None)
#   purpose_limits：{purpose: 上限}，仍算進模型總數；CodexClient／GeminiClient 預設帶 {SHADOW_PURPOSE: DAILY_SHADOW_LLM_LIMIT}
ModelQuotaGuard.acquire(*, model, purpose) -> None   # 總數或用途上限用完拋 QuotaExhausted
ModelQuotaGuard.used(model) -> int
ModelQuotaGuard.used_by(model, purpose) -> int
SHADOW_PURPOSE = "shadow"   # P 組影子版的額度用途
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
alias_shared(a: ClusterTitles, b: ClusterTitles, context) -> set[str]   # 至少一邊來自摘要別名的共同名字（只給 confirm_groups）
lead_titles(session, pool, registry, context=None) -> dict[int, str]   # run.py：編輯會議給 LLM 看的標題＝證據包 S1
EntityLexicon.summary_names(text, is_zh) -> frozenset[str]   # collection/entities.py：摘要裡的譯名表名字＋中文摘要裡的英文名
#   DeskMerges(groups, entity_groups, llm_groups, rejected: list[{group, cluster_id, title, reason}])
apply_merges(scored, groups) -> list[ScoredCluster]   # scoring.py；重疊的組會把已併入的事件一起帶過去
story_evidence(session, cluster: ScoredCluster, registry, context=None) -> EvidencePack   # 選題與回歸集共用
prepare_daily(edition_date, *, writer_mode=None, refresh=False, now=None, writer=None, mode=None, shadow=False, snapshot=None) -> int
#   mode 預設讀 DAILY_MODE（pipeline／mas）。shadow=True：P 組寫 site/daily/shadow，不寫 daily_editions。
#   DAILY_MODE=mas 時 publish_daily 若沒有準備好的期數就失敗，不重跑 prepare。
#   shadow=True 時撰稿 client 的額度用途是 SHADOW_PURPOSE（DailyWriter(name, purpose=...)），llm_records.purpose 也記 shadow（2026-11-01 前撰稿誤記 daily）。
prepare_with_shadow(edition_date, *, now=None) -> int   # DAILY_MODE=mas＋DAILY_SHADOW_ENABLED：P 影子先跑建快照，M 用同一份快照；回傳 M 的 edition id
#   影子失敗只記 log（M 自建快照、不匯出）；當天已有 daily_editions 就不跑影子
export_annotation(edition_date, out_root) -> Path | None   # P、M 都有稿才寫 out_root/YYYY-MM-DD/{blind.txt,spot-check.txt,mapping.sha256} 與 out_root/_private/YYYY-MM-DD/mapping.json
export_annotation_report(edition_date, out_root) -> str     # blind-export／export_blind_count.py 共用：「日期 雜湊 當天資料夾 對照表路徑」
private_mapping_path(root, edition_date) -> Path            # blind.py：root/_private/YYYY-MM-DD/mapping.json
publish_daily(edition_date) -> int   # 發行當下用 build_edition_view 重渲染；mas 未核准的全文改成標題短訊
# reddit_tracker/daily/view.py
render_html(view: EditionView) -> str   # 只吃 EditionView
build_edition_view(session, edition_date, run_variant, sections, *, for_publish=False) -> EditionView
view_from_edition(edition, sections) -> EditionView   # 還沒有 page_plans 的舊物件
# reddit_tracker/daily/mas/orchestrator.py
run_mas(session, *, edition_date, snapshot, registry, client, now, pitches=None) -> MasResult
irrelevant_sources(evidence) -> list[(S 編號, EvidenceItem)]   # 查核員程式工具：標題與 S1 沒有共同名字（句首字要包內佐證）＝可疑
checker_says_same_event(assessment: str | None) -> bool          # 查核員 LLM 回 action=OK＝每個來源都和 S1 同一事件
cleared_item_ids(session, story_id) -> set[int]                  # 查核員判定同一事件而保留的素材 id（修稿後重驗跳過）
# reddit_tracker/daily/blind.py
export_blind_count(session, dates, *, seed=BLIND_SEED) -> (text, mapping, sha256)
#   BLIND_SEED = 20261201；EXP2_SEED = 20261211
parse_now(text) -> datetime   # --now 的值：ISO；不帶時區＝出刊時區（台北），回傳 UTC aware
recluster(now) -> ClusterRunStats   # 用同一個 now 跑 cluster_recent_items（重編舊期用）
```

CLI：

```bash
uv run python -m reddit_tracker.daily prepare [--date YYYY-MM-DD] [--writer codex|gemini|template|fake] [--refresh] [--shadow] [--mode pipeline|mas] [--now ISO] [--recluster]
uv run python -m reddit_tracker.daily publish [--date YYYY-MM-DD]
uv run python -m reddit_tracker.daily trace --date YYYY-MM-DD [--variant mas] [--cluster ID]
uv run python -m reddit_tracker.daily approve --story ID --by 名字
uv run python -m reddit_tracker.daily hold --date YYYY-MM-DD --story ID --by 名字
uv run python -m reddit_tracker.daily blind-export --dates YYYY-MM-DD --out DIR
```

`approve`／`hold`（CLI 與回放頁 decision 路由）commit 後會用 `run.refresh_edition_html` 重畫這期的
`site/daily/YYYY-MM-DD.html`：已發行的期數照發行規則（核准的出全文、其餘「未核准」），草稿照 06:00 預覽；
**不會重送 Telegram**。重畫失敗只記 log，核准不受影響。

`--now`（手冊步驟 3 第 8 點）：把「現在」固定在某個時間，評分、選題時間窗、證據包相關性的當天素材、
版次 `prepared_at` 都用它；加 `--recluster` 時先用**同一個** `now` 聚合一輪。沒給 `--date` 時出刊日＝`now` 的台北日期。
重編 10/27：`DATABASE_URL=sqlite:///data/work/1027_rebuild.db … prepare --now 2026-10-27T06:00 --recluster --refresh`；
完整流程（刪截止後素材、清聚合與所有期數、重算重複稿）見 `scripts/rebuild_1027.py`。

## 回放時間線與 3D 編輯室（2026-11-12）

唯讀。把一期發生的事照時間排成一步一步的 `beats`，3D 頁面只負責播放，不做任何新聞判斷。

| 路由 | 內容 |
| --- | --- |
| `GET /daily/{date}/newsroom/office?variant=mas\|pipeline` | 3D 編輯室回放頁（`daily/office_page.py`＋`daily/office.html`） |
| `GET /daily/{date}/newsroom/replay.json?variant=…` | 同一份時間線資料（`daily/replay.py::build_replay`） |
| `GET /daily/{date}/newsroom?variant=…&story=` | 表格版回放與核准（原有；3D 頁不能核准） |
| `GET /daily/_static/three.module.js` | 本機那份 three.js；`reddit_tracker/daily/vendor/three.module.js` 存在才有，否則頁面從 jsDelivr 載入 `three@0.160.0` |

`build_replay(session, edition_date, run_variant) -> dict`：

| 鍵 | 內容 |
| --- | --- |
| `date`、`variant` | 哪一期、哪一組 |
| `timing` | `recorded`（訊息有 `llm_call_id`，時間是真的）或 `reconstructed`（舊期數：訊息時間用同一篇稿、同一角色的第 k 次模型呼叫還原） |
| `phases` | 這一期有出現的階段，依序：`collect`、`cluster`、`pipeline`、`pitch`、`write`、`layout`、`copy`、`approve`、`publish` |
| `roles` | 角色 id → 中文名（含 `wire` 傳真機、`researcher` 資料員、`checktool` 查核工具、`pipeline` 流水線） |
| `stories` | 有寫稿的 story：`section`、`kind`、`score`、`headline`、`source_title`、`final_status`、`versions`、`front`、`lead` |
| `plans` | 每一版 `page_plans`：`version`、`decided_by`、`front{lead,second,briefs}`、`sections{版:[{story_id,display}]}` |
| `beats` | 見下表 |
| `summary` | 收集則數與抓取次數、候選事件數、稿數、訊息數、各角色呼叫次數、降級、發行時間 |

每個 beat：`i`（順序）、`at`／`day`／`iso`（台北時間）、`phase`、`kind`、`actor`、`mode`、`title`、`say`（氣泡文字）、
`detail`（右側面板：提示詞、回應、payload、diff…）、選用的 `to`、`type`／`type_label`／`status`（訊息）、`story_id`、
`secs`（模型耗時）、`walk`（走到對方桌邊）、`paper`（傳一張紙給誰）、`sheets`（收集到的來源與則數）、
`state`（這一步之後的狀態：`stories{id:{status,version,headline}}`、`plan`（`plans` 的索引）、`collected`）。

| `kind` | 來源 | `mode`（頁面怎麼演） |
| --- | --- | --- |
| `collect` | `source_fetch_runs`，準備前 24 小時、每 4 小時一格；`rsshub` 來源歸 `wire`、其餘歸 `researcher` | `print`（傳真機吐紙）／`browse`（資料員上網） |
| `cluster`、`snapshot` | `daily_editions.stats`、`daily_snapshots` | `sort`、`stamp` |
| `llm` | `llm_records` 每次嘗試一步（含失敗）；P 組的呼叫 `actor=pipeline` | `think`（思考氣泡→結果） |
| `message` | `agent_messages`；同一版的 PITCH 併成一步；程式對稿件發的 RELEASE／HOLD `actor=checktool` | `say`／`stamp` |
| `plan` | `page_plans` 每一版 | `board`（看板換版） |
| `version` | P 組的 `story_versions`（P 沒有訊息） | `stamp` |
| `approve` | `story_versions.approved_by/approved_at`，同一人同一分鐘併成一步；晚於發行標 `late` | `stamp` |
| `publish` | `daily_editions.published_at` | `publish` |

資料直接嵌在頁面的 `<script type="application/json">`（`</` 會拆開），所以頁面另存下來就能離線重看那一期（3D 需要 three.js）。

### 訊息的時間、連結與狀態（2026-11-12 起）

- `agent_messages.llm_call_id`：這則訊息來自哪一次模型呼叫（`llm/records.last_record_id()`；重播命中舊紀錄時指到那一列）。程式自己發的訊息是空的。
- 正式出刊（呼叫 `prepare_daily`／`prepare_with_shadow` 時沒給 `now`）用 `protocol.wall_clock()`，`Clock.tick()` 回真實時間；有給 `now`（重編、回歸集、測試）維持每則 +1 秒，結果可重現。提示詞、`request_hash` 都不受影響。
- `run_mas` 結束時 `protocol.settle_messages()` 把已處理的 PITCH、RELEASE、PAGE_OBJECTION、REVISION_DONE、REBUT、REQUEST_REVISION 標成 `handled`；沒解決的 CHALLENGE 與等真人的 HOLD 留 `pending`。

## 前台標示（2026-11-12）

報頭印「第 N 期」（`view.edition_issue_number`：到這一天為止第幾期）與台北時間的出刊時間；多來源報導在標題旁標「多來源」；
來源列是「媒體｜標題｜時間（台北）」；「為什麼重要」裡的 `[S1]` 也變成連結；頁尾有「依標題與摘要撰稿」；
M 組頁尾的撰稿數照版面上有全文的稿計算。

## 試編紀錄（2026-10-26，production DB 複本，報紙日期 10/27）

- 1,743 個候選事件 → 編輯會議合併 8 組（巴西、塞爾維亞、委內瑞拉的中英文報導；五中全會三個事件；福田康夫；Anthropic IPO 等）→ 42 則：頭版 6、各版 36。
- Gemini 撰稿 37 則、模板稿 5 則；共 16 次請求，約 6 分鐘（本機限速每分鐘 5 次）。
- 實測遇到的 Gemini 失敗：503 過載（重試後成功）、JSON 格式壞掉、直接回傳陣列而缺外層物件（已改為兩種形狀都接受）。
- 試編中修正：重編時誤把本期舊草稿當成已刊登而排除大事件；板塊在選題時重新投票（Yahoo 股市 feed 改標綜合 feed）；頭版每版最多 2 則；模板稿與證據包優先保留中文來源。

## PR #1 整合介面（2026-10-30；以下取代上文舊流水線的相衝敘述）

- `prepare_daily(..., snapshot=None)`：提供 `DailySnapshot` 或 `{"candidates": [...]}` 時跳過評分與編輯會議，使用凍結的證據 id。兩組共用一份快照；`shadow=True` 即使當天已有 M 組版次也會產生 P 影子版（手動執行時會改寫快照；自動排程的 `prepare_with_shadow` 在已有版次時不跑影子）。
- `run_mas`：三內版共用 `select_articles` 正式稿名額；三次分版主編呼叫只改角度／推薦。版面編輯提出異議，總編裁決頭版。決定只能引用本期正式稿，不能讓 HOLD 上頭版；保留內版其他稿，頭版／內版連結只落一筆 `daily_articles`，保留 `merged_cluster_ids`。
- `EditionView` 把同一正式稿展開成頭版全文與內版連結；渲染不重寫正文。P／M 都保留步驟 4 的六則頭版全文，其餘版面標題短訊來自 `stats.briefs`，不送 LLM。舊期 anchor 用 cluster id，新版 page plan 用 story id。
- **查核員刪來源**（2026-11-01 起）：`irrelevant_sources` 只挑「可疑」來源——標題與 S1 沒有共同名字（譯名表、句中大寫英文字、3 位數以上數字；句首大寫字要同一證據包其他標題在句中也大寫才算，例如 Binance、Oleshky）；不比中文片段（高雄、台北兩場辯論都有「市長選戰」）。有可疑來源或沒出處的數字才叫查核員 LLM 一次；LLM 回 `OK`（提示要求無關來源必須異議）就保留可疑來源，RELEASE／CHALLENGE 的 payload 記 `cleared_sids`、`cleared_item_ids`，修稿後重驗不再點名它們；LLM 回 CHALLENGE、失敗或額度用完才照程式刪。沒出處的數字仍不能被 LLM 的 OK 放行。10/31、11/01 兩期原本刪掉 21 個來源（11/01 有 8 篇剩 1 家），重算後只刪 3 個（`scripts/recheck_factcheck.py`）。
  - **逐來源判斷（`FACT_CHECKER_PER_SOURCE`，預設 false）**：開啟時那一次查核員請求改用 `CHECKER_PER_SOURCE_SCHEMA`＝舊四欄＋`sources: [{"sid": int, "verdict": "KEEP"|"REMOVE", "reason": str}]`，user 開頭多一行「程式點名的可疑來源：S2、S3」。解讀 `checker_source_verdicts(assessment, flagged) -> {sid: 保留?}`：有逐來源判斷照它；沒提到的點名來源與舊格式回應照全域 action（OK 留、其他刪）；沒點名的來源 REMOVE 不算；沒回應／格式錯全刪。只有全域 OK 才跳過百分比的第二次查核。關閉時請求與 11/01 前逐字相同（`request_hash` 不變）。設計與錄音影響見 `docs/pr/checker-per-source.md`。
- `stats.role_calls`、`llm_requests` 統計本期本組 Codex 嘗試（包含重試），`degraded` 順序為文稿編輯、查核員 LLM、記者模板；`injection_log` 留下被擋的來源指示。文稿編輯 CHALLENGE 會交給記者修稿並重驗；缺乏可驗證來源則 HOLD。
- `llm/records.py` 是唯一紀錄入口。`RecordingCodexClient` 只查快取、設定 metadata、委派 `CodexClient.complete`；`scripts/llm_recorder.py` 僅保留相容 import，不另有重試或 INSERT。Replay 不呼叫真模型。
- `b8d4f0a17c33` 先檢查欄位與 index，只補缺少的；舊列保留、無 hash 的舊列不能 replay。降回 `a6c9e2f31d84` 會移除新增表／錄音欄位，保留舊列基礎欄位；如需回復錄音必須事先備份複本。
- 模型固定為 `gpt-6.1-sol | codex-cli 0.166.0 | reasoning_effort=low`（2026-10-31 由 ChatGPT.app 0.164.0-alpha.11.1 改為 Homebrew 0.166.0）。`llm/codex_version.py` 在排程啟動與每天準備前比對 `codex --version`，不一致或讀不到記 ERROR＋Telegram 警告、照常出刊；`llm_records.model_version` 的 `codex-cli` 段是 client 實測版本（讀不到寫 `codex-cli unknown(locked 0.166.0)`）。replay 的 `request_hash` 不含 CLI 版本。數字檢查只放行明確單位換算，純數字 14／140 不放行，也不把 published_at 當數字證據。
- MAS 發行時依最新 page plan 與核准狀態重新渲染，未核准只能印標題短訊。P 影子版只存不發。舊 v5 Reddit 日報程式已移除，沒有雙排程並行。
- 無人值守檢查使用 `REDDIT_TRACKER_NO_DOTENV=1`，Settings 不開啟 dotenv；不要從 production 取得設定。
- `scripts/verify_mas_merge.py --stage t2a|mas [--live]` 只用 `data/work` 複本，已有目的 DB 就拒絕覆寫。`--live` 才能呼叫 Codex，固定 `LLM_QUOTA_STATE_PATH=data/work/llm-quota-merge.json`、`LLM_DAILY_LIMIT=40`；先完成回歸重播檢查再執行。T2a 專用證據刻意保留原始 E01 足球來源，正式編採仍先過濾。
- E11（莫德納，MarketWatch item 2736，單一來源、財經改判國際，重編沒入選）不走整期 MAS。`uv run python scripts/record_e11.py --live` 只把這一則送進記者→（可疑才）查核員→文稿編輯，寫 `data/work/1027_e11.db`，額度檔 `data/work/llm-quota-e11.json`，新的 Codex 呼叫上限 5，不讀 `.env`、不開 production DB。匯出 `tests/regression/fixtures/1027_e11_evidence.json` 與 `1027_e11_records.json`。沒有這兩個檔時 `tests/test_e11_replay.py` skip；`--check` 只重播。

## 實驗二用的查核員開關（2026-11-13）

`daily/mas/orchestrator.py`：

```python
CHECKER_MODES = ("full", "program", "off")

def review_one(session, *, edition_date, story, evidence, client, now,
               degraded=None, per_source=None,
               checker_mode="full", draft=None) -> StoryVersion
def reporter_draft(session, client, *, edition_date, story, evidence, degraded) -> tuple[str, str, str, str]
```

- `checker_mode`：`full`＝線上行為；`program`＝只用程式的相關性規則，不呼叫查核員 LLM；`off`＝不做相關性檢查。數字檢查三種都開。
- `draft`：`(headline, deck, body, why_it_matters)`，有給就不呼叫記者寫 v1。
- 線上（`run_mas`）不傳這兩個參數。`daily/evidence.py` 的 `raw_evidence_item(member, source_names)` 不做相關性過濾，只給實驗二把無關素材加進證據包。規則見 `docs/eval/EXP2_DESIGN.md`。

## desk-v3（開發中，全部預設關閉）

分支 `feat/desk-v3`；計畫與交接見 `docs/pr/desk-v3.md`。每個開關關閉時，送給模型的請求與 `request_hash` 逐字不變。

### A1 主編、總編看得到摘要（`MAS_RICH_CONTEXT`，desk-v3，預設關閉）

`config.py`：`mas_rich_context: bool = False`（環境變數 `MAS_RICH_CONTEXT`）。

`daily/mas/orchestrator.py`：

```python
RICH_SUMMARY_CHARS = 200
rich_fields(evidence: list[EvidenceItem] | None) -> {"summary": str, "outlets": list[str], "outlet_count": int}
_story_card(session, story_id, hold_ids, evidence_of: dict[int, list[EvidenceItem]] | None = None) -> dict
_resolve_t1(..., evidence_of=None)   # run_mas 傳入本期證據包
_resolve_t3(..., evidence_of=None)
```

- `summary`：S1（證據包第一篇）摘要去頭尾空白後截 `RICH_SUMMARY_CHARS` 字；證據包有注入標記（`evidence_has_injection`）時給空字串。`outlets`：證據包 `display_name` 去重、保持順序（轉載併成一列，例如「中央社（央廣轉載）」）；`outlet_count`＝`len(outlets)`。
- 開啟時：分版主編請求的每個 `candidates[]` 多這三欄（接在 `title` 後）；總編 T1 的 `story`／`current_front[]`、T3 的 `candidates[]` 稿件卡也多這三欄。`evidence_of` 沒傳（例如 `scripts/verify_t1_t3.py`）時稿件卡不加欄位。
- 關閉時：分版主編候選欄位仍是 `section, story_id, angle, priority, sender, title`，稿件卡仍是 `story_id, section, kind, score, headline, hold`（測試 `tests/test_desk_v3.py`）。

### B1 開放版面護欄（`MAS_OPEN_LAYOUT`，desk-v3，預設關閉）

`config.py`：`mas_open_layout: bool = False`、`mas_section_min: int = 1`、`mas_section_max: int = 8`、`mas_edition_max: int = 18`（環境變數同名大寫）。

`daily/mas/layout.py`：

```python
@dataclass(frozen=True)
class LayoutLimits: enabled: bool; section_min: int; section_max: int; edition_max: int
check_limits(section_min, section_max, edition_max, sections=len(SECTION_QUOTAS)) -> list[str]  # 空＝合法
layout_limits(settings=None) -> LayoutLimits
```

- 合法條件：`section_min >= 0`、`section_max >= 1`、`section_min <= section_max`、`edition_max >= 1` 且 `>= 版數 × section_min`。
- `layout_limits` 只在開關開啟時驗證，不合法丟 `ValueError`（訊息列出所有問題）；關閉時回傳 `enabled=False`，不影響現行流程。B1 只有設定與驗證，`run_mas` 還沒讀它（B2 起接上）。

### B2 分版主編決定各版篇數（`MAS_OPEN_LAYOUT`，desk-v3，預設關閉）

`daily/mas/orchestrator.py`：

```python
OPEN_PITCH_SYSTEM: str
OPEN_PITCH_SCHEMA = {"pitches": [{"story_id": int, "angle": str, "priority": "front"|"section", "reason": str}]}
section_pool(stories, evidence_of, section) -> list[Story]     # 本版有證據、kind 合規，依 (kind, -score, id) 取 SECTION_QUOTAS×DESK_POOL_PER_SECTION
guard_open_pitches(section, proposed, pool, fallback, limits, log) -> (list[Pitch], {story_id: reason})
_section_pitches(..., calls=None, reasons_out=None, layout_log=None)
MasResult.layout_log: list[str]   # 護欄動作紀錄；關閉時為空
```

- 開啟時每版一次請求，user＝`{"section", "min", "max", "candidates": [{"story_id", "kind", "score", "title", "default", ...rich_fields}], "global_top10"}`；`default=true` 是 `select_articles` 預選的稿；`MAS_RICH_CONTEXT` 也開時候選多帶 A1 三欄。
- 護欄（`guard_open_pitches`）：回應失敗或格式錯（`pitches` 不是 list）→ 該版退回 `select_articles` 的結果；只收候選池內、不重複的 integer `story_id`；`front` 只給 report；超過 `MAS_SECTION_MAX` 依回傳順序截斷；少於 `MAS_SECTION_MIN` 依候選池順序補（理由「程式補足下限」）。每個動作寫進 `MasResult.layout_log`。HOLD 規則照舊（HOLD 稿不進 page plan）。
- `PITCH` 訊息 payload 開啟時多 `reason`（主編寫的理由）；關閉時仍是 `section, angle, priority`。
- 設定不合法（`layout_limits` 丟 `ValueError`）→ 記 WARNING 與 `layout_log`，本期用固定名額，不中斷出刊。
- 全期上限 `MAS_EDITION_MAX` 在 B3 才套用；B2 單獨開啟時全期最多 3 × `MAS_SECTION_MAX` 篇。

### B3 超過全期上限時總編刪稿（`MAS_OPEN_LAYOUT`，desk-v3，預設關閉）

`daily/mas/orchestrator.py`：

```python
TRIM_SUFFIX: str                      # 接在 EIC_SYSTEM 後面
TRIM_SCHEMA = {"dropped": [{"story_id": int, "why": str}]}
program_trim(pitches, scores, limits, count, keep_per_section=None) -> list[int]   # 低分先刪（同分刪後面的），每版留 section_min
guard_trim(proposed, pitches, scores, limits, count, log) -> (list[int], {story_id: why}, by)   # by: eic|program|mixed
_trim_edition(session, *, edition_date, pitches, stories, evidence_of, reasons, client, clock, result) -> list[Pitch]
```

- 時機：`run_mas` 自動提案（`pitches is None`）時，PITCH 訊息全部發出之後、記者審稿之前。關閉、設定不合法、或三版不重複 story 數 ≤ `MAS_EDITION_MAX` → 原樣回傳，不呼叫模型、不發訊息。
- 請求：總編一次，system＝`EIC_SYSTEM + TRIM_SUFFIX`，user＝`{"edition_max", "must_drop", "section_min", "stories": [{"story_id", "section", "score", "title", "angle", "priority", "reason", ...rich_fields}]}`（`MAS_RICH_CONTEXT` 也開時帶 A1 三欄）。
- 護欄（`guard_trim`）：只收本期名單內、不重複、刪了不會讓該版低於 `MAS_SECTION_MIN` 的稿；超過 `must_drop` 的忽略；不足（含失敗、格式錯）由 `program_trim` 依分數補。動作寫進 `MasResult.layout_log`。
- 訊息：`eic → section_editor` 的 `DECISION`，payload＝`{"action": "TRIM", "by", "edition_max", "before", "after", "dropped": [{"story_id", "section", "why"}], "why"}`；`by="program"` 時 `llm_call_id` 為 null。被刪稿的 `PITCH` 訊息保留，只是不進審稿與 page plan。
- 多一則訊息計入 `MAX_MESSAGES`（未改上限）。

### B4 每版 0–`MAS_SECTION_MAX` 篇的排版（`MAS_OPEN_LAYOUT`，desk-v3，預設關閉）

不改介面，只用測試釘住現有行為（`tests/test_desk_v3.py`）：

- `slots_from_pitches`、`build_edition_view`、`render_html`、`telegram_digest` 都照 page plan 的實際篇數排，沒有寫死 4 篇。某版 0 篇時 page plan 沒有該版的 key，HTML 顯示「本版今日無新稿。」，Telegram 各版列不列該版。
- 頭版仍由 `slots_from_pitches`（`FRONT_CAPACITY=6`）與 T1／T3 決定；`FRONT_PAGE_SIZE`／`FRONT_PAGE_PER_SECTION` 只用在 P 組的 `select_articles`。
- P 組（`prepare_daily(mode="pipeline")`）不讀 `layout_limits`：`MAS_OPEN_LAYOUT`、`MAS_RICH_CONTEXT` 全開、`MAS_EDITION_MAX=3` 時結果與預設相同。

### C1 刪稿申訴（`MAS_MORE_INTERACTION`，desk-v3，預設關閉）

設定鍵 `MAS_MORE_INTERACTION`（`config.Settings.mas_more_interaction`，預設 false）。C1 只在 B3 真的刪了稿時才作用（所以也要 `MAS_OPEN_LAYOUT`）。`protocol.ALLOWED` 加 `("section_editor", "APPEAL")`。

`daily/mas/orchestrator.py`：

```python
APPEAL_SYSTEM: str
APPEAL_SCHEMA = {"appeal": bool, "story_id": int | None, "why": str}
APPEAL_RULING_SUFFIX: str             # 接在 EIC_SYSTEM 後面
APPEAL_RULING_SCHEMA = {"verdict": "UPHOLD"|"REVERSE", "swap_out": int | None, "why": str}
appeal_section(pitches, gone) -> str | None          # 被刪最多的版，同數取 SECTIONS 順序在前
guard_appeal_ruling(ruling, appealed, appeal_from, pitches, gone, limits) -> (verdict, swap_out, 不採用原因 | None)
_appeal_trim(session, *, edition_date, pitches, cards, gone, why, limits, trim_message, client, clock, result) -> set[int]
```

- 流程（最多 1 輪）：B3 的 TRIM `DECISION` 之後，被刪最多的那版主編收到 `{"section", "dropped": [卡片＋eic_why], "kept": [卡片]}`（卡片同 B3 `stories`）。`appeal=true` 且 `story_id` 在 `dropped` 內才發 `section_editor → eic` 的 `APPEAL`（payload `{"section", "why", "trim_message_id"}`）；否則不發訊息，只記 `layout_log`。
- 總編裁決請求 user＝`{"section_min", "appeal": {"story", "why", "eic_why"}, "kept": [卡片]}`，回 `eic → section_editor` 的 `DECISION`，payload＝`{"action": "APPEAL_RULING", "verdict", "story_id", "swap_out", "appeal_message_id", "why", ["program_reason"]}`。
- 護欄：`REVERSE` 只在 `swap_out` 是目前保留、不是被申訴稿、換掉後該版不低於 `MAS_SECTION_MIN` 時成立（全期篇數不變）；回應失敗或不合規則一律當 `UPHOLD`，原因寫 `program_reason`。
- 新訊息照常計入 `MAX_MESSAGES`；關閉時不發請求、不發訊息。

### C2 版面異議要有總編回應（`MAS_MORE_INTERACTION`，desk-v3，預設關閉）

同一個開關 `MAS_MORE_INTERACTION`，只在自動模式（`run_mas` 沒傳 `pitches`）作用，不需要 `MAS_OPEN_LAYOUT`。沒有新訊息類型（`PAGE_OBJECTION`、`DECISION` 本來就在白名單）。

`daily/mas/orchestrator.py`：

```python
PAGE_REVIEW_SYSTEM: str
PAGE_REVIEW_SCHEMA = {"action": "OK"|"OBJECT", "problem": str, "detail": str,
                      "lead": int | None, "second": [int], "briefs": [int]}
PAGE_RULING_SUFFIX: str               # 接在 EIC_SYSTEM 後面
PAGE_RULING_SCHEMA = {"verdict": "ACCEPT"|"REJECT", "why": str}
guard_page_proposal(review, plan_slots, eligible, hold_ids) -> (_Decision | None, 不採用原因 | None)
_page_review(session, *, edition_date, client, clock, hold_ids, evidence_of, result) -> None
```

- 開啟時**不送**舊的頭版預審（`CHECKER_SCHEMA` 那次版面編輯呼叫與它的 `PAGE_OBJECTION`），改在 T1／T3 排定頭版之後、縮主稿之前審一次（最多 1 輪）。T3 程式發的 `OVER_CAPACITY／LAYOUT_REVIEW` 異議照舊。
- 版面編輯請求 user＝`{"capacity", "front": [_story_card＋slot], "others": [_story_card], "section_counts": {版: 篇數}}`；`others`＝最新 page plan 各版裡、不在頭版、`kind=report`、非 HOLD、證據沒有注入標記的稿。
- 回 `OK` 或無法解析 → 不發訊息，只記 `layout_log`。回 `OBJECT` → 發 `layout_editor → eic` 的 `PAGE_OBJECTION`，payload＝`{"page": "front", "problem", "detail", "proposal": {"lead", "second", "briefs"}, "plan_id"}`。
- 提案護欄（`guard_page_proposal`）：頭版規則（`_decision_problems`：有主稿、不重複、≤ `FRONT_CAPACITY`、無 HOLD）、`second` ≤ 4、只用 `front`∪`others`、篇數不比現在少、跟現在不同、不能把兩個版都有位置（T1 連結）的稿撤下頭版。不合規則 → 不問總編，程式代發 `eic → layout_editor` 的 `DECISION`（`verdict=REJECT`、`by=program`、`program_reason`、`llm_call_id=null`）。
- 合規則 → 總編請求 user＝`{"objection": {"problem", "detail"}, "current_front": [卡片＋slot], "proposed_front": [卡片＋slot]}`，回 `eic → layout_editor` 的 `DECISION`，payload＝`{"action": "PAGE_RULING", "objection_message_id", "proposal", "verdict", "by": "eic"|"program", "why", ["program_reason"]}`。總編回應失敗當 `REJECT`（`by=program`）。
- `ACCEPT` → `apply_decision(..., min_front=現在頭版篇數)` 寫下一版 page plan（`decided_by_message_id`＝這則 DECISION）；仍不合規則時訊息標 `rejected`、版面不變。`REJECT` → 訊息 `handled`、版面不變。
- 最多多 2 則訊息、2 次呼叫，計入 `MAX_MESSAGES`／額度；額度用完時 `_ask` 回 None＝當沒有異議。關閉時請求逐字不變。

### C3 總編退稿（`MAS_MORE_INTERACTION`，desk-v3，預設關閉）

同一個開關，自動模式才作用；接在 C2 `_page_review` 之後、`_maybe_shorten_lead` 之前。沒有新訊息類型（`("eic", "REQUEST_REVISION")`、`("reporter", "REVISION_DONE"|"REBUT")` 本來就在白名單）。

`daily/mas/orchestrator.py`：

```python
EIC_REVISION_MAX = 2
EIC_REQUEST_DETAIL_CHARS = 200
EIC_REVIEW_SUFFIX: str                # 接在 EIC_SYSTEM 後面
EIC_REVIEW_SCHEMA = {"requests": [{"story_id": int, "detail": str}]}
guard_eic_requests(proposed, reviewable, limit=EIC_REVISION_MAX) -> list[(story_id, detail)]
_eic_revisions(session, *, edition_date, client, clock, hold_ids, evidence_of, result) -> None
```

- 總編請求 user＝`{"max": 2, "front": [{"story_id", "headline", "deck", "summary"}]}`；只列最新 page plan 頭版裡 `status=checked`、非 HOLD 的稿；`summary`＝`rich_fields` 的 S1 摘要（200 字、有注入標記給空字串），不看 `MAS_RICH_CONTEXT`。記者已降級或額度用完時整段跳過。
- 護欄：只收 `front` 裡、不重複、`detail` 非空（截 200 字）的前 2 篇；回應無效＝不退稿（不發訊息）。
- 每篇：`eic → reporter` 的 `REQUEST_REVISION`（`target_version`＝原版、`correlation_id`＝`ER-YYYYMMDD-NNN`、payload `{"detail", "by": "eic"}`）→ 記者請求（`REPORTER_SYSTEM`＋`DRAFT_SCHEMA`，user 含要求、原稿標題／導言／正文、證據塊）。
  - `REVISE` 且有標題、正文 → 寫新版（`caused_by_message_id`＝退稿訊息、`source_ids` 不變、`status=draft`），發 `reporter → eic` 的 `REVISION_DONE`（`{"new_version", "change"}`），再走原查核流程 `_check_and_maybe_revise`（同一個 `ER-` correlation_id；可能 CHALLENGE／RELEASE／HOLD）。
  - `REBUT` → 發 `reporter → eic` 的 `REBUT`（`{"reason", "target_version"}`），原稿不動。回應無效 → 原稿不動，只記 `layout_log`。
- 修稿重驗後變 HOLD 的稿不改 page plan，跟其他 HOLD 稿一樣由發佈前的人工核可擋下。
- 最多 1 次總編呼叫＋每篇 1 次記者呼叫（＋查核流程）；訊息計入 `MAX_MESSAGES`。關閉時請求逐字不變。

### C4 回放與 trace 顯示新訊息（desk-v3）

純顯示，沒有開關（舊資料沒有這些訊息，輸出不變）。

- `daily/replay.py`：`TYPE_LABELS` 加 `"APPEAL": "申訴"`；`PITCH_DECISIONS = ("TRIM", "APPEAL_RULING")`；`_desk_decision_text(payload, titles) -> str` 依 `payload.action` 產生 TRIM／APPEAL_RULING／PAGE_RULING 的說明（有 `program_reason` 時附在後面）。沒有 `action` 的舊 DECISION 文字不變。
- beat：`APPEAL` 與 TRIM／APPEAL_RULING 的 `DECISION` 放 `phase="pitch"`（`APPEAL` `walk=true`）；PAGE_RULING 照舊 `layout`。APPEAL_RULING 的 `to` 用 `appeal_message_id` 找回申訴的版（`section_<版>`）。TRIM 的 `detail.dropped` 沿用既有欄位。
- `daily/newsroom_page.py`：`TYPE_LABELS` 加 `"APPEAL": "申訴"`。測試保證 `protocol.ALLOWED` 的每種類型在兩邊都有中文標籤。
- `format_trace` 本來就逐則印 type 與 payload，不用改；3D 編輯室（`office.html`）沒有訊息類型白名單，照 beat 播放，不用改。

### D2 文章全文抓取（`FULLTEXT_ENABLED`，desk-v3，預設關閉）

設計見 `docs/pr/desk-v3.md`「D 階段設計」。**沒有接上收集排程**；開關開著也只有呼叫 `fetch_pending` 才會抓。

- 模組 `reddit_tracker/collection/fulltext.py`：
  - `extract(html: str) -> str`：標準庫 `html.parser` 抽正文（`<article>` → `<main>` → 全頁；只收 `p/h2/h3/li/blockquote`，略過 `script/style/nav/header/footer/aside/form/iframe/...`），經 `sanitize_text`（去零寬／控制字元，`<<<`／`>>>` 改全形）。`EXTRACTOR = "stdlib-html/1"`。
  - `HttpResponse(status_code, url, headers, body)`；`Getter = Callable[[str], HttpResponse]`（單次請求、不跟 redirect）。正式用 `requests_getter()`（timeout 10 秒、回應上限 2 MB）；測試一律注入假 getter。
  - `RobotsCache(get).allowed(url) -> bool`：每個 origin 讀一次；4xx 允許，5xx／網路錯誤不允許。
  - `fetch_fulltext(url, *, get, robots, allowed_domains, skip_domains=frozenset(), min_chars=200, store_max_chars=20000) -> FetchResult(status, http_status, final_url, text, error)`：不丟例外；redirect 手動跟最多 3 次，每跳都要在登錄表網域。
  - `fetch_pending(session, item_ids, *, allowed_domains, get=None, clock, sleep, now, settings=None) -> list[ItemFulltext]`：開關關閉回 `[]`；表裡已有的素材跳過（每篇只抓一次），同網域間隔、單次上限照設定；只 `flush`，呼叫端 commit。`allowed_domains` 用 `daily/mas/orchestrator.registry_domains(registry)`。
  - `fulltext_of(session, item_ids) -> dict[int, str]`：只回 `status=ok` 的全文（D3 用）。
- 新表 `item_fulltext`（Alembic `c5e1a9d3f207`，接 `b8d4f0a17c33`；downgrade = drop table，不改 `source_items`）：`item_id`（PK，FK `source_items.id`）、`status`（`ok|robots_denied|paywalled|too_short|http_error|non_html|blocked_domain|error`）、`http_status`、`final_url`、`text`（只有 ok 有值）、`text_chars`、`content_sha1`、`extractor`、`fetched_at`、`error`。
- 設定鍵：`FULLTEXT_ENABLED`（false）、`FULLTEXT_DOMAIN_INTERVAL_SECONDS`（5）、`FULLTEXT_MAX_PER_RUN`（60）、`FULLTEXT_MIN_CHARS`（200，短於此標 `too_short`）、`FULLTEXT_STORE_MAX_CHARS`（20000）、`FULLTEXT_SKIP_DOMAINS`（逗號分隔可註冊網域，一律當 `paywalled`）。HTTP 401/402/403 也標 `paywalled`，不嘗試繞過。

### D3 記者、查核員看全文（`MAS_REPORTER_FULLTEXT`，desk-v3，預設關閉）

只讀 `item_fulltext`（D2），不會觸發抓取。關閉時證據塊、數字檢查文字與請求逐字不變（`tests/test_desk_v3.py` 比對有無全文列時的記者請求）。

- 設定鍵：`MAS_REPORTER_FULLTEXT`（false）、`MAS_REPORTER_FULLTEXT_CHARS`（2000，每篇進提示的上限）。
- `daily/evidence.py`：
  - `FulltextEvidenceItem(EvidenceItem)`：多一欄 `fulltext: str | None`。刻意用子類別：實驗二用 `asdict(EvidenceItem)` 寫案例檔，基底類別欄位不變。
  - `with_fulltext(items, texts: dict[int, str], max_chars) -> list[EvidenceItem]`：有全文的列換成子類別（簡轉繁、截長），沒有的原物件保留。
- `daily/mas/orchestrator.py`：
  - `_attach_fulltext(session, items)`：開關開時用 `fulltext_of` 換上全文；`run_mas` 建 `evidence_of` 時與文稿編輯異議重建證據時呼叫。
  - `_evidence_block`：該篇有可用全文時第三行是 `全文：…`，否則照舊 `摘要：…`。
  - `_evidence_text`：查核數字檢查用的證據文字，有可用全文時接在 `標題 摘要` 後面。
  - `evidence_has_injection` 也掃 `fulltext`；全文含注入標記時，整包照現有規則視為有注入（不上頭版、主編／總編摘要給空），且該篇提示退回摘要（`_usable_fulltext` 回 None）。
- P 組（`writer.py`）與實驗二（`eval/exp2.py`）不受影響。
