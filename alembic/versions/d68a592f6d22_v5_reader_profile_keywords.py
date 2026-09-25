"""Add explicit keyword controls to v5 reader profiles.

Revision ID: d68a592f6d22
Revises: b91feebcd321
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d68a592f6d22"
down_revision: Union[str, Sequence[str], None] = "b91feebcd321"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reader_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("included_keywords", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("excluded_keywords", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reader_profiles", schema=None) as batch_op:
        batch_op.drop_column("excluded_keywords")
        batch_op.drop_column("included_keywords")
