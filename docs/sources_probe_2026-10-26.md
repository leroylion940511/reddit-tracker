# 來源可用性探測報告（2026-10-26）

> 對 [來源登錄表](../reddit_tracker/seeds/news_sources.yaml) 逐一實測能否取得資料。這是**單次快照**，不是七天收集驗收；每日實際收錄量要等收集層上線後連續量測。

## 結論

- 登錄 **156** 個來源，啟用 **127** 個，停用 29 個（原因逐筆寫在登錄表 `notes`）。
- 非 Reddit 的 110 個啟用來源：最終輪 **109/110 成功**；唯一失敗的天下 `/cw/today` 在前兩輪成功，屬間歇性 503。
- 單次快照共取得 5,386 筆，其中 2,054 筆發布於 24 小時內。各 feed 只回傳最新 10–500 筆，因此每日實收量會隨抓取頻率增加，需以收集驗收實測。
- **每個板塊都至少有 4 個可用來源**（數據欄除外）。最弱的是生活與環境（4 個）、文化娛樂（6 個）、社群觀察（Reddit 之外只剩 PTT 與 Threads）。
- Reddit RSS 對探測限速很嚴（每 7–30 秒一次仍大量 429），為避免干擾線上 newsroom，Reddit 改以 DB 近 24 小時實際收錄量佐證。

## 各板塊彙總（非 Reddit、最終輪）

| 板塊 | 可用來源 | 快照筆數 | 其中 24h 內 |
| --- | ---: | ---: | ---: |
| 台灣 | 23 | 752 | 445 |
| 國際 | 16 | 676 | 248 |
| 兩岸與亞太 | 8 | 304 | 107 |
| 財經 | 13 | 1,068 | 222 |
| 科技 | 15 | 801 | 113 |
| 科學與健康 | 9 | 834 | 512 |
| 生活與環境 | 4 | 104 | 65 |
| 文化娛樂 | 6 | 157 | 93 |
| 體育 | 7 | 276 | 168 |
| 社群觀察（PTT、Threads） | 7 | 132 | 81 |
| 數據欄（證交所） | 2 | 282 筆資料列 | — |

## Reddit（DB 佐證，2026-10-25 22:00 至 10-26 22:00 Asia/Taipei 收錄量）

既有 15 個 subreddit 中 14 個有新收錄：askreddit 480、offmychest 329、relationship_advice 197、amitheasshole 156、legaladvice 116、confession 67、china_irl 60、taiwan 32、chineselanguage 25、hongkong 21、taipei 14、tifu 8、bestofredditorupdates 7、maliciouscompliance 2；updateme 為 0。新增的 r/worldnews 探測成功（25 筆，皆在 24h 內），r/technology 因 429 尚未驗證。11/13 Reddit RSS 停止後這些來源都會斷料。

## 需要在收集層處理的資料品質問題

| 問題 | 來源 | 處理方式 |
| --- | --- | --- |
| 項目發布時間無效（聯合新聞網每則都是 1970-01-01） | udn-headline、udn-society、udn-life、udn-sports | 以首次取得時間代替，並標記 `published_at_estimated` |
| 沒有發布時間 | ettoday-realtime、apnews-top | 同上 |
| 時區錯誤，時間偏到未來約 8 小時 | setn（三立） | 以來源層級設定時區修正；一般規則：未來超過 1 小時的時間不可信 |
| 低頻來源（最新一筆超過 48 小時） | 行政院、央行、疾管署、WHO、聯合國中文、Economist 財經、Hugging Face | 正常現象，健康監測不能只看「最新一筆距今」，要依來源的預期頻率判斷 |
| RSSHub 路由慢（30–75 秒） | storm、pts-dailynews、zaobao-world、36kr-hot | 這些路由會抓全文；收集層逾時設 90 秒並錯開排程 |
| 間歇性失敗 | cw-today | 健康監測記錄連續失敗次數，不因單次失敗停用 |

## 停用原因分類

| 類型 | 數量 | 例子 |
| --- | ---: | --- |
| 網址 404／找不到 feed | 5 | 中時、數位時代、數位部、環境資訊中心、聯合娛樂 |
| XML 格式錯誤 | 3 | 總統府、衛福部、自由健康網 |
| 上游 403（反爬蟲） | 5 | AP rss 路由、陸委會、日經中文、Economist 最新 |
| RSSHub 路由壞掉或回傳空白 | 6 | 自由即時、關鍵評論網新聞、Taiwan News、鏡週刊生活 |
| 需 headless 瀏覽器 | 3 | 中時（RSSHub）、Dcard ×2 |
| 需金鑰 | 4 | GitHub Trending、氣象署 ×2、環境部空品 |
| 其他 | 3 | 臺灣銀行匯率回傳 HTML、聯合全球版無項目、NHK 網址非中文且過期 |

