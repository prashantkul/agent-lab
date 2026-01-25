"""SQLAlchemy ORM models."""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Enum,
    DECIMAL,
    ARRAY,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    """User role enumeration."""

    REVIEWER = "reviewer"
    STUDENT = "student"
    ADMIN = "admin"


class ModuleVisibility(str, enum.Enum):
    """Module visibility states."""

    DRAFT = "draft"
    PILOT_REVIEW = "pilot_review"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Module(Base):
    """Course modules available for review."""

    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    week_number = Column(Integer, nullable=False)

    # Visibility & Access Control
    visibility = Column(
        Enum(ModuleVisibility), default=ModuleVisibility.DRAFT, nullable=False
    )

    # Rich Description
    short_description = Column(Text)
    detailed_description = Column(Text)
    learning_objectives = Column(ARRAY(Text))
    prerequisites = Column(ARRAY(Text))
    expected_outcomes = Column(Text)
    estimated_time_minutes = Column(Integer)

    # Materials
    drive_file_id = Column(String(100), nullable=False)
    drive_modified_time = Column(String(50))
    starter_repo_url = Column(String(500))

    # Instructions (Markdown)
    instructions = Column(Text)
    homework_instructions = Column(Text)

    # Grading Configuration
    grading_enabled = Column(Boolean, default=True)
    grading_script_url = Column(String(500))
    grading_criteria = Column(Text)
    max_points = Column(Integer, default=100)

    # Capacity
    max_reviewers = Column(Integer, default=10)
    max_students = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="selected_module")
    submissions = relationship("Submission", back_populates="module")


class User(Base):
    """Users (reviewers, students, and admins)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255))
    picture_url = Column(String(500))
    role = Column(Enum(UserRole), default=UserRole.REVIEWER, nullable=False)

    # Enrollment
    selected_module_id = Column(Integer, ForeignKey("modules.id"))
    selected_at = Column(DateTime)
    last_notified_version = Column(String(50))

    # Student-specific
    student_id = Column(String(50))
    cohort = Column(String(50))

    # Reminder settings
    reminder_enabled = Column(Boolean, default=True)
    last_reminder_sent = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    selected_module = relationship("Module", back_populates="users")
    submissions = relationship("Submission", back_populates="user")


class Submission(Base):
    """User submissions for in-class and homework assignments."""

    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=False)
    submission_type = Column(String(20), nullable=False)  # 'in_class' or 'homework'
    github_link = Column(String(500), nullable=False)
    comments = Column(Text, nullable=False)

    # User self-ratings (for pilot feedback)
    clarity_rating = Column(Integer)
    difficulty_rating = Column(Integer)
    time_spent_minutes = Column(Integer)

    submitted_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="submissions")
    module = relationship("Module", back_populates="submissions")
    grade = relationship("Grade", back_populates="submission", uselist=False)

    __table_args__ = (
        UniqueConstraint("user_id", "module_id", "submission_type", name="uq_user_module_type"),
        CheckConstraint("clarity_rating >= 1 AND clarity_rating <= 5", name="ck_clarity_rating"),
        CheckConstraint("difficulty_rating >= 1 AND difficulty_rating <= 5", name="ck_difficulty_rating"),
    )


class Grade(Base):
    """Grading results for submissions."""

    __tablename__ = "grades"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, unique=True)

    # Scores
    total_points = Column(DECIMAL(5, 2))
    max_points = Column(Integer, default=100)
    percentage = Column(DECIMAL(5, 2))
    letter_grade = Column(String(2))

    # Breakdown (JSONB for flexibility)
    score_breakdown = Column(JSONB)

    # Feedback
    automated_feedback = Column(Text)
    manual_feedback = Column(Text)
    strengths = Column(ARRAY(Text))
    improvements = Column(ARRAY(Text))

    # Status
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    graded_at = Column(DateTime)
    graded_by = Column(String(50))  # 'auto' or admin email

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    submission = relationship("Submission", back_populates="grade")


class Notification(Base):
    """Notification log for tracking sent notifications."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_email = Column(String(255), nullable=False)
    notification_type = Column(String(50), nullable=False)
    module_id = Column(Integer, ForeignKey("modules.id"))
    metadata = Column(JSONB)
    sent_at = Column(DateTime, default=datetime.utcnow)
