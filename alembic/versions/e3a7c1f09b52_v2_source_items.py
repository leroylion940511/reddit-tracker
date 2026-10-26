"""Add multi-source collection tables (v2.0 comprehensive daily).

Revision ID: e3a7c1f09b52
Revises: d68a592f6d22
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3a7c1f09b52"
down_revision: Union[str, Sequence[str], None] = "d68a592f6d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pk_type():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "source_items",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("tier", sa.String(length=2), nullable=False),
        sa.Column("item_key", sa.String(length=40), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("lang", sa.String(length=8), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at_estimated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title_fingerprint", sa.String(length=40), nullable=True),
        sa.Column("duplicate_of_id", _pk_type(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["source_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "item_key", name="uq_source_item_key"),
    )
    with op.batch_alter_table("source_items", schema=None) as batch_op:
        batch_op.create_index("ix_source_items_source_id", ["source_id"])
        batch_op.create_index("ix_source_items_section", ["section"])
        batch_op.create_index("ix_source_items_canonical_url", ["canonical_url"])
        batch_op.create_index("ix_source_items_published_at", ["published_at"])
        batch_op.create_index("ix_source_items_first_seen_at", ["first_seen_at"])
        batch_op.create_index("ix_source_items_title_fingerprint", ["title_fingerprint"])
        batch_op.create_index("ix_source_items_duplicate_of_id", ["duplicate_of_id"])

    op.create_table(
        "source_fetch_runs",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("not_modified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("items_returned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_new", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_duplicate", sa.Integer(), server_default="0", nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("source_fetch_runs", schema=None) as batch_op:
        batch_op.create_index("ix_source_fetch_runs_source_id", ["source_id"])
        batch_op.create_index("ix_source_fetch_runs_started_at", ["started_at"])


def downgrade() -> None:
    op.drop_table("source_fetch_runs")
    op.drop_table("source_items")
