"""日報的網頁版（單一自含 HTML）與 Telegram 精選文字。"""

from __future__ import annotations

import re
from datetime import date, timezone
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
MULTI_SOURCE_LABEL = "多來源"

_CSS = """
:root{
  --bg:#e6e3da;--paper:#f6f5f1;--ink:#16181d;--muted:#5c6370;--rule:#ddd9cf;
  --seal:#b0112a;--wire:#0e4d82;--tag:#e7eef5;--alert:#9f1239;--alert-bg:#fde8ec;
  --rise:#c62828;--fall:#1b7a43;--why:#eef2f6;
  --serif:"Source Han Serif TC","思源宋體","Noto Serif TC","Noto Serif CJK TC","Songti TC","PMingLiU","Songti SC",serif;
  --sans:"PingFang TC","Noto Sans TC","Source Han Sans TC","Microsoft JhengHei","Heiti TC",sans-serif;
  color-scheme:light dark;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0c0e11;--paper:#16191e;--ink:#f3f0e8;--muted:#b7bdc7;--rule:#323842;
    --seal:#ff6b7a;--wire:#9ec4ea;--tag:#243044;--alert:#ffb3be;--alert-bg:#3a2228;
    --rise:#ff8d86;--fall:#8ee0ae;--why:#1e2731;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:18px/1.85 var(--serif)}
a:focus-visible{outline:2px solid var(--wire);outline-offset:2px}
.wrap{max-width:1040px;margin:0 auto;padding:0 18px 64px;background:var(--paper)}
header.mast{text-align:center;padding:32px 0 16px;border-bottom:6px solid var(--seal)}
header.mast h1{margin:0;font-size:clamp(36px,7vw,68px);letter-spacing:.06em;line-height:1.15;font-weight:700}
header.mast .date{margin:10px 0 0;font-family:var(--sans);font-size:17px;line-height:1.4}
header.mast .folio{margin:4px 0 0;font-family:var(--sans);font-size:15px;line-height:1.45;color:var(--muted)}
nav{display:flex;flex-wrap:wrap;gap:4px 16px;justify-content:center;padding:12px 0;border-bottom:1px solid var(--rule);font:16px/1.4 var(--sans)}
nav a{color:var(--ink);text-decoration:none;padding:4px 0}
nav a:hover{color:var(--wire)}
.market{display:flex;flex-wrap:wrap;gap:8px 22px;justify-content:center;padding:12px 0;border-bottom:1px solid var(--rule);font:15px/1.45 var(--sans);color:var(--muted)}
.market b{color:var(--ink);font-weight:700}
.market .stale{color:var(--alert);font-weight:700}
.down{color:var(--fall);font-weight:700}
.up{color:var(--rise);font-weight:700}
h2.section{display:flex;align-items:center;gap:10px;margin:40px 0 6px;padding:0;border:0;font-size:26px;line-height:1.3;font-weight:700}
h2.section::before{content:"";width:14px;height:.72em;background:var(--seal);flex:none}
.front{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 28px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 28px}
article{padding:18px 0 16px;border-bottom:1px solid var(--rule)}
article h3{font-size:22px;line-height:1.45;margin:0 0 8px;font-weight:700}
.front article:first-child{grid-column:1/-1}
.lead h3,.front article:first-child h3{font-size:clamp(28px,4vw,42px);line-height:1.28;margin-bottom:10px}
.lead .deck,.lead p,.front article:first-child p{max-width:34em}
.deck{margin:0 0 12px;font-family:var(--sans);font-size:18px;line-height:1.65;font-weight:600;color:var(--ink)}
.tag{display:inline-block;font:13px/1.5 var(--sans);font-weight:700;background:var(--tag);color:var(--wire);padding:1px 7px;margin:0 6px 0 0;vertical-align:middle}
.tag.alert{color:var(--alert);background:var(--alert-bg)}
article p{margin:0 0 12px}
article a{color:var(--wire)}
.why{font-family:var(--sans);font-size:16px;line-height:1.7;color:var(--ink);background:var(--why);border-left:3px solid var(--wire);padding:8px 12px;margin:4px 0 12px}
.empty{color:var(--muted);font-family:var(--sans);font-style:italic;padding:12px 0}
.brief h3{font-size:18px}
.brief .deck,.brief .why,.brief p{display:none}
.brief p.withheld{display:block}
.link-only{font:16px/1.6 var(--sans)}
.sources{list-style:none;padding:8px 0 0;margin:8px 0 0;border-top:1px solid var(--rule);font:14px/1.65 var(--sans);color:var(--muted)}
.sources a{color:var(--ink);word-break:break-word}
.sources .outlet{font-weight:700;color:var(--ink)}
.withheld{font:15px/1.6 var(--sans);font-weight:700;color:var(--alert);margin-top:6px}
.briefs{grid-column:1/-1;padding:14px 0;border-bottom:1px solid var(--rule)}
.briefs h3{font-family:var(--sans);font-size:18px;margin:0 0 8px}
.briefs ul{margin:0;padding-left:1.1em}
.briefs li{margin:6px 0;font-family:var(--sans);font-size:16px;line-height:1.55}
.briefs a{color:var(--ink)}
.briefs .src{color:var(--muted);font-size:14px}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--ink);font:14px/1.75 var(--sans);color:var(--muted)}
footer p{max-width:68em}
ol.index{list-style:none;margin:8px 0 0;padding:0}
ol.index li{border-bottom:1px solid var(--rule)}
ol.index a{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 16px;align-items:baseline;padding:16px 2px;text-decoration:none;color:var(--ink);font-size:20px;line-height:1.4}
ol.index a:hover{color:var(--wire)}
ol.index .day{font-family:var(--sans);font-size:14px;color:var(--muted)}
ol.index .empty{padding:16px 2px;font-family:var(--sans);color:var(--muted)}
@media (max-width:640px){
  body{font-size:18px;overflow-x:hidden}
  .wrap{padding:0 14px 72px}
  header.mast{padding:22px 0 12px}
  header.mast h1{letter-spacing:.03em}
  nav{flex-wrap:nowrap;justify-content:flex-start;overflow-x:auto;gap:0 18px;padding:10px 0 12px}
  nav a{flex:none}
  .front,.grid{display:block}
  .lead .deck,.lead p,.front article:first-child p{max-width:none}
  article h3{font-size:22px}
  .wrap,article,h3,p{overflow-wrap:anywhere}
}
"""

