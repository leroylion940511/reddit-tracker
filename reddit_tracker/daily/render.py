"""日報的網頁版（單一自含 HTML）與 Telegram 精選文字。"""

from __future__ import annotations

import re
from datetime import date
from html import escape
from zoneinfo import ZoneInfo

from ..collection.clustering import domain_of
from ..collection.normalize import canonicalize_url
from ..config import get_settings
from .market import STALE_LABEL, is_stale
from .view import BRIEF, FULL, LINK, EditionView, ViewArticle
from .writer import KIND_LABELS, PREPRINT_LABEL, PREPRINT_OUTLETS

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
.market b{color:var(--ink)}.market .stale{color:var(--accent);font-weight:600}.down{color:#2e7d32}.up{color:#c62828}
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
.brief h3{font-size:17px}.brief .deck,.brief .why,.brief p{display:none}
.link-only{font:15px/1.6 system-ui,sans-serif}
.sources{list-style:none;padding:0;margin:8px 0 0;font:13px/1.6 system-ui,sans-serif;color:var(--muted)}
.sources a{color:var(--muted)}
.withheld{font:13px system-ui,sans-serif;color:var(--accent)}
footer{margin-top:40px;padding-top:16px;border-top:3px double var(--ink);font:13px/1.7 system-ui,sans-serif;color:var(--muted)}
@media (max-width:420px){
  .front,.grid{display:block}
  .wrap,article,h3,p{overflow-wrap:anywhere}
  body{overflow-x:hidden}
}
"""

_CITE = re.compile(r"\[(?:S)?(\d+)\]")


def edition_title(edition_date: date) -> str:
    return f"{edition_date.year} 年 {edition_date.month} 月 {edition_date.day} 日 星期{WEEKDAYS[edition_date.weekday()]}"


def _preprint_only(article: ViewArticle) -> bool:
    urls = [s.get("url") or "" for s in article.sources or []]
    return bool(urls) and all(domain_of(canonicalize_url(u)) in PREPRINT_OUTLETS for u in urls)


def _cite(text: str, anchor: str, n_sources: int) -> str:
    def repl(match: re.Match) -> str:
        number = int(match.group(1))
        if 1 <= number <= n_sources:
            return f'<a href="#{anchor}-{number}">[{number}]</a>'
        return match.group(0)

    cited = _CITE.sub(repl, escape(text))
    if n_sources and "<a href=" not in cited:
        links = "".join(f'<a href="#{anchor}-{i}">[{i}]</a>' for i in range(1, n_sources + 1))
        cited = f"{cited} {links}"
    return cited


def _paragraphs(text: str, anchor: str, n_sources: int) -> str:
    return "".join(
        f"<p>{_cite(part.strip(), anchor, n_sources)}</p>" for part in text.split("\n") if part.strip()
    )


def _source_list(article: ViewArticle, anchor: str) -> str:
    items = []
    for index, source in enumerate(article.sources, start=1):
        when = source.get("published_at") or ""
        title = source.get("title") or ""
        url = source.get("url") or ""
        outlet = source.get("outlet") or ""
        link = f'<a href="{escape(url, quote=True)}" rel="noopener">{escape(title)}</a>' if url else escape(title)
        items.append(f'<li id="{anchor}-{index}">{escape(outlet)}｜{link}' + (f"｜{escape(when)}" if when else "") + "</li>")
    return f'<ul class="sources">{"".join(items)}</ul>' if items else ""


def _article_html(article: ViewArticle) -> str:
    anchor = f"s{article.story_id or article.position}-{article.section}"
    tags = []
    if article.withheld:
        tags.append("未核准")
    elif _preprint_only(article):
        tags.append(PREPRINT_LABEL)
    elif KIND_LABELS.get(article.kind):
        tags.append(KIND_LABELS[article.kind])
    if article.writer == "template" and not article.withheld:
        tags.append("摘要整理")
    tag_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags)
    css = "brief" if article.display == BRIEF else ("link-only" if article.display == LINK else "")
    if article.display == LINK:
        label = article.link_label or article.headline
        return (
            f'<article class="link-only" id="story-{article.story_id}">'
            f'<p>{tag_html}<a href="#story-{article.story_id}">{escape(label)}</a>（見頭版）</p></article>'
        )
    if article.withheld:
        return (
            f'<article class="brief" id="story-{article.story_id}"><h3>{tag_html}{escape(article.headline)}</h3>'
            f'<p class="withheld">未核准，本期不發行全文。</p></article>'
        )
    deck = f'<p class="deck">{escape(article.deck)}</p>' if article.deck and article.writer != "template" else ""
    why = f'<p class="why">為什麼重要：{escape(article.why_it_matters)}</p>' if article.why_it_matters else ""
    klass = f' class="{css}"' if css else ""
    return (
        f'<article{klass} id="story-{article.story_id}"><h3>{tag_html}{escape(article.headline)}</h3>{deck}'
        f"{_paragraphs(article.body, anchor, len(article.sources))}{why}{_source_list(article, anchor)}</article>"
    )


def market_stale(market: list[dict] | None, edition_date: date) -> bool:
    return bool(market) and any(is_stale(row.get("date"), edition_date) for row in market)


def _market_html(market: list[dict] | None, edition_date: date) -> str:
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
    if market_stale(market, edition_date):
        date_note += f'<span class="stale">{STALE_LABEL}</span>'
    return f'<div class="market">{"".join(cells)}{date_note}</div>'


def _mast_meta(view: EditionView) -> str:
    issue = f"第 {view.issue_number} 期" if view.issue_number else "試刊號"
    when = ""
    if view.published_at is not None:
        tz = ZoneInfo(get_settings().newsroom_delivery_timezone)
        local = view.published_at.astimezone(tz)
        when = f"｜{local.strftime('%Y-%m-%d %H:%M')} 出刊"
    count = sum(1 for a in view.articles if a.display == FULL or a.is_front)
    return f"{edition_title(view.edition_date)}｜{issue}{when}｜本期 {count} 則"


def render_html(view: EditionView) -> str:
    """只吃 `EditionView`。版位來自 page_plans，不直接讀 scoring 的順序。"""
    sections = view.sections
    front = [a for a in view.articles if a.is_front]
    nav = "".join(f'<a href="#{key}">{escape(label)}</a>' for key, label in sections.items() if key != "data")
    blocks = []
    for key, label in sections.items():
        if key == "data":
            continue
        items = [a for a in view.articles if a.section == key and not a.is_front]
        if items:
            note = '<p class="empty">本版今日稿量較少</p>' if 0 < len(items) < 2 and key in MVP_SECTIONS else ""
            inner = note + "".join(_article_html(a) for a in items)
        else:
            empty = "本版今日無新稿。" if key in MVP_SECTIONS else "本版未開放。"
            inner = f'<p class="empty">{empty}</p>'
        blocks.append(f'<h2 class="section" id="{key}">{escape(label)}</h2><div class="grid">{inner}</div>')
    stats = view.stats or {}
    title = f"AI 綜合日報｜{view.edition_date.isoformat()}"
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{escape(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header class="mast"><h1>AI 綜合日報</h1><div class="meta">{_mast_meta(view)}</div></header>
<nav><a href="#front">頭版</a>{nav}</nav>
{_market_html(view.market if view.market is not None else stats.get("market"), view.edition_date)}
<h2 class="section" id="front">頭版</h2><div class="front">{"".join(_article_html(a) for a in front)}</div>
{"".join(blocks)}
<footer>
<p>本報由 AI 協作編採：程式依獨立出處數、官方來源、時效與升溫速度選題，AI 依各家媒體的標題與摘要撰稿，未讀取全文、未做現場採訪。每則附原始來源，請以原文為準。</p>
<p>標示「單一來源」者目前僅一家媒體報導；「社群觀察」為網路討論，不代表整體民意，亦非已證實的事實；「摘要整理」為未經 AI 改寫的來源摘要。「多來源」只計算獨立來源，轉載併成一列。</p>
<p>素材收集 {escape(str(stats.get("candidate_clusters", "—")))} 個事件｜AI 撰稿 {escape(str(stats.get("ai_articles", stats.get("gemini_articles", 0))))} 則｜摘要整理 {escape(str(stats.get("template_articles", 0)))} 則</p>
</footer></div></body></html>
"""


def render_index(editions: list[tuple[date, str]]) -> str:
    items = "".join(
        f'<li><a href="{escape(name, quote=True)}">{escape(edition_title(day))}</a></li>' for day, name in editions
    )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 綜合日報｜期號</title><style>{_CSS}</style></head>
<body><div class="wrap"><header class="mast"><h1>AI 綜合日報</h1><div class="meta">歷史期號</div></header>
<ul class="sources">{items or "<li>尚無期號</li>"}</ul></div></body></html>
"""


def telegram_digest(view: EditionView) -> str:
    front = [a for a in view.articles if a.is_front and not a.withheld]
    lines = [f"📰 AI 綜合日報｜{edition_title(view.edition_date)}", "", "【頭版】"]
    for article in front:
        lines.append(f"{article.position}. {article.headline}")
        if article.deck and article.writer != "template":
            lines.append(f"   {article.deck}")
    counts = []
    for key, label in view.sections.items():
        count = sum(1 for a in view.articles if a.section == key and not a.is_front and a.display == FULL)
        if key != "data" and count:
            counts.append(f"{label} {count}")
    lines += ["", "各版：" + "｜".join(counts), "", "完整報紙請開啟下方 HTML 檔（含所有文章與來源連結）。"]
    market = view.market if view.market is not None else (view.stats or {}).get("market")
    if market:
        line = "　".join(f"{m['name']} {m['close']}（{m['change_pct']}）" for m in market)
        if market_stale(market, view.edition_date):
            line += f"　⚠️{STALE_LABEL}（{market[0].get('date') or '日期不明'} 收盤）"
        lines.insert(2, line)
        lines.insert(3, "")
    text = "\n".join(lines)
    return text if len(text) <= TELEGRAM_LIMIT else text[: TELEGRAM_LIMIT - 1] + "…"


def write_history_index(site_dir) -> None:
    from pathlib import Path

    root = Path(site_dir)
    pages = []
    for path in sorted(root.glob("*.html")):
        if path.name == "index.html":
            continue
        try:
            pages.append((date.fromisoformat(path.stem), path.name))
        except ValueError:
            continue
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(render_index(pages), encoding="utf-8")
