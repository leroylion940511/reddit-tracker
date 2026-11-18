# 實驗二結果：查核員開與關

- 產生時間：2026-11-19 06:18 台北（「被刪的來源」一節於 2026-11-19 用同一批結果補產）；腳本 `scripts/run_exp2.py`
- 模型：`gpt-6.1-sol | codex-cli 0.166.0 | reasoning_effort=low`；`FACT_CHECKER_PER_SOURCE`＝關（只影響 (c) 組）
- 案例：開發集 5（E01–E05）、保留集 5、正常稿 15。保留集用實驗一的最終標註產生。
- 記者 v1 只產生一次（25 篇，各 1 次模型呼叫），三組共用；下表的 LLM 呼叫數不含這 25 次。
- 擋下＝最終版不再引用無關來源，或稿件 HOLD。誤擋＝正常稿 HOLD，或有來源被刪掉。
- 只能說「在這些案例上」；結論以保留集為主，開發集是查核工具設計時就看過的案例。

| 設定 | 開發集擋下 | 保留集擋下 | 正常稿誤擋 | LLM 呼叫數（其中查核員） |
| --- | --- | --- | --- | --- |
| (a) 全關 | 0/5 | 0/5 | 0/15 | 1（0） |
| (b) 只開程式工具 | 5/5 | 2/5 | 6/15 | 14（0） |
| (c) 程式＋LLM | 5/5 | 1/5 | 0/15 | 21（14） |

保留集只有 5 篇（上限 10）：實驗一 test 裡符合條件的配對就這麼多，照實報。

## 逐案結果

每格：最終狀態／版本數／被刪的來源數；✅＝擋下，❌＝沒擋，⚠️＝誤擋。

| 案例 | 類別 | (a) 全關 | (b) 只開程式工具 | (c) 程式＋LLM | 說明 |
| --- | --- | --- | --- | --- | --- |
| E01 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 1 | ✅ checked／v2／刪 1 | 來源混進 AP 美式足球報導（Seahawks 20-3 win） |
| E02 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 5 | ✅ checked／v2／刪 5 | 6 個來源有 3 個是蔣萬安競總／沈伯洋後援會 |
| E03 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 1 | ✅ checked／v2／刪 1 | 併入 HN「Switzerland. Block by block」，正文還寫了瑞士地圖 |
| E04 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 2 | ✅ checked／v2／刪 2 | 併入 Skydance 優離：都有 buyout，但是兩件事 |
| E05 | dev | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 1 | ✅ checked／v2／刪 1 | 附了不相關的 PTT「Anthropic 遞交 IPO」，正文也寫進去 |
| H-T106 | holdout | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | 實驗一 T106：same／only_a，方法 A 合併、最終答案不是 |
| H-T457 | holdout | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | 實驗一 T457：same／both，方法 A 合併、最終答案不是 |
| H-T523 | holdout | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | ❌ checked／v1／刪 0 | 實驗一 T523：cross／both，方法 A 合併、最終答案不是 |
| H-T767 | holdout | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 2 | ✅ checked／v2／刪 2 | 實驗一 T767：cross／only_a，方法 A 合併、最終答案不是 |
| H-T807 | holdout | ❌ checked／v1／刪 0 | ✅ checked／v2／刪 2 | ❌ checked／v1／刪 0 | 實驗一 T807：same／both，方法 A 合併、最終答案不是 |
| N-41480 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-09 M 組稿 41480 |
| N-44224 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-10 M 組稿 44224 |
| N-44227 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-10 M 組稿 44227 |
| N-44229 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-10 M 組稿 44229 |
| N-44245 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-10 M 組稿 44245 |
| N-48568 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-11 M 組稿 48568 |
| N-48569 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-11 M 組稿 48569 |
| N-48575 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-11 M 組稿 48575 |
| N-54425 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-12 M 組稿 54425 |
| N-54434 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 3 | checked／v1／刪 0 | 2026-11-12 M 組稿 54434 |
| N-59775 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-13 M 組稿 59775 |
| N-64577 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-14 M 組稿 64577 |
| N-69852 | normal | checked／v1／刪 0 | checked／v1／刪 0 | checked／v1／刪 0 | 2026-11-15 M 組稿 69852 |
| N-69866 | normal | checked／v1／刪 0 | ⚠️ checked／v2／刪 1 | checked／v1／刪 0 | 2026-11-15 M 組稿 69866 |
| N-69869 | normal | checked／v2／刪 0 | checked／v2／刪 0 | checked／v2／刪 0 | 2026-11-15 M 組稿 69869 |

## 被刪的來源

「無關來源」＝案例點名要擋的那則；其他都算連帶誤刪（正常稿沒有無關來源，刪的全是誤刪）。

| 設定 | 刪除數 | 刪對（無關來源） | 連帶誤刪 |
| --- | --- | --- | --- |
| (a) 全關 | 0 | 0 | 0 |
| (b) 只開程式工具 | 22 | 10 | 12 |
| (c) 程式＋LLM | 12 | 9 | 3 |

