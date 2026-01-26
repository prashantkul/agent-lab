"""Add terms acceptance field

Revision ID: 002
Revises: 001
Create Date: 2026-01-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('accepted_terms_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'accepted_terms_at')
