"""Shared test fixtures and configuration for all portal tests.

This module provides common fixtures for testing the Agent Lab application.
It uses PostgreSQL for testing since the models use PostgreSQL-specific
types (ARRAY, JSONB).

Setup:
    1. Create a test database: createdb course_review_test
    2. Or set TEST_DATABASE_URL to point to your test database
    3. Run tests: pytest tests/ -v
"""
import os
import pytest
from datetime import datetime
from typing import Generator
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.main import app
from app.database import Base, get_db
from app.models import (
    User, UserRole, Course, Module, ModuleVisibility,
    UserModuleSelection, Submission, Grade
)


# Test database URL - PostgreSQL is required for ARRAY and JSONB types
# Uses the Docker database by default (port 5433) since models use PostgreSQL-specific types
# Set TEST_DATABASE_URL environment variable to override

# Default to Docker PostgreSQL on port 5433
DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5433/course_review"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

engine = create_engine(TEST_DATABASE_URL)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    """Override database dependency for tests."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Create a fresh database session for each test.

    Uses transaction-based isolation: each test runs in its own
    transaction that is rolled back after the test completes.
    This ensures test isolation without requiring table drops/recreates.
    """
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)

    # Use a connection with a transaction for test isolation
    connection = engine.connect()
    transaction = connection.begin()

    # Create session bound to the connection
    db_session = TestingSessionLocal(bind=connection)

    try:
        yield db_session
    finally:
        db_session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ==================== User Fixtures ====================

@pytest.fixture
def admin_user(db: Session) -> User:
    """Create an admin user."""
    user = User(
        google_id="admin_google_123",
        email="admin@test.com",
        name="Test Admin",
        role=UserRole.admin,
        accepted_terms_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def reviewer_user(db: Session) -> User:
    """Create a reviewer user."""
    user = User(
        google_id="reviewer_google_456",
        email="reviewer@test.com",
        name="Test Reviewer",
        role=UserRole.reviewer,
        accepted_terms_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def reviewer_user_no_terms(db: Session) -> User:
    """Create a reviewer user who hasn't accepted terms."""
    user = User(
        google_id="reviewer_new_google_789",
        email="reviewer_new@test.com",
        name="New Reviewer",
        role=UserRole.reviewer,
        accepted_terms_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def student_user(db: Session) -> User:
    """Create a student user."""
    user = User(
        google_id="student_google_101",
        email="student@test.com",
        name="Test Student",
        role=UserRole.student,
        accepted_terms_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ==================== Course Fixtures ====================

@pytest.fixture
def test_course(db: Session) -> Course:
    """Create a test course."""
    course = Course(
        code="CS101",
        name="Introduction to AI Agents",
        term="Spring 2025",
        start_date=datetime(2025, 1, 15),
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


# ==================== Module Fixtures ====================

@pytest.fixture
def draft_module(db: Session, test_course: Course) -> Module:
    """Create a draft module."""
    module = Module(
        name="Draft Module",
        week_number=1,
        course_id=test_course.id,
        visibility=ModuleVisibility.draft,
        drive_file_id="test_drive_file_1",
        short_description="A draft module for testing",
        max_reviewers=2,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def pilot_review_module(db: Session, test_course: Course) -> Module:
    """Create a pilot review module (available for reviewers)."""
    module = Module(
        name="Pilot Review Module",
        week_number=2,
        course_id=test_course.id,
        visibility=ModuleVisibility.pilot_review,
        drive_file_id="test_drive_file_2",
        short_description="A module available for pilot review",
        github_classroom_url="https://classroom.github.com/a/test123",
        max_reviewers=2,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def active_module(db: Session, test_course: Course) -> Module:
    """Create an active module (available for students)."""
    module = Module(
        name="Active Module",
        week_number=3,
        course_id=test_course.id,
        visibility=ModuleVisibility.active,
        drive_file_id="test_drive_file_3",
        short_description="An active module for students",
        github_classroom_url="https://classroom.github.com/a/test456",
        max_reviewers=2,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def full_module(db: Session, test_course: Course) -> Module:
    """Create a module that's already full (2 reviewers)."""
    module = Module(
        name="Full Module",
        week_number=4,
        course_id=test_course.id,
        visibility=ModuleVisibility.pilot_review,
        drive_file_id="test_drive_file_4",
        short_description="A module that's already full",
        max_reviewers=2,
    )
    db.add(module)
    db.commit()

    # Add 2 reviewers to make it full
    for i in range(2):
        reviewer = User(
            google_id=f"full_reviewer_google_{i}",
            email=f"reviewer{i}@test.com",
            name=f"Reviewer {i}",
            role=UserRole.reviewer,
            accepted_terms_at=datetime.utcnow(),
        )
        db.add(reviewer)
        db.commit()

        selection = UserModuleSelection(
            user_id=reviewer.id,
            module_id=module.id,
            is_active=True,
        )
        db.add(selection)

    db.commit()
    db.refresh(module)
    return module


# ==================== Selection Fixtures ====================

@pytest.fixture
def reviewer_with_selection(db: Session, reviewer_user: User, pilot_review_module: Module) -> UserModuleSelection:
    """Create a reviewer with a module selection."""
    selection = UserModuleSelection(
        user_id=reviewer_user.id,
        module_id=pilot_review_module.id,
        is_active=True,
    )
    db.add(selection)
    db.commit()
    db.refresh(selection)
    return selection


@pytest.fixture
def student_with_selection(db: Session, student_user: User, active_module: Module) -> UserModuleSelection:
    """Create a student with a module selection."""
    selection = UserModuleSelection(
        user_id=student_user.id,
        module_id=active_module.id,
        is_active=True,
    )
    db.add(selection)
    db.commit()
    db.refresh(selection)
    return selection


# ==================== Session Mock Helpers ====================

def mock_session_for_user(client: TestClient, user: User):
    """Helper to mock session for a specific user."""
    client.cookies.set("session", f"user_{user.id}")
    return patch.dict(
        "app.dependencies.get_current_user_id",
        lambda request: user.id
    )


@pytest.fixture
def authenticated_admin(client: TestClient, admin_user: User):
    """Return a client authenticated as admin."""
    # Mock the session to contain the user_id
    with patch("app.dependencies.get_current_user_id", return_value=admin_user.id):
        yield client, admin_user


@pytest.fixture
def authenticated_reviewer(client: TestClient, reviewer_user: User):
    """Return a client authenticated as reviewer."""
    with patch("app.dependencies.get_current_user_id", return_value=reviewer_user.id):
        yield client, reviewer_user


@pytest.fixture
def authenticated_student(client: TestClient, student_user: User):
    """Return a client authenticated as student."""
    with patch("app.dependencies.get_current_user_id", return_value=student_user.id):
        yield client, student_user
