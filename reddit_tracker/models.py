"""SQLAlchemy 2.0 declarative models — 12 張表。

對應 docs/v4_schema.md。沿用 v3 的兩個 gotcha 應對：
- BigInt PK on SQLite 不會 autoincrement → with_variant(Integer, "sqlite")
- JSON 欄位：SQLAlchemy `JSON` type，Postgres 自動 JSONB / SQLite 自動 TEXT
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def big_pk() -> Mapped[int]:
    """BigInteger PK with SQLite fallback to Integer (for autoincrement)."""
    return mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


def big_fk(target: str, *, nullable: bool = False) -> Mapped[int]:
    return mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        ForeignKey(target),
        nullable=nullable,
    )


def utc_now() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 探索層
# ---------------------------------------------------------------------------


class CandidatePost(Base):
    __tablename__ = "candidate_posts"

    id: Mapped[int] = big_pk()
    reddit_post_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    subreddit: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    selftext: Mapped[str | None] = mapped_column(Text)
    permalink: Mapped[str | None] = mapped_column(String(255))
    author_username: Mapped[str | None] = mapped_column(String(64), index=True)
    author_karma: Mapped[int | None] = mapped_column(Integer)
    author_created_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    discovered_at: Mapped[datetime] = utc_now()
    discovery_source: Mapped[str | None] = mapped_column(String(64))  # 'subreddit:<n>' / 'keyword:<s>'
    initial_score: Mapped[int | None] = mapped_column(Integer)
    initial_num_comments: Mapped[int | None] = mapped_column(Integer)
    upvote_ratio: Mapped[float | None] = mapped_column(Float)
    lang: Mapped[str | None] = mapped_column(String(8))
    meta_json: Mapped[dict | None] = mapped_column("metadata", JSON)

    scoring_records: Mapped[list[ScoringRecord]] = relationship(back_populates="candidate")
    daily_pushes: Mapped[list[DailyPush]] = relationship(back_populates="candidate")
    feedbacks: Mapped[list[Feedback]] = relationship(back_populates="candidate")
    tracked: Mapped[TrackedPost | None] = relationship(back_populates="candidate", uselist=False)
    edition_item_sources: Mapped[list[EditionItemSource]] = relationship(
        back_populates="candidate"
    )
    agent_artifact_sources: Mapped[list[AgentArtifactSource]] = relationship(
        back_populates="candidate"
    )


class SubredditSource(Base):
    __tablename__ = "subreddit_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    lang_hint: Mapped[str | None] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_candidates_yielded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_promoted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_collected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class KeywordSeed(Base):
    __tablename__ = "keyword_seeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    category: Mapped[str | None] = mapped_column(String(32))
    lang: Mapped[str | None] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_candidates_yielded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_promoted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_collected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ---------------------------------------------------------------------------
# 評分推送
# ---------------------------------------------------------------------------


class ScoringRecord(Base):
    __tablename__ = "scoring_records"

    id: Mapped[int] = big_pk()
    candidate_post_id: Mapped[int] = big_fk("candidate_posts.id")
    stage: Mapped[str] = mapped_column(String(16))  # rules / haiku / final
    passed: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSON)
    scored_at: Mapped[datetime] = utc_now()
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

    candidate: Mapped[CandidatePost] = relationship(back_populates="scoring_records")


class DailyPush(Base):
    __tablename__ = "daily_pushes"
    __table_args__ = (UniqueConstraint("push_date", "candidate_post_id", name="uq_push_date_candidate"),)

    id: Mapped[int] = big_pk()
    push_date: Mapped[datetime] = mapped_column(Date, index=True)
    candidate_post_id: Mapped[int] = big_fk("candidate_posts.id")
    push_type: Mapped[str] = mapped_column(String(16))  # already_hot / early_bet / breaking
    rank: Mapped[int | None] = mapped_column(Integer)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[CandidatePost] = relationship(back_populates="daily_pushes")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = big_pk()
    user_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"))
    candidate_post_id: Mapped[int] = big_fk("candidate_posts.id")
    action: Mapped[str] = mapped_column(String(16))  # collect / dislike / mute_author
    acted_at: Mapped[datetime] = utc_now()

    candidate: Mapped[CandidatePost] = relationship(back_populates="feedbacks")


# ---------------------------------------------------------------------------
# v5 AI Newsroom
# ---------------------------------------------------------------------------


class ReaderProfile(Base):
    """一位讀者的可調整偏好與發行設定。

    v5 試刊只會建立一位讀者，但 schema 從第一天就支援多讀者，避免把
    Telegram chat id 或偏好硬編進 scheduler。
    """

    __tablename__ = "reader_profiles"

    id: Mapped[int] = big_pk()
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), unique=True, index=True
    )
    preference_prompt: Mapped[str | None] = mapped_column(Text)
    included_topics: Mapped[list | None] = mapped_column(JSON)
    excluded_topics: Mapped[list | None] = mapped_column(JSON)
    included_subreddits: Mapped[list | None] = mapped_column(JSON)
    excluded_subreddits: Mapped[list | None] = mapped_column(JSON)
    included_keywords: Mapped[list | None] = mapped_column(JSON)
    excluded_keywords: Mapped[list | None] = mapped_column(JSON)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Taipei", nullable=False
    )
    delivery_time: Mapped[str] = mapped_column(
        String(5), default="08:30", nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = utc_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    editions: Mapped[list[NewsroomEdition]] = relationship(back_populates="reader")
    feedbacks: Mapped[list[ReaderFeedback]] = relationship(back_populates="reader")


class NewsroomEdition(Base):
    """一位讀者在一天內的一期報紙及其發行狀態。"""

    __tablename__ = "newsroom_editions"
    __table_args__ = (
        UniqueConstraint("reader_profile_id", "edition_date", name="uq_reader_edition_date"),
    )

    id: Mapped[int] = big_pk()
    reader_profile_id: Mapped[int] = big_fk("reader_profiles.id")
    edition_date: Mapped[date] = mapped_column(Date, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="planned", nullable=False)
    editor_summary: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = utc_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    reader: Mapped[ReaderProfile] = relationship(back_populates="editions")
    items: Mapped[list[EditionItem]] = relationship(back_populates="edition")
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="edition")


class EditionItem(Base):
    """報紙的一篇短報、專題或早報快訊；來源走 bridge table。"""

    __tablename__ = "edition_items"
    __table_args__ = (
        UniqueConstraint("edition_id", "position", name="uq_edition_item_position"),
    )

    id: Mapped[int] = big_pk()
    edition_id: Mapped[int] = big_fk("newsroom_editions.id")
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # brief / feature / breaking
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="planned", nullable=False)
    headline_zh: Mapped[str | None] = mapped_column(String(120))
    body_zh: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(16))
    warnings: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = utc_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    edition: Mapped[NewsroomEdition] = relationship(back_populates="items")
    sources: Mapped[list[EditionItemSource]] = relationship(back_populates="edition_item")
    feedbacks: Mapped[list[ReaderFeedback]] = relationship(back_populates="edition_item")


class EditionItemSource(Base):
    """報紙 item 到原始 candidate 的有序、多對多來源關係。"""

    __tablename__ = "edition_item_sources"
    __table_args__ = (
        UniqueConstraint("edition_item_id", "candidate_post_id", name="uq_item_candidate_source"),
    )

    id: Mapped[int] = big_pk()
    edition_item_id: Mapped[int] = big_fk("edition_items.id")
    candidate_post_id: Mapped[int] = big_fk("candidate_posts.id")
    source_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_role: Mapped[str] = mapped_column(String(24), default="primary", nullable=False)

    edition_item: Mapped[EditionItem] = relationship(back_populates="sources")
    candidate: Mapped[CandidatePost] = relationship(back_populates="edition_item_sources")


class AgentRun(Base):
    """一個 edition stage 的一次可重跑執行。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("edition_id", "stage", "attempt", name="uq_edition_stage_attempt"),
    )

    id: Mapped[int] = big_pk()
    edition_id: Mapped[int] = big_fk("newsroom_editions.id")
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False)
    input_snapshot: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = utc_now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    edition: Mapped[NewsroomEdition] = relationship(back_populates="agent_runs")
    artifacts: Mapped[list[AgentArtifactRecord]] = relationship(back_populates="agent_run")


