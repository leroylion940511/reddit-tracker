"""Add story clusters for cross-outlet event aggregation (v2.0 daily).

Revision ID: f4b2d8e61c07
Revises: e3a7c1f09b52
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4b2d8e61c07"
down_revision: Union[str, Sequence[str], None] = "e3a7c1f09b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pk_type():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "story_clusters",
        sa.Column("id", _pk_type(), autoincrement=True, nullable=False),
        sa.Column("lang_group", sa.String(length=8), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("representative_item_id", _pk_type(), nullable=True),
        sa.Column("item_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("outlet_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("t1_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("t2_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("t4_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("story_clusters", schema=None) as batch_op:
        batch_op.create_index("ix_story_clusters_section", ["section"])
        batch_op.create_index("ix_story_clusters_first_published_at", ["first_published_at"])
        batch_op.create_index("ix_story_clusters_last_published_at", ["last_published_at"])

    with op.batch_alter_table("source_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cluster_id", _pk_type(), nullable=True))
        batch_op.create_index("ix_source_items_cluster_id", ["cluster_id"])
        batch_op.create_foreign_key("fk_source_items_cluster", "story_clusters", ["cluster_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("source_items", schema=None) as batch_op:
        batch_op.drop_constraint("fk_source_items_cluster", type_="foreignkey")
        batch_op.drop_index("ix_source_items_cluster_id")
        batch_op.drop_column("cluster_id")
    op.drop_table("story_clusters")
