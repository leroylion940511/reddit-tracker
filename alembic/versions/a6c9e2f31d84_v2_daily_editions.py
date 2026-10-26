"""Add comprehensive daily editions and articles (v2.0 trial).

Revision ID: a6c9e2f31d84
Revises: f4b2d8e61c07
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6c9e2f31d84"
down_revision: Union[str, Sequence[str], None] = "f4b2d8e61c07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pk_type():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "daily_editions",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="drafting", nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("writer", sa.String(length=32), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("html_path", sa.Text(), nullable=True),
        sa.Column("telegram_message_ids", sa.JSON(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("daily_editions", schema=None) as batch_op:
        batch_op.create_index("ix_daily_editions_edition_date", ["edition_date"], unique=True)

    op.create_table(
        "daily_articles",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("edition_id", _pk_type(), nullable=False),
        sa.Column("cluster_id", _pk_type(), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_front", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("deck", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("writer", sa.String(length=16), nullable=False),
        sa.Column("review_notes", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["edition_id"], ["daily_editions.id"]),
        sa.ForeignKeyConstraint(["cluster_id"], ["story_clusters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("daily_articles", schema=None) as batch_op:
        batch_op.create_index("ix_daily_articles_edition_id", ["edition_id"])
        batch_op.create_index("ix_daily_articles_cluster_id", ["cluster_id"])


def downgrade() -> None:
    op.drop_table("daily_articles")
    op.drop_table("daily_editions")
