"""Add start_date to courses for weekly unlock.

Revision ID: 007
Revises: 006
Create Date: 2026-01-26
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("start_date", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "start_date")
