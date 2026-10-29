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
   - 取相似度最高的那篇；若分數 ≥ `CLUSTER_THRESHOLD`，**而且**與該事件全體成員向量和的相似度 ≥ `CENTROID_MIN`，併入它的事件；否則自成新事件。第二個條件防止「A 像 B、B 像 C」一路串錯。
3. 重複素材（`duplicate_of_id` 非 null）直接沿用根素材的事件。
4. 重算有變動事件的彙總欄位。

既有素材的事件歸屬一旦決定就不再改變，讓下游（選題、文章）引用的事件 id 保持穩定。代價是兩個事件之後出現「橋接」素材時不會自動合併；這留給編輯層處理。

門檻在實際資料上抽查後決定，數值與抽查紀錄寫在本文件末。

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
cluster_recent_items(session, *, now=None, threshold=CLUSTER_THRESHOLD,
                     general_sources: frozenset[str] = frozenset(),
                     disabled_sources: frozenset[str] = frozenset()) -> ClusterRunStats
# disabled_sources：已停用來源的素材不進聚合，既有事件的訊號也不算它們
SourceRegistry.disabled_source_ids() -> frozenset[str]
```

CLI：

```bash
uv run python -m reddit_tracker.collection cluster            # 聚合時間窗內未分配的素材
uv run python -m reddit_tracker.collection clusters [--top 30] # 列出最多出處的事件，供抽查
```

排程：`newsroom_source_collection` 每次收集完立即執行 `cluster_recent_items`。

## 已知限制

- 跨語言（中文報導與英文報導同一事件）不會合併；之後在選題階段由 LLM 對高分事件做跨語言連結。
- 標題很短、摘要很空的素材（PTT、Product Hunt）容易自成一個事件，這是預期行為：社群與工具類素材本來就多半是單篇。
- 72 小時時間窗之前的舊稿（首日回補的央行、arXiv 舊稿）不聚合，`cluster_id` 維持 null。

## 門檻與抽查紀錄（2026-10-26，production DB 複本，72 小時窗 2,436 篇唯一素材）

| 參數 | 值 | 依據 |
| --- | --- | --- |
| `CLUSTER_THRESHOLD` | 0.28 | 依分數區間抽樣不同出處的最相似配對：0.20–0.25 約半數是不同事件（兩則不同的伊波拉新聞、沙烏地兩則不同外交新聞）；0.25–0.30 約 7/8 為同一事件（SpaceX 買輝達晶片、五中全會、美軍攻伊朗計畫），錯的是 NFL 第 8 週賠率對到第 7 週照片；0.30 以上幾乎都正確 |
| `CENTROID_MIN` | 0.20 | 防止單一連結一路串錯 |
| `CANDIDATE_MAX_DF_RATIO` / `CANDIDATE_MIN_DF_CAP` | 5% / 50 | 候選搜尋只用不常見 token；下限避免小資料量時找不到候選 |

結果：2,009 個事件，其中 176 個有 2 家以上出處、58 個有 3 家以上；耗時約 1 秒；立即重跑無任何變動。

抽查最大的事件皆正確：巴西大選（19 篇、10 家出處，中英文各自成一個事件）、塞爾維亞大選（英文 7 家、中文 7 家，含簡體來源）、委內瑞拉馬查多返國、蔣萬安競總成立、五中全會、金鐘獎。

抽查中修正的問題：

- hnrss 摘要樣板（Article URL、Comments URL、Points）使無關文章互相相似 → 去網址並將樣板字列為停用詞。
- 中央社電頭與圖說 → 斷詞前移除。
- 綜合 feed（央廣、中央社聚焦、公視）讓國際事件被歸到台灣版 → 登錄表 `general_feed` 不參與板塊投票。
- 「蘇清泉／周春米」與「沈伯洋女力後援會」被併在一起：查證後是周春米在女力後援會現場回應蘇清泉，屬同一場合，合併合理。