| 設定 | 案例 | item_id | 來源 | 標題 | 判定 |
| --- | --- | --- | --- | --- | --- |
| (b) 只開程式工具 | E01 | 1053 | AP Top News | Jaxon Smith-Njigba has big night in Seah | 無關來源 |
| (b) 只開程式工具 | E02 | 4862 | 三立新聞 | 批周春米「沒小孩可憐」！蘇清泉二度道歉認使用不當言語 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | E02 | 385 | 鏡週刊 政治 | 蘇清泉批周春米「沒小孩，可憐，不知養育辛苦」 遭轟歧視深夜道歉了 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | E02 | 76 | 公視新聞網 | 蔣萬安辦競總成立大會 沈伯洋成立女力後援會 | 無關來源 |
| (b) 只開程式工具 | E02 | 432 | 中央廣播電台 | [政治] 台北市長選戰／沈伯洋女力後援會成立 蕭美琴籲支持者「戒慎恐懼」 | 無關來源 |
| (b) 只開程式工具 | E02 | 8 | 中央社 政治 | 沈伯洋女力後援會成立 蕭美琴讚具備5心特質 | 無關來源 |
| (b) 只開程式工具 | E03 | 2953 | Hacker News 首頁 | Switzerland. Block by block. At 1:1 scal | 無關來源 |
| (b) 只開程式工具 | E04 | 5569 | Reuters Business | Skydance offers buyouts to some employee | 無關來源 |
| (b) 只開程式工具 | E04 | 5264 | Variety | Skydance Is Offering Employees Voluntary | 無關來源 |
| (b) 只開程式工具 | E05 | 4433 | PTT 股票板 | [新聞] AI新創Anthropic遞交IPO申請　估值達1.5 | 無關來源 |
| (b) 只開程式工具 | H-T767 | 38411 | 中央社 聚焦 | 加密貨幣交易所幣安遭竊63億美元資產追回95% 分階段恢復提款 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | H-T767 | 33061 | Yahoo Finance | Elon Musk, CZ Trade Blows Over SpaceX Sh | 無關來源 |
| (b) 只開程式工具 | H-T807 | 35513 | 風傳媒 | 台北市長辯論意外翻轉？作家評蔣萬安反咬得分：沈伯洋沒一次打殘蔣，選民該緊張了 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | H-T807 | 36686 | 自由時報 政治 | TVBS最新民調！辯論會沈伯洋優於蔣萬安  支持度46％、42％沈伯洋小輸 | 無關來源 |
| (b) 只開程式工具 | N-44224 | 78991 | 自由時報 政治 | 聯合報民調領先李四川3％ 蘇巧慧拋願景：900天耕耘獲認同 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-44245 | 80427 | Yahoo 股市新聞 | 佳世達法說》AI伺服器明年逐步放量！董座陳其宏談美選後AI疑慮：屬短期影響 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-48569 | 83852 | 中央廣播電台 | [國際] 共和黨議員提彈劾案 美防長本週面臨眾議院投票 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-48575 | 86352 | 公視 即時 | 傳立陶宛要求我駐處更名 外交部：假消息有傷台立互動 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-54434 | 91197 | 自由時報 財經 | 傳統一年底前併購肯德基、必勝客亞洲業務！公司回應了 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-54434 | 91239 | 中央社 | 傳洽購肯德基必勝客業務　統一：無法置評 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-54434 | 90244 | 經濟日報 | 統一傳買亞洲肯德基、必勝客業務 年底前有望達成協議 | ⚠️ 連帶誤刪 |
| (b) 只開程式工具 | N-69866 | 108469 | 中央廣播電台 | [國際] 傳輝達接洽安謀執行長哈斯 董事會：正在遴選獵才公司 | ⚠️ 連帶誤刪 |
| (c) 程式＋LLM | E01 | 1053 | AP Top News | Jaxon Smith-Njigba has big night in Seah | 無關來源 |
| (c) 程式＋LLM | E02 | 4862 | 三立新聞 | 批周春米「沒小孩可憐」！蘇清泉二度道歉認使用不當言語 | ⚠️ 連帶誤刪 |
| (c) 程式＋LLM | E02 | 385 | 鏡週刊 政治 | 蘇清泉批周春米「沒小孩，可憐，不知養育辛苦」 遭轟歧視深夜道歉了 | ⚠️ 連帶誤刪 |
| (c) 程式＋LLM | E02 | 76 | 公視新聞網 | 蔣萬安辦競總成立大會 沈伯洋成立女力後援會 | 無關來源 |
| (c) 程式＋LLM | E02 | 432 | 中央廣播電台 | [政治] 台北市長選戰／沈伯洋女力後援會成立 蕭美琴籲支持者「戒慎恐懼」 | 無關來源 |
| (c) 程式＋LLM | E02 | 8 | 中央社 政治 | 沈伯洋女力後援會成立 蕭美琴讚具備5心特質 | 無關來源 |
| (c) 程式＋LLM | E03 | 2953 | Hacker News 首頁 | Switzerland. Block by block. At 1:1 scal | 無關來源 |
| (c) 程式＋LLM | E04 | 5569 | Reuters Business | Skydance offers buyouts to some employee | 無關來源 |
| (c) 程式＋LLM | E04 | 5264 | Variety | Skydance Is Offering Employees Voluntary | 無關來源 |
| (c) 程式＋LLM | E05 | 4433 | PTT 股票板 | [新聞] AI新創Anthropic遞交IPO申請　估值達1.5 | 無關來源 |
| (c) 程式＋LLM | H-T767 | 38411 | 中央社 聚焦 | 加密貨幣交易所幣安遭竊63億美元資產追回95% 分階段恢復提款 | ⚠️ 連帶誤刪 |
| (c) 程式＋LLM | H-T767 | 33061 | Yahoo Finance | Elon Musk, CZ Trade Blows Over SpaceX Sh | 無關來源 |
