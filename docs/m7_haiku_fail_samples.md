# M7.6 — Haiku-fail 樣本分析（中英對照）

目的：scoring 視角下，找中文 sub haiku pass 15.1% vs 英文 35.3% 的失準模式。
每個樣本顯示：title + body 截斷 + 五軸 + verdict reason。

## 中文 sub haiku-fail 樣本（4 sub × 10 + 1 sub × 10）

### r/china_irl (zh fail, 10 筆)

- **[11842]** 【纪念】点燃一盏心灯：致那些三十七年前留在广场上的年轻灵魂
  - body: 每年的这一天，无论网络空间如何被封锁、清洗、抹除，有些记忆是无法被坦克彻底碾碎的。 三十七年前的初夏，那些走上街头的学生和市民，他们要的不过是一个更清廉、更自由、更有尊严的中国。他们是那个时代最热血、最纯粹的一批精英，却不幸将生命永远定格…
  - axes: story_potential=0.30 emotional_pull=0.80 grassroots=0.80 novelty=0.20 authenticity=0.90  →  verdict=skip  score=0.550
  - reason: 虽然情感张力和真实性较高，但题材敏感且缺乏后续展开潜力，且内容过于纪念性质，新颖度不足。
- **[7242]** 原來很多中國人移民只看人均GDP， 如果這種想法。 。
  - body: 原来很多中国人移民只看人均GDP， 如果马来西亚华人(人均GDP $14000) 有这种思想， 我们就排队入新加坡(人均GDP$80000) 国籍了 😂。 我们不排队因为人均GDP不能代表生活水平。 对于中产阶级， 马来西亚你可以有别墅，…
  - axes: story_potential=0.40 emotional_pull=0.60 grassroots=0.90 novelty=0.50 authenticity=0.80  →  verdict=skip  score=0.500
  - reason: 虽然内容有趣且有观点，但缺乏后续展开潜力，且互动数据为零，难以判断其传播潜力。
- **[7615]** 2026年Q1苹果手机出货量全球第一，份额21%同比增9%，鲸吞48%收入；中国品牌份额萎缩，没有翻盘的可能，一副衰败的景象
  - body: 市场研究机构Counterpoint Research发布报告显示，苹果在2026年第一季度首次登顶全球智能手机出货量榜首，与三星并列第一，份额均为21%。 这是苹果历史上首次在Q1季度取得这一位置，iPhone创下了新的里程碑。 数据显…
  - axes: story_potential=0.60 emotional_pull=0.40 grassroots=0.80 novelty=0.30 authenticity=0.60  →  verdict=skip  score=0.500
  - reason: 虽然内容有一定分析价值，但缺乏具体数据来源且过于预测性，情感共鸣和话题新颖度不足，难以引发持续讨论。
- **[9650]** RD-012
  - body: 想分享一個最近用得很順手的 App：秒聽錄音。我是HR，平常1on1的次數很多，以前開完會還要花一小時整理逐字稿。 核心體驗：離線錄音也沒問題。然後有一個重點功能要講——客戶拜訪結束秒出客戶意向總結，跟單超輕鬆，這個是讓我從「還不錯」升級…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.30  →  verdict=skip  score=0.250
  - reason: 这是一篇典型的产品推广帖，缺乏真实性和情感共鸣，且内容过于普通，没有后续展开的潜力。
- **[11501]** 键政为什么要逻辑？
  - body: 键政对线时，很多人喜欢攻击对方没逻辑。 不是，玩键政要什么逻辑啊？ 要逻辑，还不如跟 AI 聊天。 再说就算逻辑天衣无缝，你就能保证预测必对吗？ 逻辑一对，预测必对，哲学系遍地先知啦？ 键政要什么逻辑？ 要的是情绪，要的是屁股，要的是ME…
  - axes: story_potential=0.30 emotional_pull=0.60 grassroots=0.80 novelty=0.50 authenticity=0.70  →  verdict=skip  score=0.450
  - reason: 虽然内容有趣且有一定情绪张力，但缺乏后续展开潜力，且主题过于抽象，难以吸引持续关注。
- **[13770]** 感觉老毛的很多诗词都有一种霸气
  - body: 有一种莫名的气场 是大部分古代诗人做不到的 或者说 他这种心境很多时候别人也很难再现 比如 "万类霜天竞自由""要扫除一切害虫，全无敌""秋风萧瑟今又是，换了人间""雄关漫道真如铁，而今迈步从头越"（这句在中学教材全解每本都有，当初看到这…
  - axes: story_potential=0.30 emotional_pull=0.60 grassroots=0.90 novelty=0.40 authenticity=0.80  →  verdict=skip  score=0.450
  - reason: 虽然内容有一定情感共鸣和真实感，但缺乏后续展开潜力，且题材不够新颖，未达到追踪标准。
