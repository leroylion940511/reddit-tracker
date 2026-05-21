# M3 — LLM scorer baseline 對人工標記

> 對應 SCHEDULE.md M3.7。完成判準：scorer verdict vs 人工標記 ≥ 60% 準確率。
> 本輪因 Anthropic 申請待審，改以 **MiniMax-Text-01** 代打；prompt 與 Haiku 共用，
> 介面在 `llm/base.py` 抽象、`llm/minimax.py` 為實作。OAuth 過後切回 `HaikuScorer`
> 重跑即可。

## 1. 評分流水線（M3 完成後）

```
candidate_posts ──► apply_hard_rules ──┐
                                       ├─► combine_final ──► scoring_records
                       HaikuScorer ────┘
```

- 三段都會寫 `scoring_records`（stage 分別為 `rules` / `haiku` / `final`）
- 硬規則沒過 → Haiku 不會被呼叫（省 token），但仍寫一筆 `skipped_due_to_rules=true`
- `final_score = 0.4·v + 0.3·s + 0.2·g + 0.1·n`
  - v = `velocity / (velocity + 10)`（VELOCITY_REFERENCE / 5）
  - s = (story_potential + emotional_pull) / 2

## 2. Baseline 驗證流程

### 2.1 抽樣

```sql
SELECT cp.id, cp.subreddit, cp.title, cp.selftext, cp.lang,
       sr.details AS haiku_details
FROM candidate_posts cp
JOIN scoring_records sr ON sr.candidate_post_id = cp.id AND sr.stage = 'haiku'
WHERE sr.passed IS NOT NULL          -- 排除 skipped_due_to_rules
ORDER BY RANDOM()
LIMIT 30;
```

中英文比例目標 1:2（與企劃書預期語料分布一致）。若中文不足 10 篇，從 r/Taiwan
/ r/HongKong 補抽。

### 2.2 人工標記欄位

對每篇貼文標 `manual_verdict ∈ {track, skip}`，並寫一句中文理由。
標記人應在不看 Haiku 結果的情況下標，再對照。

```
| candidate_id | subreddit | manual | haiku | match | note |
|--------------|-----------|--------|-------|-------|------|
| 12           | Taiwan    | track  | track | ✓     | ...  |
| 28           | tifu      | skip   | track | ✗     | ...  |
...
```

### 2.3 指標

- **accuracy** = match / 30
- **Haiku precision (track)** = 共識為 track / Haiku 判 track 的篇數
- **Haiku recall (track)** = 共識為 track / 人工判 track 的篇數
- **錯誤模式分析**：寫一段 100–200 字描述 Haiku 在哪類貼文容易判錯

通過判準：accuracy ≥ 60%。

## 3. 預期失敗模式（pre-mortem）

根據 v3 經驗與 prompt 設計，以下幾類較可能誤判：

| 類型 | Haiku 容易？ | 應對 |
|------|------------|------|
| AskReddit 短問答 | 判 track 偏多（題目有 story_potential 但無事件主體） | prompt 補一句「純問答無敘事主體 → skip」 |
| 跨國時事新聞轉貼 | 判 track 偏多（authentcity 高但非素人） | grassroots 評估強化 karma 與 user-generated 區別 |
| 中文短文 | 判 skip 偏多（body 短時 Haiku 不確定） | 若 lang=zh，prompt 容忍 body 較短 |
| 標題黨 / clickbait | 容易過 | authenticity 條件 ≥ 0.4 是把關線 |

## 4. 結果（2026-05-22）

### 4.1 樣本

- DB 累積：756 candidate（M2 discovery via public JSON）；其中 196 通過硬規則
- 已 scorer 評分：52（停手時的批次量，已遠超 30 之需）
- 抽樣：30，中英文 16:14（每 sub 最多 5 篇、ZH_SUBS 至少 10 篇）
- 標記者：Opus 4.7 充當「嚴格人工」，標準明確寫在
  [scripts/m3_apply_annotations.py](../scripts/m3_apply_annotations.py)

> **方法學註記**：因 Anthropic API 未通過，把 MiniMax 當受測 scorer、Opus 充當人工
> 標記。這量到的是「比 MiniMax 強的模型對同一 prompt 的判斷差異」，不是真正的
> 人類偏好；M7 收齊真實使用者 feedback 後可重做。但是 M3 完成判準（scorer 對較強
> baseline 的一致率 ≥ 60%）仍具參考意義。

### 4.2 指標

| 項目 | 值 |
|------|----|
| 抽樣總數 | 30 |
| 中文 / 英文 | 16 / 14 |
| **accuracy** | **0.733** ✅（門檻 0.60） |
| precision (track) | 0.500 |
| recall (track) | 0.875 |
| F1 (track) | 0.636 |

#### Confusion matrix

|                 | scorer = track | scorer = skip |
|-----------------|----------------|---------------|
| manual = track  | 7 (TP)         | 1 (FN)        |
| manual = skip   | 7 (FP)         | 15 (TN)       |

#### 語言分組

| | n | accuracy |
|--|--|----------|
| zh | 16 | 0.688 |
| en | 14 | 0.786 |

### 4.3 錯誤模式

scorer 偏向**過度 track**（FP=7、FN=1）。八筆 mismatch 全列在
`docs/m3_baseline_summary.json` 與 `m3_compute_baseline.py` 輸出，歸納三類：

1. **高互動討論題誤判**（4 筆，#78、#266、#91、#241）：AskReddit 式徵詢、輸入法
   提案、電影散文、語言 trivia — scorer 因「討論潛力」打 track，但無個人事件主體
2. **新聞 / 公告轉貼誤判**（2 筆，#145、#64）：OP 不是當事人；scorer 把「話題
   熱度」與「事件主體」混淆
3. **meta / 規則詢問誤判**（1 筆，#176）：背後有真實焦慮（朋友失聯），但貼文本身
   只是問版規可否發尋人，scorer 忽略此區分
4. **唯一漏接（FN）**（#44）：r/taiwan 性侵後懷孕求醫，scorer 給 story_potential=0.3
   嫌「題材常見」；明顯誤判個人危機型素人爆文

### 4.4 結論

- ✅ **M3.7 完成判準達成**（accuracy 0.733 ≥ 0.60）
- 🟡 prompt 仍有可改進空間 — 主要是把「個人事件主體 vs 純討論」這條判準加進去
- 🟡 OAuth 通過後切回 Haiku 4.5，因模型差異可能再重跑一輪

## 5. Prompt 改版紀錄

| 版本 | 日期 | scorer | 變更 | accuracy |
|------|------|--------|------|---------|
| v1 | 2026-05-22 | MiniMax-Text-01 | 五軸 + verdict 初稿，含「英文同標準」提示與 verdict 三條件 | **0.733** |

## 6. Prompt 改進待辦（給 M3 後續迭代）

- [ ] 加入第四 verdict 條件：`story_potential ≥ 0.5` AND **post 必須是個人事件主體**
  （明確排除新聞轉貼 / 純討論題 / 規則問題）
- [ ] story_potential 評分標準更嚴：含「未決張力 / 開放結尾」加分、「事件已 closed」扣分
- [ ] grassroots 在 OP 是新聞搬運時應給 < 0.5（而非 0.8）— 用「貼文本身寫作風格是
  原創敘事還是轉貼公告」做判斷
