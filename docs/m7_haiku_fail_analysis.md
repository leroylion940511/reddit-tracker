# M7.6 Haiku-fail 模式分析（SCHEDULE 7.6 變體）

**日期**：2026-06-08
**樣本來源**：[m7_haiku_fail_samples.md](m7_haiku_fail_samples.md)
（5 中文 sub × 10 + 2 英文對照 sub × 5 = 60 筆 haiku verdict=skip）

> SCHEDULE 7.6 原本要分析「dislike / mute_author」樣本，但目前 dislike 只
> 累積 5 筆（要 OAuth 後 push 量提升才有料）。改用 scoring 視角的等價分析：
> 中文 sub haiku pass 15.1% vs 英文 35.3%（差 2.3×）— 找 prompt 失準模式。

---

## 1. 漏斗對比

| lang | n_sub | candidates | rules pass | haiku track | final pass |
|------|------:|-----------:|-----------:|------------:|-----------:|
| en   | 10    | 15,117     | 40.8%      | 35.3%       | 35.3%      |
| zh   | 5     | 2,626      | 38.5%      | **15.1%**   | 15.1%      |

`rules pass` 兩者接近（38–41%），瓶頸在 haiku：英文走過 rules 的有 86.5% 被 track，
中文只有 39.3%。

按 sub 拆：

| zh sub             | haiku pass | 真 haiku-skip 比例 |
|--------------------|-----------:|-------------------:|
| china_irl          | 20.7%      | 38.0%              |
| chineselanguage    | 11.5%      | 75.1%              |
| hongkong           | 11.0%      | 71.0%              |
| taiwan             | 12.1%      | 73.0%              |
| taipei             | 6.6%       | 83.8%              |

| en sub control     | haiku pass | 真 haiku-skip 比例 |
|--------------------|-----------:|-------------------:|
| amitheasshole      | 62.3%      | 4.1%               |
| offmychest         | 40.6%      | 21.4%              |
| relationship_advice| 45.8%      | 1.3%               |

---

## 2. 中文 haiku-skip 共同模式（觀察）

### 2.1 諮詢題大量被 skip（**合理判定，不是 prompt bug**）

`taipei` / `taiwan` / `hongkong` 樣本中 8/10 是「旅遊 / 購物 / 美食 / 簽證 /
醫療」諮詢類：

- [8087] Taipei & buying glasses
- [11491] Iang visa hongkong
- [12953] Yangmingshan hike
- [8062] Lactose free products and healthy cooking restaurants in Taipei?
- [13270] How fancy / expensive of a hotel should I stay in?

這些都是「個人需求 → 社群幫忙回答」型 — 本質**不是素人爆文題材**。Haiku skip 它們
正確。

**結論**：這部分 pass rate 差距是「中文 reddit 社群結構性差異」（地方 sub
偏問答平台），不是 prompt 失準。**不該動 prompt 去 force-pass 這類**。

### 2.2 議題討論型被低估（**真 false-negative，是 prompt 盲點**）

china_irl 樣本：

- [11842] 紀念六四：`emotional_pull=0.80, authenticity=0.90` 但
  `story_potential=0.30` → skip（reason：「敏感且缺乏後續展開潛力」）
- [167] 男人肛門快感討論：`novelty=0.60, grassroots=0.80`，但
  `story_potential=0.30` → skip
- [4117] 四三計劃證明中國能發展：`grassroots=0.80`，但
  `story_potential=0.30` → skip
- [8869, chineselanguage] 《中文新解｜裝乖》：`emotional_pull=0.70,
  authenticity=0.90` 但 `story_potential=0.30` → skip

這幾個的共同特徵：
- 議題型 / 文化反思型討論（典型「會被收藏」的素人爆文）
- emotional_pull 高、authenticity 高、grassroots 高
- 但 **story_potential 被打低**（< 0.5），因為 prompt 把 story_potential
  定義成「事件**繼續展開**」（後續更新 / 結局揭曉），不包含「議題引發持續
  討論」

