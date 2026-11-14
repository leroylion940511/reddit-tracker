"""desk-v3 D2: item_fulltext table (article full text, off by default).

Revision ID: c5e1a9d3f207
Revises: b8d4f0a17c33
Create Date: 2026-11-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e1a9d3f207"
down_revision: Union[str, Sequence[str], None] = "b8d4f0a17c33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pk_type():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "item_fulltext",
        sa.Column("item_id", _pk_type(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("text_chars", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_sha1", sa.String(length=40), nullable=True),
        sa.Column("extractor", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["source_items.id"]),
        sa.PrimaryKeyConstraint("item_id"),
    )
    with op.batch_alter_table("item_fulltext", schema=None) as batch_op:
        batch_op.create_index("ix_item_fulltext_status", ["status"])
        batch_op.create_index("ix_item_fulltext_fetched_at", ["fetched_at"])


def downgrade() -> None:
    op.drop_table("item_fulltext")