- **[167]** 作为男人，你对肛门快感的想法是什么？注意是你被进入。研究发现肛门快感其实能让男人更爽，但大多数男人就是很抗拒，觉得身为直男怎么能做这种事情。
  - body: 大多数男人一生都不愿意去体验一下肛门快感，害怕这样做了以后就不是男人了，害怕这会毁掉自己的男子气概，害怕打开新世界的大门以后就再也回不去了。然而，研究发现肛门快感其实是更爽更刺激的，能让男人感受到更棒的体验，但大多数男人对此就是很抗拒，觉…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.60 authenticity=0.60  →  verdict=skip  score=0.350
  - reason: 虽然题材有一定新奇性，但缺乏后续展开潜力，且互动数据较差（0分0评论），难以形成有吸引力的讨论。
- **[13609]** 中国即使用着最烂的体制也能做到世界第二是不是证明中国发展远远没达到上限，仍有巨大潜力。
  - body: 完全被共产主义拖了后腿，希望执政党及时刹车转向吧，别搞专制了，只要不瞎jb搞中国人凭着吃苦耐劳不会过得差，不敢想象中华民主联邦有多强，拳打欧盟，脚踩美帝。
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.60  →  verdict=skip  score=0.350
  - reason: 内容偏政治讨论，缺乏具体事件展开潜力，且情绪表达较为常见，题材不够新颖。
- **[15250]** 乌克兰就无人机入侵事件向希腊道歉：都是俄罗斯害的
  - body: 乌克兰外交部发言人赫奥尔希·蒂赫伊6月5日表示，乌克兰已就上个月在希腊领海发现的一架海军无人机事件向希腊道歉。 此前，希腊于6月3日就此事向乌克兰提出正式外交抗议。希腊方面称，这架无人机只属于乌克兰，5月7日被渔民在莱夫卡达岛海岸发现，引…
  - axes: story_potential=0.60 emotional_pull=0.40 grassroots=0.80 novelty=0.30 authenticity=0.70  →  verdict=skip  score=0.500
  - reason: 虽然事件有一定后续发展潜力，但整体内容较为常规，缺乏足够的新颖性和情感张力，且当前无互动数据支持。
- **[11377]** 夜观探花有感
  - body: 国产区av最常见的拍摄手法就是全程执法记录仪机位，男女主噼里啪啦操了半天看不见鸡巴也看不见逼，女的表情僵硬不断发出投币式摇摇车一样的公式淫叫，男的每抽插十到十五下必假装脱轨故意滑出来一下以冷却CD，俩人的生殖器官都被一辈子不见得修剪一次的…
  - axes: story_potential=0.10 emotional_pull=0.20 grassroots=0.80 novelty=0.30 authenticity=0.60  →  verdict=skip  score=0.150
  - reason: 内容为个人观感评论，缺乏事件展开潜力，且情绪张力和新颖度都较低

### r/chineselanguage (zh fail, 10 筆)

- **[16635]** Does anyone know what the Hanzi on here from Mulan is?
  - body: I know that the two on the left is 北京, but I’m curious what the two Hanzi on the right are. I’ve tried to write them in…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 这是一个简单的语言学习提问，缺乏后续展开潜力，且题材过于普通，没有特别的情绪吸引力或新颖性。
- **[9661]** What’s the difference between 看到and 看出来?
  - body: 1.看到(kàn dào）—（see/catch sight of) Meaning: you use your eyes to spot something physically. Only visual perception, no …
  - axes: story_potential=0.20 emotional_pull=0.10 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.150
  - reason: 这是一篇语言教学帖，内容过于基础且缺乏后续展开潜力，情感共鸣和题材新颖度也较低。
- **[12648]** How to properly start learning mandarin.
  - body: Hey guys, im planning to study in china for my university, which is why i wanna learn mandarin. I want to be able to ho…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 雖然作者是素人，但內容較為普通，缺乏後續發展潛力和新穎性，情感共鳴也有限。
