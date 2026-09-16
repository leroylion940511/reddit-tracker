"""v5 newsroom reader, edition, and agent ledger foundation.

Revision ID: b91feebcd321
Revises: 7778060d74e7
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b91feebcd321"
down_revision: Union[str, Sequence[str], None] = "7778060d74e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pk_type():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "reader_profiles",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("telegram_chat_id", _pk_type(), nullable=True),
        sa.Column("preference_prompt", sa.Text(), nullable=True),
        sa.Column("included_topics", sa.JSON(), nullable=True),
        sa.Column("excluded_topics", sa.JSON(), nullable=True),
        sa.Column("included_subreddits", sa.JSON(), nullable=True),
        sa.Column("excluded_subreddits", sa.JSON(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Taipei", nullable=False),
        sa.Column("delivery_time", sa.String(length=5), server_default="08:30", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("reader_profiles", schema=None) as batch_op:
        batch_op.create_index("ix_reader_profiles_telegram_chat_id", ["telegram_chat_id"], unique=True)

    op.create_table(
        "newsroom_editions",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("reader_profile_id", _pk_type(), nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="planned", nullable=False),
        sa.Column("editor_summary", sa.Text(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["reader_profile_id"], ["reader_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reader_profile_id", "edition_date", name="uq_reader_edition_date"),
    )
    with op.batch_alter_table("newsroom_editions", schema=None) as batch_op:
        batch_op.create_index("ix_newsroom_editions_edition_date", ["edition_date"], unique=False)

    op.create_table(
        "edition_items",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_id", _pk_type(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="planned", nullable=False),
        sa.Column("headline_zh", sa.String(length=120), nullable=True),
        sa.Column("body_zh", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["edition_id"], ["newsroom_editions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edition_id", "position", name="uq_edition_item_position"),
    )

    op.create_table(
        "edition_item_sources",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_item_id", _pk_type(), nullable=False),
        sa.Column("candidate_post_id", _pk_type(), nullable=False),
        sa.Column("source_order", sa.Integer(), server_default="1", nullable=False),
        sa.Column("source_role", sa.String(length=24), server_default="primary", nullable=False),
        sa.ForeignKeyConstraint(["edition_item_id"], ["edition_items.id"]),
        sa.ForeignKeyConstraint(["candidate_post_id"], ["candidate_posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edition_item_id", "candidate_post_id", name="uq_item_candidate_source"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_id", _pk_type(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="running", nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["edition_id"], ["newsroom_editions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edition_id", "stage", "attempt", name="uq_edition_stage_attempt"),
    )

    op.create_table(
        "agent_artifacts",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("agent_run_id", _pk_type(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_artifact_sources",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("agent_artifact_id", _pk_type(), nullable=False),
        sa.Column("candidate_post_id", _pk_type(), nullable=False),
        sa.Column("source_order", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["agent_artifact_id"], ["agent_artifacts.id"]),
        sa.ForeignKeyConstraint(["candidate_post_id"], ["candidate_posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_artifact_id", "candidate_post_id", name="uq_artifact_candidate_source"),
    )

    op.create_table(
        "reader_feedback",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("reader_profile_id", _pk_type(), nullable=False),
        sa.Column("edition_item_id", _pk_type(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("acted_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["reader_profile_id"], ["reader_profiles.id"]),
        sa.ForeignKeyConstraint(["edition_item_id"], ["edition_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reader_profile_id", "edition_item_id", "action", name="uq_reader_item_action"),
    )


def downgrade() -> None:
    op.drop_table("reader_feedback")
    op.drop_table("agent_artifact_sources")
    op.drop_table("agent_artifacts")
    op.drop_table("agent_runs")
    op.drop_table("edition_item_sources")
    op.drop_table("edition_items")
    with op.batch_alter_table("newsroom_editions", schema=None) as batch_op:
        batch_op.drop_index("ix_newsroom_editions_edition_date")
    op.drop_table("newsroom_editions")
    with op.batch_alter_table("reader_profiles", schema=None) as batch_op:
        batch_op.drop_index("ix_reader_profiles_telegram_chat_id")
    op.drop_table("reader_profiles")
