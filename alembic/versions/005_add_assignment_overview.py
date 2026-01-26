"""Add assignment_overview to modules.

Revision ID: 005
Revises: 004
Create Date: 2026-01-26
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("assignment_overview", sa.Text, nullable=True),
    )
    op.add_column(
        "modules",
        sa.Column("overview_generated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("modules", "overview_generated_at")
    op.drop_column("modules", "assignment_overview")