- **[8869]** 《中文新解｜裝乖》這不是性格穩定，而是生存技能的一種。
  - body: 把脾氣摺好收進笑裡， 方便別人拿你當懂事。 這不是性格穩定，而是生存技能的一種。 為了減少摩擦，你學會把最尖銳的部分磨平，好讓自己能滑進任何不適合的環境。 有沒有那種時刻——不是真的不在乎，只是不想解釋？ https://preview.…
  - axes: story_potential=0.30 emotional_pull=0.70 grassroots=0.80 novelty=0.60 authenticity=0.90  →  verdict=skip  score=0.500
  - reason: 雖然情感張力強且真實性高，但缺乏事件展開潛力，屬於個人感悟類型，難以形成持續討論。
- **[8426]** Skipping subvocalization when reading?
  - body: I have been studying Mandarin Chinese for about 2 months not and have really prioritized character recognition and basi…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.40 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 雖然貼文真實性高且符合素人輪廓，但缺乏後續發展潛力，情緒張力和新穎度也較低，難以吸引持續關注。
- **[12784]** struggling with listening to native speakers in Taiwan
  - body: Hi, i’ve studied up to HSK 4 years ago in chinese school when i was young and i don’t use my mandarin much aside from w…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 虽然内容真实且作者背景符合素人特征，但缺乏后续展开潜力，情感共鸣和题材新颖度也较低。
- **[16508]** Don't watch if you want your tones to suck!
  - body: I feel like especially Americans mess up the 4th and 4th pairs. I also always accidentally do like a 1st and 4th when I…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.40 authenticity=0.70  →  verdict=skip  score=0.250
  - reason: 内容过于简单，缺乏展开潜力，且情绪吸引力和新颖度较低
- **[7775]** Meaning of this oracle bone symbol?
  - body: Anyone who can help me shine light on the historical meaning of this oracle bone symbol? 🙏
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.60 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 虽然题材新颖且作者看起来是素人，但缺乏后续展开潜力，且目前没有互动，难以引发情感共鸣。
- **[8258]** The difference between 看见and看到
  - body: Basic meaning (both to see.) They are almost the Same for real things you look at. Small differences & easy rules. 1)看见…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 这是一篇语言教学贴，内容过于基础且缺乏展开潜力，情感共鸣和话题新颖度都较低。
- **[14024]** Interactive Chinese reading practice with active recall. See the characters, ty…
  - body: (empty)
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.60 authenticity=0.70  →  verdict=skip  score=0.250
  - reason: 虽然题材有一定新颖性，但缺乏具体内容描述，难以评估后续发展潜力，且互动性不足导致情感吸引力较低。

### r/hongkong (zh fail, 10 筆)

- **[7227]** Tang' Roast uses paper spoon and it broke scrapping the salted duck egg.
  - body: I'm just trying to peel the shell, man. It was bought from the branch near the TKW market (i.e. the "Red Apple"): https…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 雖然真實性高且作者像素人，但內容過於瑣碎，缺乏事件延展性和新穎度，情緒拉力也有限。
- **[11491]** Iang visa hongkong
  - body: I have question for iang , I did my master and then got 2 years iang visa and then do one year iang extension by workin…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.60  →  verdict=skip  score=0.250
  - reason: 貼文主要是一個關於簽證的問題，沒有明顯的後續發展潛力或情感吸引力，且題材較為普通。
- **[12938]** In Store Stock Availability of TWEMCO Clocks
  - body: Traveling to HK next week and I'd love to buy a TWEMCO Clock in person. Aware that the factory no longer sells directly…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.20 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 貼文內容單純是尋求購物建議，沒有明顯的後續發展潛力或情感吸引力，且題材較為普通。
- **[12319]** Omakase / high quality sushi with vegetarian options in HK?
  - body: Hi, I'm planning a birthday dinner for my boyfriend who is a sushi lover, ideally omakase but I guess that would be qui…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.90  →  verdict=skip  score=0.350
  - reason: 雖然貼文真實性高且符合素人輪廓，但缺乏後續發展潛力，題材也較為普通，難以引起強烈情緒共鳴。