class AgentArtifactRecord(Base):
    """供 dashboard 檢視的 agent artifact；不存 private reasoning。"""

    __tablename__ = "agent_artifacts"

    id: Mapped[int] = big_pk()
    agent_run_id: Mapped[int] = big_fk("agent_runs.id")
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[str | None] = mapped_column(String(16))
    warnings: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = utc_now()

    agent_run: Mapped[AgentRun] = relationship(back_populates="artifacts")
    sources: Mapped[list[AgentArtifactSource]] = relationship(back_populates="artifact")


class AgentArtifactSource(Base):
    """Artifact 的來源關係，讓選題／查核過程可回溯。"""

    __tablename__ = "agent_artifact_sources"
    __table_args__ = (
        UniqueConstraint("agent_artifact_id", "candidate_post_id", name="uq_artifact_candidate_source"),
    )

    id: Mapped[int] = big_pk()
    agent_artifact_id: Mapped[int] = big_fk("agent_artifacts.id")
    candidate_post_id: Mapped[int] = big_fk("candidate_posts.id")
    source_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    artifact: Mapped[AgentArtifactRecord] = relationship(back_populates="sources")
    candidate: Mapped[CandidatePost] = relationship(back_populates="agent_artifact_sources")


class ReaderFeedback(Base):
    """Telegram 報紙 item 的 ❤️／🚫／👀 回饋。"""

    __tablename__ = "reader_feedback"
    __table_args__ = (
        UniqueConstraint("reader_profile_id", "edition_item_id", "action", name="uq_reader_item_action"),
    )

    id: Mapped[int] = big_pk()
    reader_profile_id: Mapped[int] = big_fk("reader_profiles.id")
    edition_item_id: Mapped[int] = big_fk("edition_items.id")
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # more / less / follow
    acted_at: Mapped[datetime] = utc_now()

    reader: Mapped[ReaderProfile] = relationship(back_populates="feedbacks")
    edition_item: Mapped[EditionItem] = relationship(back_populates="feedbacks")