_CITE = re.compile(r"\[(?:S)?(\d+)\]")


def edition_title(edition_date: date) -> str:
    return f"{edition_date.year} 年 {edition_date.month} 月 {edition_date.day} 日 星期{WEEKDAYS[edition_date.weekday()]}"


def _preprint_only(article: ViewArticle) -> bool:
    urls = [s.get("url") or "" for s in article.sources or []]
    return bool(urls) and all(domain_of(canonicalize_url(u)) in PREPRINT_OUTLETS for u in urls)


def _cite(text: str, anchor: str, n_sources: int, *, fill: bool = True) -> str:
    def repl(match: re.Match) -> str:
        number = int(match.group(1))
        if 1 <= number <= n_sources:
            return f'<a href="#{anchor}-{number}">[{number}]</a>'
        return match.group(0)

    cited = _CITE.sub(repl, escape(text))
    if fill and n_sources and "<a href=" not in cited:
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
        when_html = f'｜<span class="when">{escape(when)}</span>' if when else ""
        items.append(
            f'<li id="{anchor}-{index}"><span class="outlet">{escape(outlet)}</span>｜{link}{when_html}</li>'
        )
    return f'<ul class="sources">{"".join(items)}</ul>' if items else ""


WITHHELD_LABELS = {
    "hold": ("暫扣", "本稿暫扣，本期不發行全文。"),
    "unapproved": ("未核准", "未核准，本期不發行全文。"),
}


def _withheld_label(article: ViewArticle) -> tuple[str, str]:
    """（標籤, 說明）。HOLD 寫「暫扣」；要核可而沒核可才寫「未核准」。沒有原因的舊呼叫端照舊寫未核准。"""
    return WITHHELD_LABELS.get(article.withheld_reason, WITHHELD_LABELS["unapproved"])


def _article_html(article: ViewArticle, *, lead: bool = False) -> str:
    anchor = f"s{article.story_id or article.position}-{article.section}"
    tags = []
    if article.withheld:
        tags.append(_withheld_label(article)[0])
    elif _preprint_only(article):
        tags.append(PREPRINT_LABEL)
    elif KIND_LABELS.get(article.kind):
        tags.append(KIND_LABELS[article.kind])
    elif article.kind == "report" and len(article.sources) >= 2:
        tags.append(MULTI_SOURCE_LABEL)  # 手冊 6.8：狀態標籤放在標題旁；來源列已把轉載併成一列，只算獨立來源
    if article.writer == "template" and not article.withheld:
        tags.append("摘要整理")
    tag_html = "".join(
        f'<span class="tag{" alert" if article.withheld else ""}">{escape(t)}</span>' for t in tags
    )
    css = "brief" if article.display == BRIEF else ("link-only" if article.display == LINK else "")
    classes = ["lead"] if lead else []
    if css:
        classes.append(css)
    if article.display == LINK:
        # 內版遇到頭版稿：只放標題連結到頭版那篇，不重印正文（手冊步驟 4）；連結本身不帶 id，避免和頭版重複
        # 連結文字一律用稿件標題；slot 的 label 是分版主編的內部角度，不給讀者看
        label = article.headline
        return (
            f'<article class="link-only">'
            f'<p>{tag_html}<a href="#{article.anchor}">{escape(label)}</a>（見頭版）</p></article>'
        )
    if article.withheld and "brief" not in classes:
        classes.append("brief")
    if article.withheld:
        inner = (
            f'<h3>{tag_html}{escape(article.headline)}</h3>'
            f'<p class="withheld">{escape(_withheld_label(article)[1])}</p>'
        )
    else:
        deck = f'<p class="deck">{escape(article.deck)}</p>' if article.deck and article.writer != "template" else ""
        why = (
            f'<p class="why">為什麼重要：{_cite(article.why_it_matters, anchor, len(article.sources), fill=False)}</p>'
            if article.why_it_matters else ""
        )
        inner = (
            f'<h3>{tag_html}{escape(article.headline)}</h3>{deck}'
            f"{_paragraphs(article.body, anchor, len(article.sources))}{why}{_source_list(article, anchor)}"
        )
    # article 只留 id：回歸測試要精確的 `<article id="story-N">`，class 放內層
    klass = " ".join(classes)
    if klass:
        inner = f'<div class="{klass}">{inner}</div>'
    return f'<article id="{article.anchor}">{inner}</article>'


