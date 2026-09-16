"""Run a complete, offline AI newsroom demo without touching v4 data/services.

Usage:
    uv run python -m reddit_tracker.newsroom.demo
    uv run python -m reddit_tracker.newsroom.demo --open
"""

from __future__ import annotations

import argparse
import webbrowser
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import gettempdir

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..models import Base, CandidatePost
from .planning import plan_edition, previous_calendar_day_window
from .rendering import load_edition_view, render_html, render_telegram_preview
from .repository import create_reader_profile, get_or_create_edition
from .writing import draft_edition


DEMO_EDITION_DATE = date(2026, 9, 17)
DEMO_POSTS = (
    ("d01", "relationship_advice", "My partner and I disagree about boundaries", "伴侶界線談不攏時，怎麼把話說開？", "我在關係裡遇到一個難以開口的界線問題，想知道別人的經驗。"),
    ("d02", "offmychest", "A friendship changed after a difficult conversation", "一次坦白對話，讓友情走向哪裡？", "一次坦白的對話讓我重新理解一段友情，也讓我猶豫是否做對了。"),
    ("d03", "taiwan", "A small Taiwan daily life surprise", "一個陌生人的善意，留在台灣日常裡", "在台灣日常生活裡遇到一個陌生人的好意，讓我記了一整天。"),
    ("d04", "taipei", "What makes a neighborhood feel like home", "一個社區，從什麼時候開始像家？", "搬到新社區後，我開始注意到鄰里互動如何改變一個人的歸屬感。"),
    ("d05", "askreddit", "What small habit changed your day", "哪些小習慣，真的改變了一天？", "大家分享那些看似很小、卻真的改變生活節奏的習慣。"),
    ("d06", "askreddit", "What online opinion surprised you most", "一個提問，翻出網路文化的意外共識", "一個看似普通的提問，引出許多人對網路文化的意外觀察。"),
    ("d07", "careerguidance", "How I handled an awkward job conversation", "工作裡最難談的，往往不是工作", "我試著處理工作中的尷尬溝通，結果比想像中更複雜。"),
    ("d08", "jobs", "A lesson from my first week at work", "第一週上班後，才明白的一件事", "第一週工作讓我學到一件沒有寫在職務說明裡的事。"),
    ("d09", "todayilearned", "An unexpectedly kind thing a stranger did", "陌生人的一個小舉動，改變了一天", "一個陌生人的小舉動，意外讓整天的心情都不同。"),
    ("d10", "casualconversation", "A small story that made people smile", "一段小插曲，讓留言區都笑了", "一個普通日常片段，卻讓留言區的人都想起自己的故事。"),
)


@dataclass(frozen=True)
class DemoResult:
    html_path: Path
    database_path: Path
    telegram_preview: str
    item_count: int
    artifact_count: int


def _default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path(gettempdir()) / f"reddit-newsroom-demo-{timestamp}.html"


def run_demo(*, output_path: Path, database_path: Path | None = None) -> DemoResult:
    """Create an isolated database, run all demo stages, and write an HTML report."""
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing demo output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    database_path = (database_path or output_path.with_suffix(".sqlite")).expanduser().resolve()
    if database_path.exists():
        raise FileExistsError(f"refusing to overwrite existing demo database: {database_path}")

    engine = create_engine(f"sqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        with Session.begin() as session:
            window = previous_calendar_day_window(DEMO_EDITION_DATE)
            reader = create_reader_profile(
                session,
                telegram_chat_id=999_001,
                preference_prompt="多看台灣生活和人際故事，少看政治。",
                included_topics=["taiwan_life", "relationships"],
                excluded_subreddits=["politics"],
            )
            edition = get_or_create_edition(
                session,
                reader=reader,
                edition_date=DEMO_EDITION_DATE,
                window_start=window.start_utc,
                window_end=window.end_utc,
            ).edition
            _seed_demo_candidates(session, window_start=window.start_utc)
            plan = plan_edition(session, edition=edition).plan
            draft_edition(session, edition=edition, plan=plan)
            view = load_edition_view(session, edition=edition)
            html = render_html(view)
            preview = render_telegram_preview(view)
            item_count = len(view.items)
            artifact_count = len(view.artifacts)
        output_path.write_text(html, encoding="utf-8")
    finally:
        engine.dispose()
    return DemoResult(
        html_path=output_path,
        database_path=database_path,
        telegram_preview=preview,
        item_count=item_count,
        artifact_count=artifact_count,
    )


def _seed_demo_candidates(session, *, window_start: datetime) -> None:
    for index, (reddit_post_id, subreddit, title, headline_zh, body) in enumerate(DEMO_POSTS):
        session.add(CandidatePost(
            reddit_post_id=reddit_post_id,
            subreddit=subreddit,
            title=title,
            selftext=body,
            permalink=f"/r/{subreddit}/comments/{reddit_post_id}/demo/",
            author_username=f"demo_author_{index}",
            posted_at=window_start + timedelta(hours=2, minutes=index),
            lang="en" if index not in {2, 3} else "zh",
            initial_num_comments=10 + index,
            meta_json={"headline_zh": headline_zh},
        ))
    session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成離線 AI 編輯室 HTML demo，不呼叫外部服務。")
    parser.add_argument("--output", type=Path, default=None, help="HTML 輸出位置；預設為 /tmp 下的新檔案")
    parser.add_argument("--open", action="store_true", help="產出後在預設瀏覽器開啟 HTML")
    args = parser.parse_args()
    result = run_demo(output_path=args.output or _default_output_path())
    print(f"HTML demo: {result.html_path}")
    print(f"Isolated demo DB: {result.database_path}")
    print(f"Edition: {result.item_count} items, {result.artifact_count} visible agent artifacts")
    print("\n--- Telegram preview (not sent) ---\n")
    print(result.telegram_preview)
    if args.open:
        webbrowser.open(result.html_path.as_uri())


if __name__ == "__main__":
    main()
