"""Add github_classroom_url to modules.

Revision ID: 008
Revises: 007
Create Date: 2026-01-26
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("github_classroom_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("modules", "github_classroom_url")
