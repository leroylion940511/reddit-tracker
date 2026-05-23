"""M5 related_posts add notified_at + uq_related_post_triple

Revision ID: 7778060d74e7
Revises: c0d4993bb6f1
Create Date: 2026-05-23 18:42:41.631904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7778060d74e7'
down_revision: Union[str, Sequence[str], None] = 'c0d4993bb6f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("related_posts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_related_post_triple",
            ["tracked_post_id", "relation_type", "reddit_post_id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("related_posts", schema=None) as batch_op:
        batch_op.drop_constraint("uq_related_post_triple", type_="unique")
        batch_op.drop_column("notified_at")
