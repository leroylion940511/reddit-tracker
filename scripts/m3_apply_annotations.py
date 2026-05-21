"""把 Opus（agent）作為人工標記者的判斷寫進 m3_annotations.json。

每筆都附 manual_verdict + manual_reason；判斷依 reddit_tracker_proposal.md §4.2
研究命題（素人爆文發現），對「真實個人事件 + 後續發展潛力」嚴格把關：

- track：真實個人經歷、有未決張力或明確敘事主體、能想像有後續更新
- skip：純問答、純討論 / 觀點、新聞轉貼、推廣 / 廣告、單張照片、語言學習諮詢

用法：
    uv run python scripts/m3_apply_annotations.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# (candidate_id, manual_verdict, manual_reason)
ANNOTATIONS: list[tuple[int, str, str]] = [
    (176, "skip",  "詢問版規 (是否能發尋人啟事)；雖背後有個人焦慮但貼文本身是 meta 問題、不是事件敘事"),
    (163, "skip",  "純政治觀點長文，無個人事件，標準 essay"),
    (111, "skip",  "純諮詢『有人從美國搬港嗎』，無個人敘事內容"),
    (241, "skip",  "語言學習趣味問題（520=I love you），純 trivia，無事件主體"),
    (281, "skip",  "夾帶 Preply 教師推廣連結（個人課程），輕度自我推銷"),
    (101, "track", "真實求助：14歲親人連兩年無法升學、家長偏好回中學 vs VTC，有明確個人困境與後續路徑選擇"),
    (100, "skip",  "信用卡年費的小抱怨；貼文內 EDIT 已自行解決，故事已 closed"),
    (142, "skip",  "純文化哲思（中國文化核心是什麼），互動極低、無敘事"),
    (153, "skip",  "對美國人無知的諷刺笑話段子，無個人事件"),
    (110, "skip",  "純旅遊安全諮詢『五月底適合來嗎』"),
    (290, "track", "TIFU 經典：學印度髒話罵詐騙電話 → 反被狂打 70+ 通；情況進行中、後續是否能擋住有明確懸念"),
    (335, "track", "TIFU 教堂下跪撞傷小腿 + 後續『then somehow I made it worse』明示未完，自述個人事件"),
    (81,  "track", "妻子在台被歧視（老婦人多次衝突），尋求法律 / 應對建議，事件反覆中，後續發展可期"),
    (53,  "skip",  "詢問日式三溫暖文化（為何放成人台），純 trivia 問題"),
    (331, "track", "TIFU 男友送花到 Sephora 反被誤認為偷東西，完整事件敘事、實際發生在自身"),
    (44,  "track", "極嚴重個人危機：被下藥性侵後懷孕、尋找台北醫療資源；高度真實 + 急迫 + 顯然會有後續"),
    (314, "track", "TIFU 白褲被神秘污漬玷污、22 分鐘內要 Q2 review；極強懸念、開放結尾"),
    (316, "track", "TIFU 借錢給哥哥老婆保釋（疑似被警察騙），錢還沒追回，事件進行中"),
    (41,  "skip",  "高雄車站設施介紹照片貼文（純介紹，無敘事或事件）"),
    (78,  "skip",  "AskReddit 式徵詢『遇過什麼台灣人刻板印象』，純討論題，無個人事件"),
    (208, "skip",  "淡江大橋夜景照片貼文，無敘事"),
    (246, "skip",  "兩個月準備 HSK4 可行嗎，純考試諮詢"),
    (145, "skip",  "新聞轉貼（川普媳婦讚美中國）；OP 非當事人，只是搬運"),
    (259, "skip",  "中文教學 trivia + YouTube 自我推廣連結"),
    (91,  "skip",  "電影討論散文（王家衛重慶森林氛圍），無個人事件"),
    (266, "skip",  "輸入法改良點子討論；雖然互動高但本質是觀點 / 提案、無敘事事件"),
    (40,  "skip",  "個人交友請求（台中找女友），無事件"),
    (61,  "skip",  "AskReddit 式論點題『台灣生活標準是否全球最高』，純觀點討論"),
    (64,  "skip",  "新聞快訊（台灣旅行誌奪 Booker），公告式 + OP 非當事人"),
    (90,  "skip",  "新聞外連（南亞男子在 MTR 摳腳皮）+ 一句嘲諷，無個人敘事"),
]


def main() -> int:
    path = Path("docs/m3_annotations.json")
    data = json.loads(path.read_text())
    by_id = {row["candidate_id"]: row for row in data}

    missing = [cid for cid, _, _ in ANNOTATIONS if cid not in by_id]
    if missing:
        print(f"⚠️  annotation 對不到 candidate_id: {missing}")

    for cid, verdict, reason in ANNOTATIONS:
        if cid not in by_id:
            continue
        by_id[cid]["manual_verdict"] = verdict
        by_id[cid]["manual_reason"] = reason

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    n_done = sum(1 for row in data if row.get("manual_verdict") in ("track", "skip"))
    print(f"applied {n_done} / {len(data)} annotations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
