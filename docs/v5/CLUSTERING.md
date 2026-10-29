# 事件聚合規格（v2.0 綜合日報）

把「不同媒體報導同一件事」的 `source_items` 合成一個 `story_clusters` 事件，並由程式算出之後評分要用的訊號（企劃 5.1 步驟 3–4）。收集層的完全重複（同網址、同標題）已由 [COLLECTION.md](COLLECTION.md) 處理；這裡處理的是「不同標題、不同媒體、同一事件」。

## 方法

程式計算、不用 LLM：每篇素材做成 TF-IDF 向量，用餘弦相似度把新素材併入最相近的既有事件。理由：

- 每天數千篇，LLM 逐篇比對太貴，也受 Gemini 免費額度限制。
- 結果可重現、可解釋（看得到兩篇共同的關鍵詞與分數），符合「數字由程式產生」的原則。
- 本地 embedding 模型要拉進 PyTorch 等大型依賴，目前不值得。

### 文字前處理

| 步驟 | 規則 |
| --- | --- |
| 輸入 | 標題重複兩次（加權）＋摘要前 300 字 |
| 去樣板 | 移除網址、通訊社電頭與圖說（「（中央社記者…電）」「中央社記者某某攝」）、日期（「115年10月26日」）；聚合 feed 摘要樣板字（article、url、comments、points）列為停用詞 |
| 簡轉繁 | `lang == "zh"`（簡體來源）先用 `zhconv` 轉為 `zh-tw`，讓 DW、RFI、聯合早報能和台灣媒體比對 |
| 中文 | 連續中日韓字元切成字元 bigram |
| 英文 | 小寫單字，去掉停用詞與 2 字以下的字 |
| 數字 | 3 位數以上的數字保留為 token（金額、年份、編號常是辨識事件的關鍵） |
| 語言群組 | `zh`／`zh-Hant` 為 `zh`，其他依原 `lang`；**只在同一語言群組內聚合** |

### 指派規則（增量、不重排既有事件）

每次執行：

1. 讀入「時間窗」內的唯一素材（`duplicate_of_id IS NULL`、`published_at` 在最近 72 小時），以這批素材計算 IDF。
2. 依 `published_at` 由舊到新處理尚未分配事件的素材：
   - 找出同語言群組、發布時間相差 48 小時內、且至少共用一個 token 的已分配素材。
   - 由相似度最高的開始，逐一檢查（2026-10-29 起，手冊步驟 3）：分數過**兩段門檻**、標題有足夠的**共同實體**（見下節），**而且**與該事件全體成員向量和的相似度 ≥ `CENTROID_MIN`，就併入它的事件；都不符合就自成新事件。最後一個條件防止「A 像 B、B 像 C」一路串錯。原則：不確定就不要合併。
3. 重複素材（`duplicate_of_id` 非 null）直接沿用根素材的事件。
4. 重算有變動事件的彙總欄位。

既有素材的事件歸屬一旦決定就不再改變，讓下游（選題、文章）引用的事件 id 保持穩定。代價是兩個事件之後出現「橋接」素材時不會自動合併；這留給編輯層處理。

門檻在實際資料上抽查後決定，數值與抽查紀錄寫在本文件末。

## 共同實體與兩段門檻（2026-10-29，手冊步驟 3 第 1–2 點）

只看相似度的話，標題共用一個字就會合併（E03 的「Block」把語音模型和瑞士地圖併在一起、E04 的「buyouts」把微軟和 Skydance 併在一起）。所以合併前還要兩篇**標題**有共同的人名、地名、組織名或數字（`collection/entities.py`）：

| 語言 | 算實體的 | 不算的 |
| --- | --- | --- |
| 全部 | 譯名表（`seeds/name_glossary.yaml`）命中的名字，先統一成中文標準譯名（Lula、露拉 → 魯拉）；3 位數以上的數字（去千分位） | 1900–2100 的年份 |
| 英文 | 句中大寫開頭的字；大小寫混合的字（iPhone、SpaceX）；句首字只有在當天其他標題句中也大寫、而且當天從沒以小寫出現時才算（「Anthropic files for IPO…」） | 句首字、常見字清單（`seeds/entity_common_words.yaml`：Block、Apple、New、月份、職稱、太常見的國名…）；**整個標題都是 Title Case 時只認譯名表** |
| 中文 | 譯名表名字；兩篇都有、≥3 字、在「當天素材」標題中出現率 < 5% 的片段（只有這兩篇有的片段一定算）。中文標題裡的英文字（SpaceX）也算 | 3 字以下、常見的片段（每篇都有的「選戰」樣板） |

