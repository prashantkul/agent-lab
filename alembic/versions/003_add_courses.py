"""Add courses table and link modules to courses.

Revision ID: 003
Revises: 002
Create Date: 2026-01-25
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create courses table
    op.create_table(
        'courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('instructor_name', sa.String(200), nullable=True),
        sa.Column('instructor_email', sa.String(255), nullable=True),
        sa.Column('term', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_courses_id'), 'courses', ['id'], unique=False)

    # Add course_id to modules table
    op.add_column('modules', sa.Column('course_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_modules_course_id', 'modules', 'courses', ['course_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_modules_course_id', 'modules', type_='foreignkey')
    op.drop_column('modules', 'course_id')
    op.drop_index(op.f('ix_courses_id'), table_name='courses')
    op.drop_table('courses')
