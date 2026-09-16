"""Read-only presentation for a drafted newsroom edition.

The renderer creates an offline HTML newsroom and a Telegram-like text preview.
Neither function sends network traffic or exposes private prompts/reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AgentArtifactRecord,
    AgentArtifactSource,
    AgentRun,
    CandidatePost,
    EditionItem,
    EditionItemSource,
    NewsroomEdition,
    ReaderProfile,
)


STAGE_LABELS = {
    "reader_profile": "讀者檔案 agent",
    "scout": "採訪 agent",
    "assignment": "選題主編",
    "verification": "脈絡查核 agent",
    "writing": "撰稿 agent",
    "chief_editing": "總編輯 agent",
    "learning": "學習 agent",
}
KIND_LABELS = {"brief": "短報", "feature": "專題", "breaking": "早報快訊"}


@dataclass(frozen=True)
class SourceView:
    original_title: str
    subreddit: str
    permalink: str


@dataclass(frozen=True)
class ItemView:
    position: int
    kind: str
    headline_zh: str
    body_zh: str
    why_it_matters: str
    confidence: str | None
    warnings: list[str]
    sources: list[SourceView]


@dataclass(frozen=True)
class ArtifactView:
    stage: str
    status: str
    attempt: int
    summary: str | None
    error_message: str | None
    sources: list[SourceView]


@dataclass(frozen=True)
class EditionView:
    edition_date: str
    reader_summary: str
    items: list[ItemView]
    artifacts: list[ArtifactView]


def load_edition_view(session: Session, *, edition: NewsroomEdition) -> EditionView:
    """Load a display projection without depending on stale ORM collections."""
    reader = session.get(ReaderProfile, edition.reader_profile_id)
    if reader is None:
        raise ValueError("edition reader profile is missing")
    items = list(session.scalars(
        select(EditionItem)
        .where(EditionItem.edition_id == edition.id)
        .order_by(EditionItem.position.asc())
    ).all())
    item_source_rows = session.execute(
        select(EditionItemSource, CandidatePost)
        .join(CandidatePost, EditionItemSource.candidate_post_id == CandidatePost.id)
        .where(EditionItemSource.edition_item_id.in_([item.id for item in items] or [-1]))
        .order_by(EditionItemSource.source_order.asc())
    ).all()
    sources_by_item: dict[int, list[SourceView]] = {item.id: [] for item in items}
    for bridge, candidate in item_source_rows:
        sources_by_item[bridge.edition_item_id].append(_source_view(candidate))

    runs = list(session.scalars(
        select(AgentRun).where(AgentRun.edition_id == edition.id).order_by(AgentRun.id.asc())
    ).all())
    artifacts = list(session.scalars(
        select(AgentArtifactRecord)
        .join(AgentRun, AgentArtifactRecord.agent_run_id == AgentRun.id)
        .where(AgentRun.edition_id == edition.id)
        .order_by(AgentArtifactRecord.id.asc())
    ).all())
    artifact_source_rows = session.execute(
        select(AgentArtifactSource, CandidatePost)
        .join(CandidatePost, AgentArtifactSource.candidate_post_id == CandidatePost.id)
        .where(AgentArtifactSource.agent_artifact_id.in_([artifact.id for artifact in artifacts] or [-1]))
        .order_by(AgentArtifactSource.source_order.asc())
    ).all()
    sources_by_artifact: dict[int, list[SourceView]] = {artifact.id: [] for artifact in artifacts}
    for bridge, candidate in artifact_source_rows:
        sources_by_artifact[bridge.agent_artifact_id].append(_source_view(candidate))
    artifact_by_run = {artifact.agent_run_id: artifact for artifact in artifacts}

    reader_summary = reader.preference_prompt or "依預設綜合版面編採。"
    return EditionView(
        edition_date=edition.edition_date.isoformat(),
        reader_summary=reader_summary,
        items=[
            ItemView(
                position=item.position,
                kind=item.kind,
                headline_zh=item.headline_zh or "（尚無標題）",
                body_zh=item.body_zh or "（尚無稿件）",
                why_it_matters=item.why_it_matters or "（尚無編輯按語）",
                confidence=item.confidence,
                warnings=list(item.warnings or []),
                sources=sources_by_item[item.id],
            )
            for item in items
        ],
        artifacts=[
            ArtifactView(
                stage=run.stage,
                status=run.status,
                attempt=run.attempt,
                summary=artifact_by_run[run.id].summary if run.id in artifact_by_run else None,
                error_message=run.error_message,
                sources=sources_by_artifact.get(artifact_by_run[run.id].id, []) if run.id in artifact_by_run else [],
            )
            for run in runs
        ],
    )


def _source_view(candidate: CandidatePost) -> SourceView:
    permalink = candidate.permalink or f"/r/{candidate.subreddit}/comments/{candidate.reddit_post_id}/"
    if not permalink.startswith(("https://", "http://")):
        permalink = f"https://www.reddit.com/{permalink.lstrip('/')}"
    return SourceView(
        original_title=candidate.title or "（原帖未提供標題）",
        subreddit=candidate.subreddit,
        permalink=permalink,
    )


def render_telegram_preview(view: EditionView) -> str:
    """Render a network-free preview of the Telegram newspaper payload."""
    lines = [
        f"🗞️ AI 編輯室每日報｜{view.edition_date}",
        "台灣讀者版・示範 preview（尚未發送）",
        "",
    ]
    for item in view.items:
        kind = KIND_LABELS.get(item.kind, item.kind)
        lines.extend([
            f"{item.position}. 【{kind}】{item.headline_zh}",
            item.why_it_matters,
            f"來源：{', '.join(f'r/{source.subreddit}' for source in item.sources)}",
            "❤️ 多看這類　🚫 少看這類　👀 追後續",
            "",
        ])
    return "\n".join(lines).rstrip()


def render_html(view: EditionView) -> str:
    """Render an offline newsroom page with only inspectable artifacts."""
    article_cards = "\n".join(_render_item(item) for item in view.items)
    artifact_cards = "\n".join(_render_artifact(artifact) for artifact in view.artifacts)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 編輯室每日報｜{escape(view.edition_date)}</title>
  <style>
    :root {{ color-scheme: dark; --ink:#eef4fa; --muted:#9eb0c2; --paper:#101925; --card:#172332; --line:#2b4155; --accent:#68d7bb; --yellow:#f6ca66; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:linear-gradient(135deg,#0b111a,#172236); color:var(--ink); font:16px/1.65 system-ui,-apple-system,"Noto Sans TC",sans-serif; }}
    main {{ width:min(1060px,calc(100% - 2rem)); margin:0 auto; padding:3rem 0 5rem; }}
    header {{ border-bottom:1px solid var(--line); padding:0 0 1.5rem; margin-bottom:2rem; }} .eyebrow {{ color:var(--accent); font-size:.85rem; letter-spacing:.08em; text-transform:uppercase; }} h1 {{ font-size:clamp(2rem,6vw,4rem); line-height:1.08; margin:.4rem 0; letter-spacing:-.05em; }} .lede {{ color:var(--muted); max-width:48rem; }}
    .grid {{ display:grid; grid-template-columns:minmax(0,1.7fr) minmax(18rem,.8fr); gap:2rem; }} h2 {{ margin:0 0 1rem; font-size:1.15rem; }} .card {{ background:color-mix(in srgb,var(--card) 90%,transparent); border:1px solid var(--line); border-radius:16px; padding:1.25rem; margin-bottom:1rem; }} .tag {{ color:var(--yellow); font-size:.78rem; font-weight:700; letter-spacing:.06em; }} h3 {{ margin:.25rem 0 .5rem; font-size:1.25rem; line-height:1.35; }} .body {{ white-space:pre-wrap; color:#d6e0ea; }} .why {{ color:var(--accent); font-size:.92rem; }} .warning {{ color:#ffd79a; font-size:.86rem; }}
    .sources {{ margin:.8rem 0 0; padding:0; list-style:none; }} .sources li {{ margin:.25rem 0; font-size:.86rem; }} a {{ color:#92caff; }} .agent {{ border-left:3px solid var(--accent); }} .agent.failed {{ border-left-color:#f18a8a; }} .agent small {{ color:var(--muted); }} code {{ color:#c5d7e8; }}
    @media (max-width:760px) {{ main {{ width:min(100% - 1.2rem,1060px); padding-top:1.5rem; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <header><div class="eyebrow">Offline demo · no external API · source transparent</div><h1>AI 編輯室每日報</h1><p class="lede">{escape(view.edition_date)}｜讀者設定：{escape(view.reader_summary)}</p></header>
  <div class="grid"><section><h2>今日報紙</h2>{article_cards}</section><aside><h2>編輯室紀錄</h2>{artifact_cards}</aside></div>
</main></body></html>"""