# ---------------------------------------------------------------------------
# 多來源收集（v2.0 綜合日報，規格見 docs/v5/COLLECTION.md）
# ---------------------------------------------------------------------------


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (UniqueConstraint("source_id", "item_key", name="uq_source_item_key"),)

    id: Mapped[int] = big_pk()
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    section: Mapped[str] = mapped_column(String(32), index=True)
    tier: Mapped[str] = mapped_column(String(2))
    item_key: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(8))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    published_at_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    title_fingerprint: Mapped[str | None] = mapped_column(String(40), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        ForeignKey("source_items.id"),
        index=True,
    )
    meta_json: Mapped[dict | None] = mapped_column("metadata", JSON)


class SourceFetchRun(Base):
    __tablename__ = "source_fetch_runs"

    id: Mapped[int] = big_pk()
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    not_modified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    items_returned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_duplicate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# ---------------------------------------------------------------------------
# 收藏追蹤
# ---------------------------------------------------------------------------


class TrackedPost(Base):
    __tablename__ = "tracked_posts"

    id: Mapped[int] = big_pk()
    candidate_post_id: Mapped[int] = big_fk("candidate_posts.id")
    user_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"))
    promoted_at: Mapped[datetime] = utc_now()
    polling_tier: Mapped[str] = mapped_column(String(16), default="hot", nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    initial_summary: Mapped[str | None] = mapped_column(Text)

    candidate: Mapped[CandidatePost] = relationship(back_populates="tracked")
    snapshots: Mapped[list[PostSnapshot]] = relationship(back_populates="tracked")
    related: Mapped[list[RelatedPost]] = relationship(back_populates="tracked")
    qa_sessions: Mapped[list[QASession]] = relationship(back_populates="tracked")


class PostSnapshot(Base):
    __tablename__ = "post_snapshots"

    id: Mapped[int] = big_pk()
    tracked_post_id: Mapped[int] = big_fk("tracked_posts.id")
    captured_at: Mapped[datetime] = utc_now()
    score: Mapped[int | None] = mapped_column(Integer)
    num_comments: Mapped[int | None] = mapped_column(Integer)
    upvote_ratio: Mapped[float | None] = mapped_column(Float)
    new_comments: Mapped[dict | None] = mapped_column(JSON)

    tracked: Mapped[TrackedPost] = relationship(back_populates="snapshots")


class RelatedPost(Base):
    __tablename__ = "related_posts"
    __table_args__ = (
        UniqueConstraint(
            "tracked_post_id", "relation_type", "reddit_post_id",
            name="uq_related_post_triple",
        ),
    )

    id: Mapped[int] = big_pk()
    tracked_post_id: Mapped[int] = big_fk("tracked_posts.id")
    reddit_post_id: Mapped[str | None] = mapped_column(String(16), index=True)
    relation_type: Mapped[str] = mapped_column(String(16))  # author_followup/_reply/hot_reply/crosspost
    relevance_score: Mapped[float | None] = mapped_column(Float)
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = utc_now()
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tracked: Mapped[TrackedPost] = relationship(back_populates="related")


# ---------------------------------------------------------------------------
# LLM 與問答
# ---------------------------------------------------------------------------


class LLMRecord(Base):
    __tablename__ = "llm_records"

    id: Mapped[int] = big_pk()
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32), index=True)  # scoring / summarization / qa
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    called_at: Mapped[datetime] = utc_now()
    context_ref: Mapped[dict | None] = mapped_column(JSON)


class QASession(Base):
    __tablename__ = "qa_sessions"

    id: Mapped[int] = big_pk()
    user_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"))
    tracked_post_id: Mapped[int] = big_fk("tracked_posts.id")
    started_at: Mapped[datetime] = utc_now()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="active", nullable=False)

    tracked: Mapped[TrackedPost] = relationship(back_populates="qa_sessions")
    messages: Mapped[list[QAMessage]] = relationship(back_populates="session")


class QAMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[int] = big_pk()
    qa_session_id: Mapped[int] = big_fk("qa_sessions.id")
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    sent_at: Mapped[datetime] = utc_now()

    session: Mapped[QASession] = relationship(back_populates="messages")


__all__ = [
    "Base",
    "AgentArtifactRecord",
    "AgentArtifactSource",
    "AgentRun",
    "CandidatePost",
    "DailyPush",
    "EditionItem",
    "EditionItemSource",
    "Feedback",
    "KeywordSeed",
    "LLMRecord",
    "PostSnapshot",
    "QAMessage",
    "QASession",
    "ReaderFeedback",
    "ReaderProfile",
    "RelatedPost",
    "ScoringRecord",
    "SourceFetchRun",
    "SourceItem",
    "SubredditSource",
    "TrackedPost",
    "NewsroomEdition",
]
