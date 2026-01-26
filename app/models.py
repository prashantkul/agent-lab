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

    reviewer = "reviewer"
    student = "student"
    admin = "admin"


class ModuleVisibility(str, enum.Enum):
    """Module visibility states."""

    draft = "draft"
    pilot_review = "pilot_review"
    active = "active"
    archived = "archived"


class Course(Base):
    """Courses that contain modules."""

    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), unique=True, nullable=False)  # e.g., "AI-AGENTS-101"
    description = Column(Text)

    # Course metadata
    instructor_name = Column(String(200))
    instructor_email = Column(String(255))
    term = Column(String(50))  # e.g., "Spring 2026"

    # Schedule (for weekly unlock)
    start_date = Column(DateTime)  # When week 1 starts

    # Status
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    modules = relationship("Module", back_populates="course", order_by="Module.week_number")


class Module(Base):
    """Course modules available for review."""

    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)  # nullable for migration
    name = Column(String(100), nullable=False)
    week_number = Column(Integer, nullable=False)

    # Visibility & Access Control
    visibility = Column(
        Enum(ModuleVisibility),
        default=ModuleVisibility.draft,
        nullable=False
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
    github_classroom_url = Column(String(500))  # Assignment invitation link

    # AI-generated assignment overview (for reviewers)
    assignment_overview = Column(Text)
    overview_generated_at = Column(DateTime)

    # Instructions (Markdown)
    instructions = Column(Text)
    homework_instructions = Column(Text)

    # Grading Configuration (display only - actual grading via GitHub Classroom)
    grading_criteria = Column(Text)
    max_points = Column(Integer, default=100)

    # Capacity
    max_reviewers = Column(Integer, default=2)
    max_students = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    course = relationship("Course", back_populates="modules")
    users = relationship("User", back_populates="selected_module")
    submissions = relationship("Submission", back_populates="module")
    user_selections = relationship("UserModuleSelection", back_populates="module")


class User(Base):
    """Users (reviewers, students, and admins)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255))
    picture_url = Column(String(500))
    role = Column(Enum(UserRole), default=UserRole.reviewer, nullable=False)

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

    # Terms acceptance
    accepted_terms_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    selected_module = relationship("Module", back_populates="users")
    submissions = relationship("Submission", back_populates="user")
    module_selections = relationship("UserModuleSelection", back_populates="user", order_by="UserModuleSelection.selected_at")


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

    # Structured feedback responses (JSONB for flexibility)
    feedback_responses = Column(JSONB)

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


class UserModuleSelection(Base):
    """Many-to-many relationship between users and modules they're reviewing."""

    __tablename__ = "user_module_selections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=False)
    selected_at = Column(DateTime, default=datetime.utcnow)
    last_notified_version = Column(String(50))
    is_active = Column(Boolean, default=True)  # Currently viewing this module

    # Relationships
    user = relationship("User", back_populates="module_selections")
    module = relationship("Module", back_populates="user_selections")

    __table_args__ = (
        UniqueConstraint("user_id", "module_id", name="uq_user_module_selection"),
    )


class Notification(Base):
    """Notification log for tracking sent notifications."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_email = Column(String(255), nullable=False)
    notification_type = Column(String(50), nullable=False)
    module_id = Column(Integer, ForeignKey("modules.id"))
    extra_data = Column(JSONB)
    sent_at = Column(DateTime, default=datetime.utcnow)
