"""Add user_module_selections table for multi-module support.

Revision ID: 006
Revises: 005
Create Date: 2026-01-26
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the new user_module_selections table
    op.create_table(
        "user_module_selections",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("module_id", sa.Integer, sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("selected_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("last_notified_version", sa.String(50)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.UniqueConstraint("user_id", "module_id", name="uq_user_module_selection"),
    )

    # Migrate existing selections from users table to new table
    op.execute("""
        INSERT INTO user_module_selections (user_id, module_id, selected_at, last_notified_version, is_active)
        SELECT id, selected_module_id, selected_at, last_notified_version, true
        FROM users
        WHERE selected_module_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_table("user_module_selections")
