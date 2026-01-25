"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-01-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums
    user_role = postgresql.ENUM('reviewer', 'student', 'admin', name='userrole')
    user_role.create(op.get_bind(), checkfirst=True)

    module_visibility = postgresql.ENUM('draft', 'pilot_review', 'active', 'archived', name='modulevisibility')
    module_visibility.create(op.get_bind(), checkfirst=True)

    # Create modules table
    op.create_table(
        'modules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('week_number', sa.Integer(), nullable=False),
        sa.Column('visibility', sa.Enum('draft', 'pilot_review', 'active', 'archived', name='modulevisibility'), nullable=False, server_default='draft'),
        sa.Column('short_description', sa.Text(), nullable=True),
        sa.Column('detailed_description', sa.Text(), nullable=True),
        sa.Column('learning_objectives', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('prerequisites', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('expected_outcomes', sa.Text(), nullable=True),
        sa.Column('estimated_time_minutes', sa.Integer(), nullable=True),
        sa.Column('drive_file_id', sa.String(length=100), nullable=False),
        sa.Column('drive_modified_time', sa.String(length=50), nullable=True),
        sa.Column('starter_repo_url', sa.String(length=500), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('homework_instructions', sa.Text(), nullable=True),
        sa.Column('grading_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('grading_script_url', sa.String(length=500), nullable=True),
        sa.Column('grading_criteria', sa.Text(), nullable=True),
        sa.Column('max_points', sa.Integer(), nullable=True, server_default='100'),
        sa.Column('max_reviewers', sa.Integer(), nullable=True, server_default='10'),
        sa.Column('max_students', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_modules_id'), 'modules', ['id'], unique=False)

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('google_id', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('picture_url', sa.String(length=500), nullable=True),
        sa.Column('role', sa.Enum('reviewer', 'student', 'admin', name='userrole'), nullable=False, server_default='reviewer'),
        sa.Column('selected_module_id', sa.Integer(), nullable=True),
        sa.Column('selected_at', sa.DateTime(), nullable=True),
        sa.Column('last_notified_version', sa.String(length=50), nullable=True),
        sa.Column('student_id', sa.String(length=50), nullable=True),
        sa.Column('cohort', sa.String(length=50), nullable=True),
        sa.Column('reminder_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('last_reminder_sent', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['selected_module_id'], ['modules.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('google_id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
    op.create_index(op.f('ix_users_google_id'), 'users', ['google_id'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    # Create submissions table
    op.create_table(
        'submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('module_id', sa.Integer(), nullable=False),
        sa.Column('submission_type', sa.String(length=20), nullable=False),
        sa.Column('github_link', sa.String(length=500), nullable=False),
        sa.Column('comments', sa.Text(), nullable=False),
        sa.Column('clarity_rating', sa.Integer(), nullable=True),
        sa.Column('difficulty_rating', sa.Integer(), nullable=True),
        sa.Column('time_spent_minutes', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.CheckConstraint('clarity_rating >= 1 AND clarity_rating <= 5', name='ck_clarity_rating'),
        sa.CheckConstraint('difficulty_rating >= 1 AND difficulty_rating <= 5', name='ck_difficulty_rating'),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'module_id', 'submission_type', name='uq_user_module_type')
    )
    op.create_index(op.f('ix_submissions_id'), 'submissions', ['id'], unique=False)

    # Create grades table
    op.create_table(
        'grades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('total_points', sa.DECIMAL(precision=5, scale=2), nullable=True),
        sa.Column('max_points', sa.Integer(), nullable=True, server_default='100'),
        sa.Column('percentage', sa.DECIMAL(precision=5, scale=2), nullable=True),
        sa.Column('letter_grade', sa.String(length=2), nullable=True),
        sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('automated_feedback', sa.Text(), nullable=True),
        sa.Column('manual_feedback', sa.Text(), nullable=True),
        sa.Column('strengths', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('improvements', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('graded_at', sa.DateTime(), nullable=True),
        sa.Column('graded_by', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('submission_id')
    )
    op.create_index(op.f('ix_grades_id'), 'grades', ['id'], unique=False)

    # Create notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('notification_type', sa.String(length=50), nullable=False),
        sa.Column('module_id', sa.Integer(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_id'), 'notifications', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_grades_id'), table_name='grades')
    op.drop_table('grades')
    op.drop_index(op.f('ix_submissions_id'), table_name='submissions')
    op.drop_table('submissions')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_google_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_modules_id'), table_name='modules')
    op.drop_table('modules')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS modulevisibility')
    op.execute('DROP TYPE IF EXISTS userrole')
