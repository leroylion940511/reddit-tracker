"""SQLAlchemy 2.0 declarative models — 12 張表。

對應 docs/v4_schema.md。沿用 v3 的兩個 gotcha 應對：
- BigInt PK on SQLite 不會 autoincrement → with_variant(Integer, "sqlite")
- JSON 欄位：SQLAlchemy `JSON` type，Postgres 自動 JSONB / SQLite 自動 TEXT
"""

from __future__ import annotations

from datetime import datetime
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

    id: Mapped[int] = big_pk()
    tracked_post_id: Mapped[int] = big_fk("tracked_posts.id")
    reddit_post_id: Mapped[str | None] = mapped_column(String(16), index=True)
    relation_type: Mapped[str] = mapped_column(String(16))  # author_followup/_reply/hot_reply/crosspost
    relevance_score: Mapped[float | None] = mapped_column(Float)
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = utc_now()

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
    "CandidatePost",
    "DailyPush",
    "Feedback",
    "KeywordSeed",
    "LLMRecord",
    "PostSnapshot",
    "QAMessage",
    "QASession",
    "RelatedPost",
    "ScoringRecord",
    "SubredditSource",
    "TrackedPost",
]
