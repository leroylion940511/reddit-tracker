"""MAS newsroom tables and llm_records columns (handbook steps 6–7).

Revision ID: b8d4f0a17c33
Revises: a6c9e2f31d84
Create Date: 2026-10-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f0a17c33"
down_revision: Union[str, Sequence[str], None] = "a6c9e2f31d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pk_type():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "daily_snapshots",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edition_date", name="uq_daily_snapshot_date"),
    )
    op.create_table(
        "stories",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=False),
        sa.Column("run_variant", sa.String(length=16), nullable=False),
        sa.Column("keeper_cluster_id", _pk_type(), nullable=False),
        sa.Column("merged_cluster_ids", sa.JSON(), nullable=True),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edition_date", "run_variant", "keeper_cluster_id", name="uq_story_keeper"),
    )
    op.create_index("ix_stories_edition_date", "stories", ["edition_date"])
    op.create_table(
        "agent_messages",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("run_variant", sa.String(length=16), nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=False),
        sa.Column("story_id", _pk_type(), nullable=True),
        sa.Column("sender_role", sa.String(length=32), nullable=False),
        sa.Column("recipient_role", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("llm_call_id", _pk_type(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_messages_run_variant", "agent_messages", ["run_variant"])
    op.create_index("ix_agent_messages_edition_date", "agent_messages", ["edition_date"])
    op.create_index("ix_agent_messages_story_id", "agent_messages", ["story_id"])
    op.create_index("ix_agent_messages_correlation_id", "agent_messages", ["correlation_id"])
    op.create_table(
        "story_versions",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("story_id", _pk_type(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("run_variant", sa.String(length=16), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("deck", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("source_ids", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("caused_by_message_id", _pk_type(), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "version", "run_variant", name="uq_story_version"),
    )
    op.create_index("ix_story_versions_story_id", "story_versions", ["story_id"])
    op.create_table(
        "page_plans",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("run_variant", sa.String(length=16), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("decided_by_message_id", _pk_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edition_date", "plan_version", "run_variant", name="uq_page_plan"),
    )
    op.create_index("ix_page_plans_edition_date", "page_plans", ["edition_date"])

    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("llm_records")}
    indexes = {index["name"] for index in inspector.get_indexes("llm_records")}
    with op.batch_alter_table("llm_records") as batch:
        if "request_hash" not in existing:
            batch.add_column(sa.Column("request_hash", sa.String(length=64), nullable=True))
        if "prompt_text" not in existing:
            batch.add_column(sa.Column("prompt_text", sa.Text(), nullable=True))
        if "response_text" not in existing:
            batch.add_column(sa.Column("response_text", sa.Text(), nullable=True))
        if "latency_ms" not in existing:
            batch.add_column(sa.Column("latency_ms", sa.Integer(), nullable=True))
        if "ok" not in existing:
            batch.add_column(sa.Column("ok", sa.Boolean(), nullable=True))
        if "error" not in existing:
            batch.add_column(sa.Column("error", sa.Text(), nullable=True))
        if "role" not in existing:
            batch.add_column(sa.Column("role", sa.String(length=32), nullable=True))
        if "run_variant" not in existing:
            batch.add_column(sa.Column("run_variant", sa.String(length=16), nullable=True))
        if "edition_date" not in existing:
            batch.add_column(sa.Column("edition_date", sa.Date(), nullable=True))
        if "story_id" not in existing:
            batch.add_column(sa.Column("story_id", _pk_type(), nullable=True))
        if "model_version" not in existing:
            batch.add_column(sa.Column("model_version", sa.Text(), nullable=True))
        if "ix_llm_records_request_hash" not in indexes:
            batch.create_index("ix_llm_records_request_hash", ["request_hash"])


def downgrade() -> None:
    with op.batch_alter_table("llm_records") as batch:
        batch.drop_index("ix_llm_records_request_hash")
        batch.drop_column("model_version")
        batch.drop_column("story_id")
        batch.drop_column("edition_date")
        batch.drop_column("run_variant")
        batch.drop_column("role")
        batch.drop_column("error")
        batch.drop_column("ok")
        batch.drop_column("latency_ms")
        batch.drop_column("response_text")
        batch.drop_column("prompt_text")
        batch.drop_column("request_hash")
    op.drop_table("page_plans")
    op.drop_table("story_versions")
    op.drop_table("agent_messages")
    op.drop_table("stories")
    op.drop_table("daily_snapshots")
