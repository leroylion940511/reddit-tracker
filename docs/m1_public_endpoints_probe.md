# M1 Public Endpoints Probe Result

_Probe time: 2026-05-22 11:16:49 UTC_

## 樣本

從 ['tifu', 'AmItheAsshole', 'Taiwan'] 各取 hot 3 篇（按 num_comments 排序），共 6 個 post / 同數 author。

| sub | post_id | author | score | comments |
| --- | ------- | ------ | ----- | -------- |
| r/AmItheAsshole | 1tkc63r | u/Odd-Adhesiveness7714 | 1 | 128 |
| r/AmItheAsshole | 1tkck9s | u/WesternBeach6798 | 318 | 125 |
| r/AmItheAsshole | 1tkcdrv | u/SS-9000ultra | 140 | 103 |
| r/taiwan | 1tju86z | u/ProperProperer | 118 | 107 |
| r/taiwan | 1tk8mwm | u/BoringDreamGuy | 0 | 62 |
| r/taiwan | 1tjsj3u | u/random_agency | 0 | 53 |

## 統計

| endpoint | attempts | success | parse_ok | success_rate | 狀態分布 |
| -------- | -------- | ------- | -------- | ------------ | -------- |
| user_about | 6 | 5 | 5 | 83% | 200=5, 403=1 |
| user_submitted | 6 | 6 | 6 | 100% | 200=6 |
| duplicates | 6 | 6 | 6 | 100% | 200=6 |
| comments | 6 | 6 | 6 | 100% | 200=6 |

## 樣本輸出

### user_about
- u/WesternBeach6798 link_karma=90 comment_karma=21 created_utc=1713701995.0
- u/SS-9000ultra link_karma=53 comment_karma=-100 created_utc=1779429506.0

### user_submitted
- u/Odd-Adhesiveness7714 got 2 subs, top='AITA for smoking on my balcony?'
- u/WesternBeach6798 got 1 subs, top='AITAH for telling my late fiancés family that they can’t be in my kids lives'

### duplicates
- r/AmItheAsshole/1tkc63r → 0 dups (200 但空)
- r/AmItheAsshole/1tkck9s → 0 dups (200 但空)
- r/AmItheAsshole/1tkcdrv → 0 dups (200 但空)

### comments
- r/AmItheAsshole/1tkc63r top=47 total=122 MoreComments=0
- r/AmItheAsshole/1tkck9s top=33 total=122 MoreComments=0
- r/AmItheAsshole/1tkcdrv top=58 total=97 MoreComments=0

## 補充驗證：duplicates 在「有 crossposts」的樣本

第一輪 6/6 都回空集合是因為樣本都是 r/new 的新貼文（幾小時內、還沒人 crosspost），不是 endpoint 失效。重抓「`num_crossposts > 0` 的樣本」再驗：

| post_id | sub | num_crossposts | duplicates 回 | 狀態 |
| ------- | --- | -------------- | -------------- | ---- |
| 1tgqct1 | AmItheAsshole | 3 | — | **403 Blocked** |
| 1th3sdp | AmItheAsshole | 2 | 2 | 200 ✅ |
| 1tij3co | AmItheAsshole | 1 | 1 | 200 ✅ |

結論：**duplicates 在 public path 下基本可用**，回的 count 與 `num_crossposts` 一致；偶有 403（單樣本不足以歸因，疑似 NSFW / quarantine 旗標）。M5 crosspost 偵測可以走 public，但需要 retry / 容忍部分樣本 403。

## 額外發現（不在原 P1 範圍但影響 discovery）

跑這輪 probe 時順手測了 `search` 路徑，發現：

- `https://www.reddit.com/search.json`（all-reddit search） → **403 Blocked**
- `https://www.reddit.com/r/tifu/search.json?restrict_sr=on` → **403 Blocked**
- `https://www.reddit.com/r/AmItheAsshole/search.json?restrict_sr=on` → 200 ✅

代表 `services/discovery.py::discover_from_keywords` 走 `subreddit="all"` 路徑會全部 403，這也解釋了 PROGRESS.md「M2.13 連續 24h」沒跑而 keyword stats 表現不明的原因。

**需要修正**：keyword discovery 改成「對每個 enabled subreddit_source 各做 `restrict_sr=on` 搜尋」，而不是 all-reddit 搜尋。這應該另開 P5 處理（不在當前 P2-P4 範圍）。

## P2 行動項（基於上面數據）

1. **PublicJSONScraper 新增 `_fetch_user_about(name)`**：拿 `link_karma + comment_karma + created_utc`，做 24h LRU cache（每作者一天一次 call）；補進 ingest 流程 → 解掉 PROGRESS.md「public JSON 拿不到 karma」這條坑
2. **`fetch_user_submissions` 拿掉 warning + 回 `[]` 的保守處理**：probe 100% 200，當作正常 endpoint；保留 404 / 403 兜底
3. **`fetch_duplicates` 同樣拿掉 warning**：endpoint 大多可用，403 改為 debug log + 回 `[]`，加 1 次 retry-with-jitter 應付偶發
4. **新增 `fetch_comment_tree(post_id)`**：`/comments/<id>.json?limit=500&depth=10`，搭配 `services/comment_tree.py` 樹狀展開器供 M5/M6 使用；MoreComments 在本輪 9 篇樣本中皆為 0，預設不處理 MoreComments expansion（OAuth-only），M6 prompt 註記「only top N replies shown」
5. **不需要 retry-with-jitter 做為通用層**：成功率 user_about 83% / 其餘 100%，單次失敗成本低，過度設計沒必要
