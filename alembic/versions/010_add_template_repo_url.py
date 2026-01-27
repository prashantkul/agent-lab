"""Add template_repo_url to modules.

Revision ID: 010
Revises: 009
Create Date: 2025-01-26
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("template_repo_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("modules", "template_repo_url")