def _section_briefs_html(briefs: list[dict] | None, sections: dict[str, str]) -> str:
    """其他版（科學、生活、文化、體育）的標題短訊：不呼叫 LLM、沒有正文，放在頭版（手冊步驟 4）。"""
    if not briefs:
        return ""
    items = "".join(
        f'<li><span class="tag">{escape(sections.get(b["section"], b["section"]))}</span>'
        + (f'<span class="tag">{escape(b["label"])}</span>' if b.get("label") else "")
        + f'<a href="{escape(b["url"], quote=True)}" rel="noopener">{escape(b["headline"])}</a>'
        f' <span class="src">（{escape(b["outlet"])}）</span></li>'
        for b in briefs
    )
    return f'<div class="briefs"><h3>短訊</h3><ul>{items}</ul></div>'


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
        stamp = view.published_at
        if stamp.tzinfo is None:  # SQLite 讀回來沒有時區，存的是 UTC；不補的話 08:35 會印成 00:35
            stamp = stamp.replace(tzinfo=timezone.utc)
        local = stamp.astimezone(tz)
        when = f"{local.strftime('%Y-%m-%d %H:%M')} 出刊"
    count = sum(1 for a in view.articles if a.display == FULL or a.is_front)
    folio = "｜".join(part for part in (issue, when, f"本期 {count} 則") if part)
    return (
        f'<p class="date">{escape(edition_title(view.edition_date))}</p>'
        f'<p class="folio">{escape(folio)}</p>'
    )


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
    ai_count, template_count = stats.get("ai_articles", stats.get("gemini_articles", 0)), stats.get("template_articles", 0)
    if not ai_count and not template_count:
        # M 組的 stats 不記撰稿數（稿在 story_versions）；照版面上有全文的稿數
        written = {a.story_id or id(a): a for a in view.articles if a.display == FULL and not a.withheld}
        template_count = sum(1 for a in written.values() if a.writer == "template")
        ai_count = len(written) - template_count
    title = f"AI 綜合日報｜{view.edition_date.isoformat()}"
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{escape(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header class="mast"><h1>AI 綜合日報</h1>{_mast_meta(view)}</header>
<nav><a href="#front">頭版</a>{nav}</nav>
{_market_html(view.market if view.market is not None else stats.get("market"), view.edition_date)}
<h2 class="section" id="front">頭版</h2><div class="front">{"".join(_article_html(a, lead=(i == 0)) for i, a in enumerate(front))}{_section_briefs_html(stats.get("briefs"), sections)}</div>
{"".join(blocks)}
<footer>
<p>本報由 AI 協作編採，依標題與摘要撰稿：程式依獨立出處數、官方來源、時效與升溫速度選題，AI 依各家媒體的標題與摘要撰稿，未讀取全文、未做現場採訪。每則附原始來源，請以原文為準。</p>
<p>標示「單一來源」者目前僅一家媒體報導；「社群觀察」為網路討論，不代表整體民意，亦非已證實的事實；「摘要整理」為未經 AI 改寫的來源摘要。「多來源」只計算獨立來源，轉載併成一列。</p>
<p>素材收集 {escape(str(stats.get("candidate_clusters", "—")))} 個事件｜AI 撰稿 {escape(str(ai_count))} 則｜摘要整理 {escape(str(template_count))} 則</p>
</footer></div></body></html>
"""


def render_index(editions: list[tuple[date, str]]) -> str:
    """最新一期排最上面。`editions` 來自檔名排序（舊到新），這裡只倒過來顯示。"""
    if not editions:
        items = '<li class="empty">尚無期號</li>'
    else:
        items = "".join(
            f'<li><a href="{escape(name, quote=True)}">'
            f'<span class="when">{escape(edition_title(day))}</span>'
            f'<span class="day">{escape(day.isoformat())}</span></a></li>'
            for day, name in reversed(editions)
        )
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>AI 綜合日報｜各期</title><style>{_CSS}</style></head>
<body><div class="wrap"><header class="mast"><h1>AI 綜合日報</h1><p class="folio">各期日報</p></header>
<ol class="index">{items}</ol></div></body></html>
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
        # 內版篇數含頭版稿的連結（頭版 6 則是從三內版 12 篇裡標記的）
        count = sum(1 for a in view.articles if a.section == key and not a.is_front and a.display in (FULL, LINK))
        if key != "data" and count:
            counts.append(f"{label} {count}")
    briefs = (view.stats or {}).get("briefs") or []
    if briefs:
        counts.append(f"短訊 {len(briefs)}")
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