## 環境

- RSSHub `fb2ce11`（2026-10-26），安裝於 `~/rsshub`，只綁 `127.0.0.1:1200`，需存取金鑰；以 Homebrew Node 26 執行（官方標示支援 22／24，目前實測可用）。
- 探測腳本：`scripts/probe_news_sources.py`。重跑方式：`PYTHONPATH=. uv run python scripts/probe_news_sources.py --out probe.json`。

## 逐來源結果

| 板塊 | 來源 id | 名稱 | 層級 | 方式 | 結果 | 筆數 | 24h 內 | 最新距今 (h) | 備註 |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 台灣 | `cna-politics` | 中央社 政治 | T2 | rsshub | ✅ | 16 | 16 | 1.6 |  |
| 台灣 | `cna-society` | 中央社 社會 | T2 | rsshub | ✅ | 20 | 9 | 1.0 |  |
| 台灣 | `cna-local` | 中央社 地方 | T2 | rsshub | ✅ | 19 | 19 | 2.0 |  |
| 台灣 | `cna-headlines` | 中央社 聚焦 | T2 | rsshub | ✅ | 20 | 20 | 1.3 |  |
| 台灣 | `pts-news` | 公視新聞網 | T2 | rss | ✅ | 25 | 25 | 0.9 |  |
| 台灣 | `pts-dailynews` | 公視 即時 | T2 | rsshub | ✅ | 15 | 15 | 1.3 |  |
| 台灣 | `twreporter` | 報導者 | T2 | rss | ✅ | 10 | 0 | 46.2 |  |
| 台灣 | `twreporter-hub` | 報導者（RSSHub） | T2 | rsshub | ✅ | 6 | 0 | 46.2 |  |
| 台灣 | `ltn-politics` | 自由時報 政治 | T2 | rss | ✅ | 40 | 40 | 0.1 |  |
| 台灣 | `ltn-society` | 自由時報 社會 | T2 | rss | ✅ | 40 | 40 | 0.4 |  |
| 台灣 | `ltn-local` | 自由時報 地方 | T2 | rss | ✅ | 40 | 40 | 0.1 |  |
| 台灣 | `ltn-breaking` | 自由時報 即時 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由解析錯誤（2026-10-26）；自由各分類原生 RSS 可用 |
| 台灣 | `udn-headline` | 聯合新聞網 要聞 | T2 | rss | ✅ | 20 | 0 | 無日期 | 項目無有效發布時間 |
| 台灣 | `udn-society` | 聯合新聞網 社會 | T2 | rss | ✅ | 20 | 0 | 無日期 | 項目無有效發布時間 |
| 台灣 | `chinatimes-realtime` | 中時 即時 | T2 | rss | ❌ 停用 | — | — | — | 原生 RSS 404，未找到替代網址（2026-10-26） |
| 台灣 | `chinatimes-hub` | 中時 即時（RSSHub） | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由需 headless Chromium，未安裝 |
| 台灣 | `storm` | 風傳媒 | T2 | rsshub | ✅ | 22 | 22 | 0.2 |  |
| 台灣 | `thenewslens-news` | 關鍵評論網 新聞 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由回傳空白（2026-10-26）；改用 thenewslens-feed |
| 台灣 | `thenewslens-feed` | 關鍵評論網 | T2 | rss | ✅ | 18 | 12 | 2.2 |  |
| 台灣 | `cw-today` | 天下雜誌 今日 | T2 | rsshub | ⚠️ 間歇失敗 | 0 | — | 無日期 | 本輪 503，前兩輪成功 |
| 台灣 | `ettoday-realtime` | ETtoday 即時 | T2 | rss | ✅ | 50 | 0 | 無日期 | 項目無有效發布時間 |
| 台灣 | `setn` | 三立新聞 | T2 | rsshub | ✅ | 30 | 29 | -7.8 | 發布時間時區錯誤（偏到未來） |
| 台灣 | `mirrormedia-political` | 鏡週刊 政治 | T2 | rsshub | ✅ | 24 | 16 | 3.4 |  |
| 台灣 | `rti-news` | 中央廣播電台 | T2 | rss | ✅ | 128 | 128 | 0.4 |  |
| 台灣 | `ey-news` | 行政院 新聞稿 | T1 | rss | ✅ | 100 | 0 | 70.2 |  |
| 台灣 | `president-news` | 總統府 新聞 | T1 | rss | ❌ 停用 | — | — | — | XML 格式錯誤，feedparser 無法解析（2026-10-26） |
| 台灣 | `moe-news` | 教育部 即時新聞 | T1 | rss | ✅ | 50 | 3 | 5.0 |  |
| 台灣 | `taiwannews-hot` | Taiwan News 熱門 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由回傳空白（2026-10-26） |
| 台灣 | `focustaiwan` | Focus Taiwan | T2 | rss | ✅ | 39 | 11 | 2.3 |  |
| 國際 | `cna-world` | 中央社 國際 | T2 | rsshub | ✅ | 17 | 17 | 0.4 |  |
| 國際 | `ltn-world` | 自由時報 國際 | T2 | rss | ✅ | 40 | 40 | 0.4 |  |
| 國際 | `udn-world` | 聯合新聞網 全球 | T2 | rss | ❌ 停用 | — | — | — | 回傳 200 但沒有項目（2026-10-26） |
| 國際 | `bbc-zhongwen` | BBC 中文 | T2 | rss | ✅ | 38 | 6 | 4.0 |  |
| 國際 | `dw-chinese` | DW 中文 | T2 | rss | ✅ | 60 | 9 | 0.3 |  |
| 國際 | `rfi-chinese` | RFI 中文 | T2 | rss | ✅ | 30 | 27 | 0.5 |  |
| 國際 | `nytimes-cn` | 紐約時報中文網 | T2 | rss | ✅ | 20 | 5 | 9.9 |  |
| 國際 | `voa-chinese` | 美國之音 中文 | T2 | rss | ✅ | 20 | 3 | 1.5 |  |
| 國際 | `un-news-zh` | 聯合國新聞 中文 | T1 | rss | ✅ | 30 | 0 | 50.2 |  |
| 國際 | `bbc-world` | BBC World | T2 | rss | ✅ | 26 | 23 | 0.2 |  |
| 國際 | `reuters-world` | Reuters World | T2 | rsshub | ✅ | 20 | 20 | 1.1 |  |
| 國際 | `apnews-top` | AP Top News | T2 | rsshub | ✅ | 148 | 0 | 無日期 | 項目無有效發布時間 |
| 國際 | `apnews-world` | AP World | T2 | rsshub | ❌ 停用 | — | — | — | 上游 403（2026-10-26） |
| 國際 | `guardian-world` | The Guardian World | T2 | rss | ✅ | 45 | 34 | 0.2 |  |
| 國際 | `aljazeera` | Al Jazeera | T2 | rss | ✅ | 25 | 25 | 0.2 |  |
| 國際 | `npr-news` | NPR News | T2 | rss | ✅ | 10 | 10 | 0.8 |  |
| 國際 | `nytimes-home` | NYT Home | T2 | rss | ✅ | 18 | 18 | 0.2 |  |
| 國際 | `dw-en` | DW English | T2 | rss | ✅ | 129 | 11 | 0.3 |  |
| 兩岸與亞太 | `cna-cross-strait` | 中央社 兩岸 | T2 | rsshub | ✅ | 20 | 11 | 0.5 |  |
| 兩岸與亞太 | `mac-news` | 陸委會 新聞稿 | T1 | rss | ❌ 停用 | — | — | — | 403 Forbidden（2026-10-26） |
| 兩岸與亞太 | `bbc-zhongwen-china` | BBC 中文 中國 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由解析錯誤（2026-10-26） |
| 兩岸與亞太 | `zaobao-china` | 聯合早報 中國即時 | T2 | rsshub | ✅ | 24 | 24 | 0.6 |  |
| 兩岸與亞太 | `zaobao-world` | 聯合早報 國際即時 | T2 | rsshub | ✅ | 24 | 24 | 0.2 |  |
| 兩岸與亞太 | `nikkei-cn` | 日經中文網 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 抓全文時上游 403（2026-10-26） |
| 兩岸與亞太 | `nikkei-asia` | Nikkei Asia | T2 | rsshub | ✅ | 30 | 24 | 0.5 |  |
| 兩岸與亞太 | `rfa-chinese` | 自由亞洲電台 中文 | T2 | rss | ✅ | 30 | 1 | 7.4 |  |
| 兩岸與亞太 | `hkfp` | Hong Kong Free Press | T2 | rss | ✅ | 30 | 7 | 3.6 |  |
| 兩岸與亞太 | `scmp-china` | SCMP China | T2 | rss | ✅ | 50 | 10 | 1.2 |  |
| 兩岸與亞太 | `thediplomat` | The Diplomat | T2 | rss | ✅ | 96 | 6 | 7.6 |  |
| 兩岸與亞太 | `nhk-zh` | NHK 中文 | T2 | rss | ❌ 停用 | — | — | — | 此網址為 NHK 日文 cat0，最新一筆已 79 天前，需另找中文 feed |
| 財經 | `cna-economy` | 中央社 產經 | T2 | rsshub | ✅ | 19 | 7 | 4.9 |  |
| 財經 | `cna-stock` | 中央社 證券 | T2 | rsshub | ✅ | 19 | 3 | 5.1 |  |
| 財經 | `ltn-business` | 自由時報 財經 | T2 | rss | ✅ | 40 | 40 | 0.3 |  |
| 財經 | `udn-money` | 經濟日報 | T2 | rss | ✅ | 20 | 20 | 0.1 |  |
| 財經 | `yahoo-tw-stock` | Yahoo 股市新聞 | T2 | rss | ✅ | 50 | 50 | 0.4 |  |
| 財經 | `cbc-news` | 中央銀行 新聞稿 | T1 | rss | ✅ | 500 | 0 | 83.2 |  |
| 財經 | `cnbc-top` | CNBC Top News | T2 | rss | ✅ | 30 | 22 | 0.0 |  |
| 財經 | `cnbc-hub` | CNBC（RSSHub） | T2 | rsshub | ✅ | 29 | 22 | 0.0 |  |
| 財經 | `reuters-business` | Reuters Business | T2 | rsshub | ✅ | 20 | 17 | 0.3 |  |
| 財經 | `ft-home` | Financial Times | T2 | rss | ✅ | 11 | 11 | 0.3 |  |
| 財經 | `economist-finance` | The Economist 財經 | T2 | rss | ✅ | 300 | 0 | 94.4 |  |
| 財經 | `economist-latest` | The Economist 最新 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 抓全文時上游 403（2026-10-26） |
| 財經 | `marketwatch-top` | MarketWatch | T2 | rss | ✅ | 10 | 10 | 0.4 |  |
| 財經 | `apnews-business` | AP Business | T2 | rsshub | ❌ 停用 | — | — | — | 上游 403（2026-10-26） |
| 財經 | `yahoo-finance` | Yahoo Finance | T2 | rsshub | ✅ | 20 | 20 | 0.1 |  |
| 科技 | `cna-tech` | 中央社 科技 | T2 | rsshub | ✅ | 19 | 3 | 6.8 |  |
| 科技 | `ithome-tw` | iThome | T2 | rss | ✅ | 30 | 9 | 2.0 |  |
| 科技 | `technews-tw` | 科技新報 | T2 | rss | ✅ | 40 | 26 | 5.0 |  |
| 科技 | `bnext` | 數位時代 | T2 | rss | ❌ 停用 | — | — | — | 原生 RSS 404，首頁未提供 feed 連結（2026-10-26） |
| 科技 | `inside-tw` | INSIDE | T2 | rss | ✅ | 10 | 6 | 8.5 |  |
| 科技 | `36kr-hot` | 36Kr 熱榜 | T2 | rsshub | ✅ | 8 | 8 | 3.9 |  |
| 科技 | `theverge` | The Verge | T2 | rss | ✅ | 10 | 10 | 0.2 |  |
| 科技 | `arstechnica` | Ars Technica | T2 | rss | ✅ | 20 | 1 | 3.2 |  |
| 科技 | `techcrunch` | TechCrunch | T2 | rss | ✅ | 20 | 7 | 0.1 |  |
| 科技 | `reuters-tech` | Reuters Technology | T2 | rsshub | ✅ | 20 | 17 | 0.7 |  |
| 科技 | `mit-tech-review` | MIT Technology Review | T2 | rss | ✅ | 10 | 2 | 1.5 |  |
| 科技 | `hn-frontpage` | Hacker News 首頁 | T3 | rss | ✅ | 20 | 14 | 1.1 |  |
| 科技 | `hn-api-top` | Hacker News 官方 API | T3 | json | ✅ | 500 | — | 無日期 |  |
| 科技 | `github-trending` | GitHub Trending | T3 | rsshub | ❌ 停用 | — | — | — | RSSHub 需設定 GITHUB_ACCESS_TOKEN |
| 科技 | `hf-daily-papers` | Hugging Face Daily Papers | T3 | rsshub | ✅ | 30 | 0 | 90.2 |  |
| 科技 | `hf-blog` | Hugging Face Blog | T3 | rsshub | ✅ | 14 | 0 | 70.0 |  |
| 科技 | `producthunt` | Product Hunt | T3 | rss | ✅ | 50 | 10 | 9.0 |  |
| 科技 | `moda-news` | 數位發展部 新聞稿 | T1 | rss | ❌ 停用 | — | — | — | RSS 網址 404，首頁未提供 feed 連結（2026-10-26） |
| 科學與健康 | `arxiv-cs-ai` | arXiv cs.AI | T3 | rss | ✅ | 321 | 321 | 10.2 |  |
| 科學與健康 | `arxiv-cs-cl` | arXiv cs.CL | T3 | rss | ✅ | 169 | 169 | 10.2 |  |
| 科學與健康 | `nature-news` | Nature | T2 | rss | ✅ | 75 | 3 | 14.2 |  |
| 科學與健康 | `sciencedaily` | ScienceDaily | T2 | rss | ✅ | 60 | 5 | 2.6 |  |
| 科學與健康 | `sciencedaily-health` | ScienceDaily Health | T2 | rss | ✅ | 60 | 3 | 2.6 |  |
| 科學與健康 | `who-news` | WHO News | T1 | rss | ✅ | 109 | 0 | 390.4 |  |
| 科學與健康 | `pansci` | 泛科學 | T2 | rss | ✅ | 10 | 1 | 3.2 |  |
| 科學與健康 | `mohw-news` | 衛福部 新聞 | T1 | rss | ❌ 停用 | — | — | — | XML 格式錯誤（2026-10-26） |
| 科學與健康 | `cdc-tw-news` | 疾管署 新聞稿 | T1 | rss | ✅ | 10 | 0 | 125.7 |  |
| 科學與健康 | `ltn-health` | 自由健康網 | T2 | rss | ❌ 停用 | — | — | — | XML 格式錯誤（2026-10-26） |
| 科學與健康 | `statnews` | STAT News | T2 | rss | ✅ | 20 | 10 | 0.3 |  |
| 生活與環境 | `cna-life` | 中央社 生活 | T2 | rsshub | ✅ | 19 | 19 | 0.2 |  |
| 生活與環境 | `ltn-life` | 自由時報 生活 | T2 | rss | ✅ | 40 | 40 | 0.2 |  |
| 生活與環境 | `udn-life` | 聯合新聞網 生活 | T2 | rss | ✅ | 20 | 0 | 無日期 | 項目無有效發布時間 |
| 生活與環境 | `einfo` | 環境資訊中心 | T2 | rss | ❌ 停用 | — | — | — | RSS 網址 404／500（2026-10-26） |
| 生活與環境 | `guardian-environment` | The Guardian Environment | T2 | rss | ✅ | 25 | 6 | 1.2 |  |
| 生活與環境 | `mirrormedia-life` | 鏡週刊 生活 | T2 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由回傳空白（2026-10-26） |
| 生活與環境 | `cwa-warnings` | 氣象署 警特報 | T1 | json | ❌ 停用 | — | — | — |  |
| 文化娛樂 | `cna-culture` | 中央社 文化 | T2 | rsshub | ✅ | 20 | 4 | 7.0 |  |
| 文化娛樂 | `cna-entertainment` | 中央社 娛樂 | T2 | rsshub | ✅ | 12 | 12 | 5.1 |  |
| 文化娛樂 | `ltn-entertainment` | 自由時報 娛樂 | T2 | rss | ✅ | 40 | 40 | 0.1 |  |
| 文化娛樂 | `udn-stars` | 聯合新聞網 娛樂 | T2 | rss | ❌ 停用 | — | — | — | RSS 網址 404（2026-10-26） |
| 文化娛樂 | `openbook` | Openbook 閱讀誌 | T2 | rss | ✅ | 10 | 1 | 10.7 |  |
| 文化娛樂 | `variety` | Variety | T2 | rss | ✅ | 10 | 10 | 0.2 |  |
| 文化娛樂 | `guardian-culture` | The Guardian Culture | T2 | rss | ✅ | 65 | 26 | 0.2 |  |
| 文化娛樂 | `thenewslens-culture` | 關鍵評論網 藝文 | T2 | rsshub | ❌ 停用 | — | — | — | 上游分類頁 404（2026-10-26） |
| 體育 | `cna-sports` | 中央社 運動 | T2 | rsshub | ✅ | 13 | 13 | 2.1 |  |
| 體育 | `ltn-sports` | 自由時報 體育 | T2 | rss | ✅ | 40 | 40 | 0.1 |  |
| 體育 | `udn-sports` | 聯合新聞網 運動 | T2 | rss | ✅ | 20 | 0 | 無日期 | 項目無有效發布時間 |
| 體育 | `bbc-sport` | BBC Sport | T2 | rss | ✅ | 68 | 48 | 0.3 |  |
| 體育 | `espn-news` | ESPN | T2 | rss | ✅ | 37 | 37 | -0.8 | 發布時間時區錯誤（偏到未來） |
| 體育 | `guardian-sport` | The Guardian Sport | T2 | rss | ✅ | 48 | 19 | 0.8 |  |
| 體育 | `sportsv` | 運動視界 | T2 | rss | ✅ | 50 | 11 | 1.7 |  |
| 社群觀察 | `reddit-taiwan` | r/taiwan | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-taipei` | r/taipei | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-china-irl` | r/china_irl | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-hongkong` | r/hongkong | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-chineselanguage` | r/ChineseLanguage | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-askreddit` | r/AskReddit | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-amitheasshole` | r/AmItheAsshole | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-relationship-advice` | r/relationship_advice | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-offmychest` | r/offmychest | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-legaladvice` | r/legaladvice | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-tifu` | r/tifu | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-confession` | r/confession | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-bestofredditorupdates` | r/BestofRedditorUpdates | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-maliciouscompliance` | r/MaliciousCompliance | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-updateme` | r/UpdateMe | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-worldnews` | r/worldnews | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `reddit-technology` | r/technology | T4 | reddit | ➖ | — | — | — | 以 DB 實際收錄佐證，見下節 |
| 社群觀察 | `ptt-gossiping` | PTT 八卦板 | T4 | rss | ✅ | 20 | 20 | 0.0 |  |
| 社群觀察 | `ptt-hatepolitics` | PTT 政黑板 | T4 | rss | ✅ | 18 | 18 | 0.0 |  |
| 社群觀察 | `ptt-stock` | PTT 股票板 | T4 | rss | ✅ | 17 | 13 | 0.7 |  |
| 社群觀察 | `ptt-tech-job` | PTT 科技業板 | T4 | rss | ✅ | 19 | 2 | 1.0 |  |
| 社群觀察 | `ptt-womentalk` | PTT 女孩板 | T4 | rss | ✅ | 18 | 7 | 2.4 |  |
| 社群觀察 | `ptt-baseball` | PTT 棒球板 | T4 | rss | ✅ | 20 | 20 | 0.0 |  |
| 社群觀察 | `dcard-trending` | Dcard 熱門 | T4 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由需 headless Chromium，且 Dcard 有反爬蟲 |
| 社群觀察 | `dcard-funny` | Dcard 有趣 | T4 | rsshub | ❌ 停用 | — | — | — | RSSHub 路由需 headless Chromium，且 Dcard 有反爬蟲 |
| 社群觀察 | `threads-search-taiwan` | Threads 搜尋 台灣 | T4 | rsshub | ✅ | 20 | 1 | 0.2 |  |
| 數據欄 | `twse-index` | 證交所 每日市場成交 | T1 | json | ✅ | 15 | — | 無日期 |  |
| 數據欄 | `twse-mi-index` | 證交所 每日收盤指數 | T1 | json | ✅ | 267 | — | 無日期 |  |
| 數據欄 | `bot-fx` | 臺灣銀行 牌告匯率 | T1 | csv | ❌ 停用 | — | — | — | 回傳 HTML 而非 CSV（2026-10-26），需另找匯率來源 |
| 數據欄 | `cwa-forecast` | 氣象署 36 小時預報 | T1 | json | ❌ 停用 | — | — | — |  |
| 數據欄 | `moenv-aqi` | 環境部 空氣品質 | T1 | json | ❌ 停用 | — | — | — |  |