「當天素材」＝這次聚合時間窗內的素材標題；共同片段取連續覆蓋的最長段，每段算一個實體。

兩段門檻（設定值，`config.Settings`；實驗一凍結）：

| 相似度 | 合併條件 | 設定 |
| --- | --- | --- |
| ≥ 0.45 | ≥ 1 個共同實體 | `CLUSTER_HIGH_THRESHOLD`、`CLUSTER_HIGH_MIN_ENTITIES` |
| 0.28–0.45 | ≥ 2 個共同實體 | `CLUSTER_LOW_THRESHOLD`、`CLUSTER_MID_MIN_ENTITIES` |
| < 0.28 | 不合併 | |

`ClusterRunStats.rejected_no_entity` 記錄「相似度夠但共同實體不足」而沒併入的次數。代價是同一事件被拆開的情況變多（10/27 重編：2,539 → 2,822 個事件，≥2 家出處 264 → 220），特別是英文 Title Case 標題與只共有一個名字的中段配對；漏合併頂多多一篇稿，錯合併會刊出錯誤。11/07 拿到 dev 標註後重調。

### 譯名表 `seeds/name_glossary.yaml`

撰稿與合併共用。每筆 `{en: [英文寫法], zh: 中央社標準譯名, also: [其他中文譯名]}`；比對不分大小寫、忽略重音（Vučić＝Vucic），簡體先轉繁體，最長的寫法優先（「小波索納洛」→ 佛拉維歐）。30–50 筆，只收 2026-10-30 以前在素材出現過的名字（實驗一防偷看，`tests/test_entities.py` 用母本驗證），刻意不收美國、中國這類每篇國際新聞都有的國名。

## 出處（outlet）與獨立來源數

「獨立來源數」以**出處**計算，不以登錄表的 feed 計算（自由時報政治版與地方版是同一家媒體）：

- 出處 = `canonical_url` 的可註冊網域（`news.ltn.com.tw` → `ltn.com.tw`；`.com.tw`、`.org.tw`、`.gov.tw`、`.co.uk` 等取三段）。
- 轉載通訊社稿：摘要或標題含「中央社記者」「（中央社」者，出處視為 `cna.com.tw`。其他通訊社（路透、美聯）的轉載辨識留待之後補強。
- 社群來源（T4）計入 `item_count`，**不計入** `outlet_count`。

## 資料表

### `story_clusters`（新表）

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | int PK | |
| `lang_group` | str(8) | `zh`、`en` 等 |
| `section` | str(32), index | 成員中 T1／T2 最常見的板塊；登錄表標為 `general_feed` 的綜合 feed 不參與投票；沒有可投票成員時依序退回全部非綜合成員、全部成員 |
| `title` | text | 代表標題：層級最高（T1 > T2 > T3 > T4）中最早發布的那篇 |
| `representative_item_id` | int | 代表素材的 `source_items.id`（不加 FK，避免與 `source_items.cluster_id` 形成循環） |
| `item_count` | int | 成員素材數（含重複） |
| `outlet_count` | int | 非社群的獨立出處數 |
| `t1_count` / `t2_count` / `t4_count` | int | 各層級成員數 |
| `first_published_at` / `last_published_at` | datetime(tz), index | |
| `created_at` / `updated_at` | datetime(tz) | |

### `source_items` 新增欄位

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `cluster_id` | FK → `story_clusters.id`, nullable, index | null 表示尚未聚合（例如超出時間窗的舊稿） |

## 介面