**這是 prompt 的盲點**：story_potential 定義太窄，把「reflective / topical /
共鳴強的觀點貼」都篩掉。

### 2.3 互動數據為 0 → 推斷低 story_potential（**RSS source 副作用**）

多個 fail reason 明確提到「互動數據為零」「無 0 觀察」：

- [7242] 移民只看人均 GDP：「互動數據為零，難以判斷其傳播潛力」
- [14024] Interactive Chinese reading：「互動性不足導致情感吸引力較低」
- [167] 男人話題：「互動數據較差（0 分 0 評論），難以形成有吸引力的討論」

**根因**：

- 60% (10,741/17,743) candidate 在 DB 中 `initial_score=0` 或 `num_comments=0`
- 既是 RSS source 拿不到欄位的退化（Plan C 期間），也是 /new 端剛發佈的 post 本就 0
- `build_user_prompt` 把 `Score / Comments: 0 / 0` 餵給 Haiku
- Haiku 拿這當證據說「冷貼 → 不會傳播 → story_potential 低」

問題：discovery 抓的本來就是「剛發布、還沒互動」的新貼。`0/0` 是時間序起點，
不是「冷貼」的證據。prompt 沒提醒這件事。

---

## 3. 對英文對照組的觀察

AITA / offmychest 也有「story_potential 0.30 + 高 emotional_pull → skip」
的樣本（[10695] "I don't want to live anymore"），但比例低很多 — 因為英文
sub 內容類型本身就偏向「我做了 X，請大家評理」的衝突敘事，story_potential
基本盤高。

英文 fail 樣本中也有同樣 reason 「缺乏後續展開潛力」— 證明這個盲點不是
中文獨有，**只是中文 sub 命中率高得多**。

---

## 4. Retune 提案

**目標**：拉高議題型 / 反思型中文貼文的 pass rate，**不**動諮詢題 / 旅遊問答的
判定。

### 4.1 SYSTEM_PROMPT 擴展 story_potential 定義

加一段：

> story_potential 不只指「事件會繼續發生」，也包含「議題本身能引發持續討論
> 或共鳴回響」。當 emotional_pull ≥ 0.7 且 authenticity ≥ 0.6 時，貼文本身的
> 觀點 / 反思 / 議題即構成 story_potential，不要因為「沒有具體後續事件」就
> 給 < 0.4。

### 4.2 提醒 0 互動不可作為證據

加一段：

> 注意：candidate 來自 subreddit /new 端，**多數貼文在抓取當下 score 和
> num_comments 為 0**（剛發佈、尚未累積互動）。請不要把 `Score / Comments:
> 0 / 0` 當作「冷貼 / 沒人氣」的證據 — 這是時間序起點，不代表傳播潛力。
> 評分請依貼文內容本身判斷。

### 4.3 不動 verdict 門檻

維持 `track = avg ≥ 0.55 AND story_potential ≥ 0.5 AND authenticity ≥ 0.4`。
盲點修在 story_potential 的給分標準，不在 verdict 門檻 — 過度鬆綁會把英文 sub
打爆。

### 4.4 不動 build_user_prompt

繼續傳 score=0 / comments=0 給 Haiku，由 prompt 自己處理（透明度高，
也不需動 wiring）。

---

## 5. 後續驗證策略（M7.6 收尾）

由於 Anthropic API key 不一定常駐，本次 retune 暫採「fixture-based 確保
JSON schema 不破壞」策略。真實 A/B 評估留到下兩個觸發點：

1. **OAuth 通過後**：accumulate ≥ 50 dislike / mute_author 樣本後跑
   eval_dislike_features.py（新腳本），驗證 retune 是否確實提升 precision
2. **每週對帳**：跑 eval_lang_breakdown.py 觀察中文 pass rate 是否上升到 25%+
   且英文 pass rate 不下降

對應 [[project_m7_retune_backlog]] #1。
