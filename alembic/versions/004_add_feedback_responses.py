"""Add feedback_responses JSONB column to submissions.

Revision ID: 004
Revises: 003
Create Date: 2025-01-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("feedback_responses", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "feedback_responses")