def _render_item(item: ItemView) -> str:
    warnings = "".join(f"<p class=\"warning\">⚠️ {escape(warning)}</p>" for warning in item.warnings)
    return f"""<article class="card">
  <div class="tag">{item.position:02d} · {escape(KIND_LABELS.get(item.kind, item.kind))} · 信心 {escape(item.confidence or '未標示')}</div>
  <h3>{escape(item.headline_zh)}</h3><div class="body">{escape(item.body_zh)}</div>
  <p class="why">為什麼值得看：{escape(item.why_it_matters)}</p>{warnings}{_render_sources(item.sources)}
</article>"""


def _render_artifact(artifact: ArtifactView) -> str:
    label = STAGE_LABELS.get(artifact.stage, artifact.stage)
    status = "failed" if artifact.status == "failed" else ""
    summary = artifact.error_message or artifact.summary or "此 stage 未產生可展示 artifact。"
    return f"""<section class="card agent {status}"><strong>{escape(label)}</strong><small> · {escape(artifact.status)} · attempt {artifact.attempt}</small>
  <p>{escape(summary)}</p>{_render_sources(artifact.sources)}</section>"""


def _render_sources(sources: list[SourceView]) -> str:
    if not sources:
        return ""
    rows = "".join(
        f"<li><a href=\"{escape(source.permalink, quote=True)}\">r/{escape(source.subreddit)}｜{escape(source.original_title)}</a></li>"
        for source in sources
    )
    return f"<ul class=\"sources\">{rows}</ul>"


__all__ = [
    "ArtifactView",
    "EditionView",
    "ItemView",
    "SourceView",
    "load_edition_view",
    "render_html",
    "render_telegram_preview",
]
