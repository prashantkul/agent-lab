"""Remove deprecated grading fields.

Now that grading is handled by GitHub Classroom, we no longer need:
- starter_repo_url (GitHub Classroom creates repos from templates)
- grading_enabled (always enabled via GitHub Classroom)
- grading_script_url (graders are in a private repo, triggered by GitHub Actions)

Revision ID: 009
Revises: 008
Create Date: 2026-01-26
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("modules", "starter_repo_url")
    op.drop_column("modules", "grading_enabled")
    op.drop_column("modules", "grading_script_url")


def downgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("starter_repo_url", sa.String(500), nullable=True),
    )
    op.add_column(
        "modules",
        sa.Column("grading_enabled", sa.Boolean(), nullable=True, server_default="true"),
    )
    op.add_column(
        "modules",
        sa.Column("grading_script_url", sa.String(500), nullable=True),
    )
