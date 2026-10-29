"""日報的網頁版（單一自含 HTML）與 Telegram 精選文字。"""

from __future__ import annotations

from datetime import date
from html import escape

from ..models import DailyArticle, DailyEdition
from .writer import KIND_LABELS

WEEKDAYS = "一二三四五六日"
# MVP 只做頭版＋台灣、國際、科技三個內版（手冊 1.3）；其他版留在選單，沒稿時寫「本版未開放」。
MVP_SECTIONS = ("taiwan", "world", "tech")
TELEGRAM_LIMIT = 3_900

_CSS = """
:root{--bg:#f7f4ee;--paper:#fffdf8;--ink:#1d1b18;--muted:#6b645a;--rule:#d9d2c5;--accent:#8a1c1c;--tag:#efe8da}
@media (prefers-color-scheme:dark){:root{--bg:#141311;--paper:#1c1a17;--ink:#ece6da;--muted:#a59d8f;--rule:#3a352e;--accent:#e07a6a;--tag:#2a2621}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.75 "Noto Serif TC","PingFang TC","Songti TC",serif}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px 48px;background:var(--paper)}
header.mast{text-align:center;padding:28px 0 12px;border-bottom:3px double var(--ink)}
header.mast h1{margin:0;font-size:clamp(30px,6vw,52px);letter-spacing:.12em}
header.mast .meta{color:var(--muted);font-size:14px;margin-top:6px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:center;padding:10px 0;border-bottom:1px solid var(--rule);font:15px/1.4 system-ui,sans-serif}
nav a{color:var(--ink);text-decoration:none}nav a:hover{color:var(--accent)}
.market{display:flex;flex-wrap:wrap;gap:8px 24px;justify-content:center;padding:8px 0;border-bottom:1px solid var(--rule);font:14px/1.4 system-ui,sans-serif;color:var(--muted)}
.market b{color:var(--ink)}.down{color:#2e7d32}.up{color:#c62828}
h2.section{font-size:22px;margin:32px 0 8px;padding-bottom:4px;border-bottom:2px solid var(--ink)}
.front{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0 32px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0 32px}
article{padding:16px 0;border-bottom:1px solid var(--rule)}
article h3{font-size:21px;line-height:1.4;margin:0 0 6px}
.front article:first-child{grid-column:1/-1}.front article:first-child h3{font-size:30px}
.deck{color:var(--muted);margin:0 0 8px;font-weight:600}
.tag{display:inline-block;font:12px/1.6 system-ui,sans-serif;background:var(--tag);color:var(--accent);padding:0 8px;border-radius:3px;margin-right:6px;vertical-align:middle}
article p{margin:0 0 10px}.why{font-size:15px;color:var(--muted)}
details{font:13px/1.6 system-ui,sans-serif;color:var(--muted)}details a{color:var(--muted);word-break:break-all}
.empty{color:var(--muted);font-style:italic;padding:12px 0}
footer{margin-top:40px;padding-top:16px;border-top:3px double var(--ink);font:13px/1.7 system-ui,sans-serif;color:var(--muted)}
"""


def edition_title(edition_date: date) -> str:
    return f"{edition_date.year} 年 {edition_date.month} 月 {edition_date.day} 日 星期{WEEKDAYS[edition_date.weekday()]}"


def _paragraphs(text: str) -> str:
    return "".join(f"<p>{escape(part.strip())}</p>" for part in text.split("\n") if part.strip())


def _article_html(article: DailyArticle) -> str:
    tags = []
    if KIND_LABELS.get(article.kind):
        tags.append(KIND_LABELS[article.kind])
    if article.writer == "template":
        tags.append("摘要整理")
    tag_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags)
    sources = "".join(
        f'<li>{escape(s["outlet"])}｜<a href="{escape(s["url"], quote=True)}" rel="noopener">{escape(s["title"])}</a></li>'
        for s in article.sources
    )
    deck = f'<p class="deck">{escape(article.deck)}</p>' if article.deck and article.writer != "template" else ""
    why = f'<p class="why">為什麼重要：{escape(article.why_it_matters)}</p>' if article.why_it_matters else ""
    return (
        f"<article><h3>{tag_html}{escape(article.headline)}</h3>{deck}{_paragraphs(article.body)}{why}"
        f"<details><summary>來源（{len(article.sources)}）</summary><ul>{sources}</ul></details></article>"
    )