- **[7224]** Venting: Carousell in HK has gone way too commercial
  - body: I'm looking for a cupboard, and on carousel there are only ads for custom made ones. Too many
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文內容過於簡單，僅表達對 Carousell 平台商業化的不滿，缺乏故事發展潛力和情緒吸引力，且題材不具新穎性。
- **[10336]** Late HSBC Credit Card payment: Waive fees?
  - body: I forgot to fund my HSBC bank account 6 days past the due date and got charged 600HKD. It is my first time forgetting (…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.70  →  verdict=skip  score=0.350
  - reason: 貼文內容過於普通，僅為個人信用卡逾期問題，沒有明顯的後續發展潛力或情感張力，且題材常見，難以吸引追蹤興趣。
- **[14014]** Aqila SPA in SZ?
  - body: Hi guys, I'd like to go to Aqila SPA in SZ and spend the night there but I got a few questions first: - Do you automati…
  - axes: story_potential=0.20 emotional_pull=0.10 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.150
  - reason: 這篇貼文主要是關於水療中心的具體問題詢問，沒有明顯的事件發展潛力或情感吸引力，且題材較為普通。
- **[9179]** Bringing in medication
  - body: Hello, about to start uni in september and i was wondering if i could bring in hair loss medication (specifically dutas…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 貼文內容單純是關於藥物進口的問題，沒有明顯的後續發展潛力或情感吸引力，且題材較為普通。
- **[7230]** Hong Kong beaches are underrated!
  - body: Clear water bay in SK. Water was so clear, comparable to Croatia omis. And that’s a fact from my first hand experience.…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 雖然作者像普通用戶，但內容過於普通，僅是對比香港和克羅地亞海灘水質，沒有足夠的吸引力或潛力。
- **[8847]** Where to fix headphones in Hong Kong?
  - body: Following its faithful service for the last 3-4 years, my Sony XM-4 has unfortunately reached the point where it lets o…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.90  →  verdict=skip  score=0.350
  - reason: 雖然貼文真實且具備素人特質，但內容過於日常且缺乏後續發展潛力，情緒張力也較弱。

### r/taipei (zh fail, 10 筆)

- **[8087]** Taipei & buying glasses
  - body: Hello! I'll be in Taipei for about six weeks this summer for a scholarship program. I wear -5.5 prescription glasses fo…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文內容單純是關於購買眼鏡的詢問，缺乏後續發展潛力，且情緒張力和新穎度都較低。
- **[12000]** How do people dry their clothes during the rainy season?
  - body: I will be traveling to Taipei, Taiwan this summer and staying in a studio apartment rental for 2 months. The place has …
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 这是一个关于台北生活常识的普通提问，缺乏后续展开潜力，且情感共鸣和题材新颖度都较低。
- **[7274]** ENGLISH SUBTITLE CINEMA IN TAIPEI OR TAOYUAN NEAR TRAIN STATIONS
  - body: Hey there! Is there anyone who has tried seeing a movie in Taiwan? Can you suggest a movie theater with English subtitl…
  - axes: story_potential=0.20 emotional_pull=0.10 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.150
  - reason: 貼文內容單純是尋求電影院資訊，沒有故事發展潛力或情感張力，且題材常見無新意。
- **[7275]** Pokemon Cards
  - body: Hello. Can anyone recommend where to buy decently priced Pokemon cards in Taipei? I'm looking mostly for Japanese and C…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文內容單純是尋求購物建議，沒有明顯的後續發展潛力或情感吸引力，且題材較為普通。
- **[13781]** Taiwan Concert Lottery - Is there a chance of getting better seats?
  - body: Hi! I got a slot for a concert in Taiwan this coming September. Not super happy with the seats but I was wondering what…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文內容過於普通，僅為一般性詢問，沒有明顯的後續發展潛力或情感吸引力。
- **[13780]** Terminal 2 to Terminal 1 Taoyuan Airport
  - body: Hi there, I have a layover of 1 hour and 50 mins and I will be landing at terminal 2 in Taoyuan airport. My flight to m…
  - axes: story_potential=0.20 emotional_pull=0.10 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.150
  - reason: 这是一个普通的机场转机咨询帖，缺乏后续展开潜力、情绪吸引力和新颖性。
- **[14110]** Light and ultra light coffe roasters? Simple was OK - not my favorite. Fika fik…
  - body: Taipei has exceptional coffee scene. I prefer light and ultra light beans. Mostly washed process. Any good suggestions?…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 貼文內容僅為尋求咖啡店推薦，沒有明顯的事件發展潛力或情感吸引力，且題材較為日常普通。
- **[17589]** taipei this summer - to pack
  - body: Hi! I’ll be in Taipei this July/August for 8 weeks. Is there anything that is a must pack that I shouldn’t forget? I’ve…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 这是一篇普通的旅游咨询贴，缺乏后续展开潜力，情感共鸣和话题新颖度都较低。
- **[13270]** How fancy / expensive of a hotel should I stay in?
  - body: I've got a work trip to Taiwan that I'm leaving for a day early to see Taipei. I browsed this sub for hotel recommendat…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.80 novelty=0.10 authenticity=0.90  →  verdict=skip  score=0.250
  - reason: 貼文內容較為普通，僅為一般旅遊住宿詢問，缺乏後續發展潛力及情感吸引力，且題材不具新穎性。
- **[12953]** Yangmingshan hike
  - body: Hello! Thinking of going yangmingshan during my trip to Taipei in Oct. I plan to hike to mount qixing and qingtiangang.…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 雖然是素人發問，但內容過於普通，缺乏吸引力和後續發展潛力。

### r/taiwan (zh fail, 10 筆)

- **[8075]** nightlife/ things to do in taipei?
  - body: hey everyone, just landed in taipei and will be here for a while as a foreign student. i was wondering where the best n…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 雖然是素人發文且真實性高，但內容過於普通，缺乏獨特性和後續發展潛力，難以引起強烈情緒共鳴。
- **[12922]** Places to find Taiwanese caregivers?
  - body: Any places to connect with Taiwan-based caregivers or younger workforce, who would be interested in coming to the US to…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.70  →  verdict=skip  score=0.350
  - reason: 貼文主要為尋求資源，故事發展潛力有限，且缺乏顯著的情緒張力或新穎性。
- **[11659]** Any Spurs fans? (NBA Finals)
  - body: Just FYI, I’ve heard that Hooters (Qincheng location) and Brass Monkey are playing the NBA Finals games, starting tomor…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文內容單純是分享觀賽資訊，沒有明顯的後續發展潛力或情感張力，且題材較為普通。
- **[11668]** Last train home on Taiwan Railway 最後一班火車 - Pat Metheny Group
  - body: Last train home on Taiwan Railway 最後一班火車 - Pat Metheny Group The classic hit set to visuals on Taiwan Railway…
  - axes: story_potential=0.20 emotional_pull=0.30 grassroots=0.80 novelty=0.40 authenticity=0.60  →  verdict=skip  score=0.250
  - reason: 貼文缺乏具體事件或故事性，僅是音樂與火車的簡單結合，難以吸引持續關注。
- **[9639]** Where do locals buy their street styles clothes?
  - body: Ive been staying in taoyuan, Ive seen lot of locals in their 20s-30s wearing these baggy and oversized clothes. It’s pr…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文內容過於普通，僅為尋求購物建議，沒有明顯的後續發展潛力或情感吸引力。
- **[8058]** Weekly Travel, Questions, & Mandarin Thread
  - body: This thread is for: Travel queries & information. Generic questions that most likely won't generate discussion as their…
  - axes: story_potential=0.10 emotional_pull=0.00 grassroots=0.00 novelty=0.00 authenticity=0.90  →  verdict=skip  score=0.050
  - reason: 這是一個例行性的討論串公告，沒有故事發展潛力，也缺乏情緒張力和新穎性，且由機器人發布，無法追蹤個人故事。
- **[10922]** Questions about Taiwan international politics
  - body: Please forgive me for being ignorant, but my understanding is China wants to make Taiwan part of China. I have seen a f…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.70  →  verdict=skip  score=0.350
  - reason: 雖然作者真實性尚可，但內容過於基礎且缺乏具體事件，難以引發深入討論或後續發展。
- **[10326]** Tixcraft Name Errors
  - body: Finished the presale war on BTS Arirang concert here in taiwan. Surprised to see similar experiences with other people …
  - axes: story_potential=0.40 emotional_pull=0.30 grassroots=0.80 novelty=0.20 authenticity=0.70  →  verdict=skip  score=0.350
  - reason: 雖然是素人發文且真實性尚可，但缺乏情緒張力和新穎性，且事件發展潛力有限。
- **[8062]** Lactose free products and healthy cooking restaurants in Taipei?
  - body: Hello everyone My wife is recovering from a condition and is on a lactose, gluten free diet and also needs to avoid oil…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.80 novelty=0.20 authenticity=0.90  →  verdict=skip  score=0.350
  - reason: 雖然是真實的求助帖，但缺乏後續發展潛力，且題材較為日常，難以引起強烈情緒共鳴。
- **[8053]** Landing Visa with a German temporary passport
  - body: Hello everybody. My passport got stolen and currently just hold a temporary passport. The embassy of Taiwan said I need…
  - axes: story_potential=0.30 emotional_pull=0.20 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.250
  - reason: 貼文主要為個人求助，故事發展潛力和情緒拉力較低，且題材不具新穎性，難以吸引廣泛關注。

## 英文 sub haiku-fail 樣本（對照組）

### r/amitheasshole (en fail, 5 筆)

- **[9080]** AITA for cancelling being in a performance after agreeing to do it
  - body: I honestly feel really guilty about this and don’t know if I’m being selfish. For context, I’ve been involved in drama …
  - axes: story_potential=0.30 emotional_pull=0.60 grassroots=0.80 novelty=0.20 authenticity=0.70  →  verdict=skip  score=0.450
  - reason: 虽然情感张力较高且作者看起来真实，但故事发展潜力有限且题材缺乏新意，难以吸引持续关注。
- **[11882]** AITA for nicknaming my friend “perry” when his real name is “peezy”
  - body: so my buddy is like 40 years old and calls himself “peezy”. He requests for all of us in the friend group to call him t…
  - axes: story_potential=0.60 emotional_pull=0.40 grassroots=0.90 novelty=0.30 authenticity=0.60  →  verdict=skip  score=0.500
  - reason: 虽然故事有一定后续潜力，但整体缺乏新意，且情感共鸣较弱，真实性存疑。
- **[12037]** AITA for having a 2-hour gap between my wedding and the start of Cocktail hour?
  - body: I'm(M33) already married 2 years to my wife, but I was talking to a new coworker(M29) today about weddings. I mentioned…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 雖然作者是素人，但故事缺乏後續發展潛力，且情緒張力和新穎度都較低，難以引起廣泛討論。
- **[11417]** AITA - for not understanding why my Asian friend had to have rice with every me…
  - body: So I was dating somebody for a while who was of Indonesian heritage. Absolutely lovely person, the reasons why we split…
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 内容过于普通，缺乏后续展开潜力，且文化差异讨论不够深入或新颖，难以吸引持续关注。
- **[9384]** AITA For using a first basemen’s glove
  - body: So, a little background. My kids play baseball and softball (ages 8 and 10). While I’m not an official coach, I help ru…
  - axes: story_potential=0.30 emotional_pull=0.60 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.450
  - reason: 虽然情感张力较高且真实性强，但缺乏后续展开潜力，题材也较为普通，不符合追踪标准。

### r/offmychest (en fail, 5 筆)

- **[10695]** I don’t want to live anymore
  - body: And I can’t do shit about it. I can’t do it to my family, it would break them. At least I don’t have children, and I’ll…
  - axes: story_potential=0.30 emotional_pull=0.80 grassroots=0.90 novelty=0.10 authenticity=0.80  →  verdict=skip  score=0.550
  - reason: 雖然情緒張力高且真實感強，但缺乏事件展開潛力，且題材常見無新意，難以吸引長期追蹤。
- **[13503]** one of my classmates died
  - body: i don't know why i'm so upset about it i didn't even know him that well but it's been on my mind all day. he was too ki…
  - axes: story_potential=0.30 emotional_pull=0.70 grassroots=0.90 novelty=0.20 authenticity=0.80  →  verdict=skip  score=0.500
  - reason: 雖然情緒拉力強且真實性高，但缺乏後續發展潛力且題材較為常見，無法達到追蹤標準。
- **[16585]** I am a straight male but I want to marry a yuri(lesbian)
  - body: It's not that I am not attracted to the straight girls but it's a desire that I marry a lesbian and I am aware that it …
  - axes: story_potential=0.30 emotional_pull=0.40 grassroots=0.90 novelty=0.60 authenticity=0.80  →  verdict=skip  score=0.350
  - reason: 雖然題材有點新奇且作者看起來是真實用戶，但缺乏事件發展潛力和足夠的情緒拉力，難以吸引持續關注。
- **[11023]** He always breaks his promise 💔
  - body: ​ "He promises me every single time that he'll change for me , but even after 1 year he's still the same. He always bre…
  - axes: story_potential=0.30 emotional_pull=0.60 grassroots=0.80 novelty=0.20 authenticity=0.70  →  verdict=skip  score=0.450
  - reason: 雖然情感張力較高且真實性不錯，但缺乏事件展開潛力且題材較為常見，難以吸引持續關注。
- **[16450]** As a gay man, I admire lesbians
  - body: There are a lot of things I feel lesbians do better than gay men. Gay community is full of exclusion, and is sad. Gays …
  - axes: story_potential=0.30 emotional_pull=0.60 grassroots=0.90 novelty=0.40 authenticity=0.80  →  verdict=skip  score=0.450
  - reason: 雖然情感真實且具反思性，但缺乏事件性發展潛力，且題材較常見，難以吸引持續追蹤。