```python
# reddit_tracker/collection/clustering.py
tokenize(text: str, lang: str) -> list[str]
lang_group(lang: str | None) -> str
outlet_of(canonical_url: str, title: str | None, summary: str | None) -> str
cluster_recent_items(session, *, now=None, rules: MergeRules | None = None,
                     lexicon: EntityLexicon | None = None,
                     general_sources: frozenset[str] = frozenset(),
                     disabled_sources: frozenset[str] = frozenset()) -> ClusterRunStats
# rules／lexicon 預設取設定值與 seeds 檔；disabled_sources：已停用來源的素材不進聚合，既有事件的訊號也不算它們
SourceRegistry.disabled_source_ids() -> frozenset[str]

# reddit_tracker/collection/entities.py
MergeRules(high_threshold=0.45, low_threshold=0.28, high_min_entities=1, mid_min_entities=2,
           cross_lang_min_entities=2, llm_merge_min_entities=1)
MergeRules.from_settings(settings=None) -> MergeRules
MergeRules.required_entities(score) -> int | None      # None：不合併
load_lexicon(glossary_path=None, common_words_path=None) -> EntityLexicon   # 預設路徑來自設定
EntityLexicon.entities(title, is_zh) -> TitleEntities  # names、cjk、trigrams、leads、proper、lower
EntityLexicon.shared(a, b, context: EntityContext | None) -> set[str]
EntityLexicon.glossary_names(text) -> list[str]        # 標準中文譯名
EntityLexicon.glossary_entries(text) -> list[GlossaryEntry]
EntityContext(titles: Iterable[TitleEntities])          # 當天素材：片段出現率、句首字佐證
```

CLI：

```bash
uv run python -m reddit_tracker.collection cluster            # 聚合時間窗內未分配的素材
uv run python -m reddit_tracker.collection clusters [--top 30] # 列出最多出處的事件，供抽查
```

排程：`newsroom_source_collection` 每次收集完立即執行 `cluster_recent_items`。

## 已知限制

- 跨語言（中文報導與英文報導同一事件）不在聚合合併；由日報編輯會議用「譯名表＋共同實體」合併（見 DAILY_EDITION.md）。
- 標題很短、摘要很空的素材（PTT、Product Hunt）容易自成一個事件，這是預期行為：社群與工具類素材本來就多半是單篇。
- 72 小時時間窗之前的舊稿（首日回補的央行、arXiv 舊稿）不聚合，`cluster_id` 維持 null。

## 門檻與抽查紀錄（2026-10-26，production DB 複本，72 小時窗 2,436 篇唯一素材）

| 參數 | 值 | 依據 |
| --- | --- | --- |
| `CLUSTER_THRESHOLD`（2026-10-29 起為 `CLUSTER_LOW_THRESHOLD`，另加共同實體條件） | 0.28 | 依分數區間抽樣不同出處的最相似配對：0.20–0.25 約半數是不同事件（兩則不同的伊波拉新聞、沙烏地兩則不同外交新聞）；0.25–0.30 約 7/8 為同一事件（SpaceX 買輝達晶片、五中全會、美軍攻伊朗計畫），錯的是 NFL 第 8 週賠率對到第 7 週照片；0.30 以上幾乎都正確 |
| `CENTROID_MIN` | 0.20 | 防止單一連結一路串錯 |
| `CANDIDATE_MAX_DF_RATIO` / `CANDIDATE_MIN_DF_CAP` | 5% / 50 | 候選搜尋只用不常見 token；下限避免小資料量時找不到候選 |

結果：2,009 個事件，其中 176 個有 2 家以上出處、58 個有 3 家以上；耗時約 1 秒；立即重跑無任何變動。

抽查最大的事件皆正確：巴西大選（19 篇、10 家出處，中英文各自成一個事件）、塞爾維亞大選（英文 7 家、中文 7 家，含簡體來源）、委內瑞拉馬查多返國、蔣萬安競總成立、五中全會、金鐘獎。

抽查中修正的問題：

- hnrss 摘要樣板（Article URL、Comments URL、Points）使無關文章互相相似 → 去網址並將樣板字列為停用詞。
- 中央社電頭與圖說 → 斷詞前移除。
- 綜合 feed（央廣、中央社聚焦、公視）讓國際事件被歸到台灣版 → 登錄表 `general_feed` 不參與板塊投票。
- 「蘇清泉／周春米」與「沈伯洋女力後援會」被併在一起：查證後是周春米在女力後援會現場回應蘇清泉，屬同一場合，合併合理。