def _market_html(market: list[dict] | None) -> str:
    if not market:
        return ""
    cells = []
    for row in market:
        css = "down" if row["change"].startswith("-") else "up"
        cells.append(
            f'<span>{escape(row["name"])} <b>{escape(row["close"])}</b> '
            f'<span class="{css}">{escape(row["change"])}（{escape(row["change_pct"])}）</span></span>'
        )
    date_note = f'<span>證交所 {escape(market[0]["date"] or "")} 收盤</span>'
    return f'<div class="market">{"".join(cells)}{date_note}</div>'


def render_html(edition: DailyEdition, sections: dict[str, str]) -> str:
    articles = edition.articles
    front = sorted((a for a in articles if a.is_front), key=lambda a: a.position)
    nav = "".join(f'<a href="#{key}">{escape(label)}</a>' for key, label in sections.items() if key != "data")
    blocks = []
    for key, label in sections.items():
        if key == "data":
            continue
        items = sorted((a for a in articles if a.section == key and not a.is_front), key=lambda a: a.position)
        empty = "本版今日無新稿。" if key in MVP_SECTIONS else "本版未開放。"
        inner = "".join(_article_html(a) for a in items) or f'<p class="empty">{empty}</p>'
        blocks.append(f'<h2 class="section" id="{key}">{escape(label)}</h2><div class="grid">{inner}</div>')
    stats = edition.stats or {}
    title = f"AI 綜合日報｜{edition.edition_date.isoformat()}"
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{escape(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header class="mast"><h1>AI 綜合日報</h1><div class="meta">{edition_title(edition.edition_date)}｜試刊號｜本期 {len(articles)} 則</div></header>
<nav><a href="#front">頭版</a>{nav}</nav>
{_market_html(stats.get("market"))}
<h2 class="section" id="front">頭版</h2><div class="front">{"".join(_article_html(a) for a in front)}</div>
{"".join(blocks)}
<footer>
<p>本報由 AI 協作編採：程式依獨立出處數、官方來源、時效與升溫速度選題，AI 依各家媒體的標題與摘要撰稿，未讀取全文、未做現場採訪。每則附原始來源，請以原文為準。</p>
<p>標示「單一來源」者目前僅一家媒體報導；「社群觀察」為網路討論，不代表整體民意，亦非已證實的事實；「摘要整理」為未經 AI 改寫的來源摘要。</p>
<p>素材收集 {escape(str(stats.get("candidate_clusters", "—")))} 個事件｜AI 撰稿 {escape(str(stats.get("ai_articles", stats.get("gemini_articles", 0))))} 則｜摘要整理 {escape(str(stats.get("template_articles", 0)))} 則</p>
</footer></div></body></html>
"""


def telegram_digest(edition: DailyEdition, sections: dict[str, str]) -> str:
    front = sorted((a for a in edition.articles if a.is_front), key=lambda a: a.position)
    lines = [f"📰 AI 綜合日報｜{edition_title(edition.edition_date)}", "", "【頭版】"]
    for article in front:
        lines.append(f"{article.position}. {article.headline}")
        if article.deck and article.writer != "template":
            lines.append(f"   {article.deck}")
    counts = []
    for key, label in sections.items():
        count = sum(1 for a in edition.articles if a.section == key and not a.is_front)
        if key != "data" and count:
            counts.append(f"{label} {count}")
    lines += ["", "各版：" + "｜".join(counts), "", "完整報紙請開啟下方 HTML 檔（含所有文章與來源連結）。"]
    market = (edition.stats or {}).get("market")
    if market:
        lines.insert(2, "　".join(f"{m['name']} {m['close']}（{m['change_pct']}）" for m in market))
        lines.insert(3, "")
    text = "\n".join(lines)
    return text if len(text) <= TELEGRAM_LIMIT else text[: TELEGRAM_LIMIT - 1] + "…"
