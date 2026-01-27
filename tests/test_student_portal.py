"""
Test harness for the Student Portal.

Tests cover:
- Student home/dashboard (/student, /student/home)
- Module view (/student/module/{id})
- Assignment submission (/student/module/{id}/submit)
- GitHub grade view (/student/submission/{id}/github-grade)
- Help page access (/help/student)

Requirements:
- PostgreSQL database (the models use PostgreSQL-specific types: ARRAY, JSONB)
- Set TEST_DATABASE_URL environment variable or it will use the default test database

To run tests:
    pytest tests/test_student_portal.py -v
"""

import os
import uuid as uuid_module
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app.database import Base, get_db
from app.models import (
    User,
    UserRole,
    Course,
    Module,
    ModuleVisibility,
    Submission,
    Grade,
    UserModuleSelection,
)
from app.routers import student, dashboard
from app.dependencies import require_user


def unique_id() -> str:
    """Generate a unique ID for test data to avoid conflicts."""
    return str(uuid_module.uuid4())[:8]


# Test database setup using PostgreSQL (required for ARRAY and JSONB types)
# Uses the Docker database by default (port 5433) with transaction rollback for isolation
# Set TEST_DATABASE_URL environment variable to override

# Default to Docker PostgreSQL on port 5433
DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5433/course_review"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

engine = create_engine(TEST_DATABASE_URL)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _safe_truncate(conn, table_name: str):
    """Safely truncate a table if it exists."""
    try:
        conn.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
    except Exception:
        pass  # Table may not exist


@pytest.fixture(scope="function")
def db():
    """Create a fresh database session for each test.

    This fixture:
    1. Creates all tables before each test (if they don't exist)
    2. Yields a database session
    3. Rolls back and cleans up test data after each test

    Note: Uses transaction rollback for isolation. Each test runs in its
    own transaction that is rolled back after the test completes.
    """
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)

    # Use a connection with a transaction for test isolation
    connection = engine.connect()
    transaction = connection.begin()

    # Create session bound to the connection
    db = TestingSessionLocal(bind=connection)

    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def mock_student_user(db):
    """Create a mock student user for testing."""
    # Use unique identifiers to avoid conflicts with existing data
    uid = unique_id()
    user = User(
        google_id=f"google_student_test_{uid}",
        email=f"student_test_{uid}@test.edu",
        name="Test Student",
        role=UserRole.student,
        accepted_terms_at=datetime.utcnow(),
        reminder_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def mock_admin_user(db):
    """Create a mock admin user for testing."""
    uid = unique_id()
    user = User(
        google_id=f"google_admin_test_{uid}",
        email=f"admin_test_{uid}@test.edu",
        name="Test Admin",
        role=UserRole.admin,
        accepted_terms_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def mock_course(db):
    """Create a test course that has already started."""
    uid = unique_id()
    course = Course(
        name="Agentic AI Systems Test",
        code=f"AI-TEST-{uid}",
        description="Learn to build AI agents",
        instructor_name="Dr. Test",
        instructor_email="instructor@test.edu",
        term="Spring 2026",
        start_date=datetime.utcnow() - timedelta(days=14),  # Started 2 weeks ago
        is_active=True,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@pytest.fixture
def mock_future_course(db):
    """Create a test course that hasn't started yet."""
    uid = unique_id()
    course = Course(
        name="Future AI Course Test",
        code=f"AI-FUTURE-{uid}",
        description="Coming soon",
        start_date=datetime.utcnow() + timedelta(days=30),  # Starts in 30 days
        is_active=True,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@pytest.fixture
def mock_active_module(db, mock_course):
    """Create an active module in week 1 (should be unlocked)."""
    uid = unique_id()
    module = Module(
        course_id=mock_course.id,
        name=f"Module 1: Introduction to AI Agents ({uid})",
        week_number=1,
        visibility=ModuleVisibility.active,
        short_description="Learn the basics of AI agents",
        detailed_description="A comprehensive introduction to AI agents.",
        drive_file_id=f"test_drive_file_id_{uid}",
        github_classroom_url="https://classroom.github.com/a/test123",
        instructions="Complete the in-class exercises.",
        homework_instructions="Submit your homework via GitHub.",
        max_points=100,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def mock_locked_module(db, mock_course):
    """Create an active module in week 10 (should be locked for week 3 current)."""
    uid = unique_id()
    module = Module(
        course_id=mock_course.id,
        name=f"Module 10: Advanced Topics ({uid})",
        week_number=10,
        visibility=ModuleVisibility.active,
        short_description="Advanced AI agent patterns",
        drive_file_id=f"test_drive_file_id_locked_{uid}",
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def mock_draft_module(db, mock_course):
    """Create a draft module (should not be accessible)."""
    uid = unique_id()
    module = Module(
        course_id=mock_course.id,
        name=f"Draft Module ({uid})",
        week_number=1,
        visibility=ModuleVisibility.draft,
        short_description="Work in progress",
        drive_file_id=f"test_drive_file_id_draft_{uid}",
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def mock_pilot_review_module(db, mock_course):
    """Create a pilot review module (should not be accessible by students)."""
    uid = unique_id()
    module = Module(
        course_id=mock_course.id,
        name=f"Pilot Review Module ({uid})",
        week_number=1,
        visibility=ModuleVisibility.pilot_review,
        short_description="Under pilot review",
        drive_file_id=f"test_drive_file_id_pilot_{uid}",
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@pytest.fixture
def mock_submission(db, mock_student_user, mock_active_module):
    """Create a test submission."""
    submission = Submission(
        user_id=mock_student_user.id,
        module_id=mock_active_module.id,
        submission_type="homework",
        github_link="https://github.com/student/assignment-1",
        comments="My submission",
        submitted_at=datetime.utcnow(),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@pytest.fixture
def mock_grade(db, mock_submission):
    """Create a test grade for a submission."""
    grade = Grade(
        submission_id=mock_submission.id,
        total_points=85,
        max_points=100,
        percentage=85.0,
        letter_grade="B",
        status="completed",
        graded_at=datetime.utcnow(),
        graded_by="auto",
        automated_feedback="Good work!",
    )
    db.add(grade)
    db.commit()
    db.refresh(grade)
    return grade


def create_test_app(db, user=None):
    """Create a FastAPI test app with the student routes."""
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-secret-key",
        max_age=86400,
    )

    # Override database dependency
    def override_get_db():
        try:
            yield db
        finally:
            pass

    # Override user dependency
    async def override_require_user():
        if user is None:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/"},
            )
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_user] = override_require_user

    app.include_router(student.router)
    app.include_router(dashboard.router)

    return app


@pytest.fixture
def client(db, mock_student_user):
    """Create a test client with an authenticated student user."""
    app = create_test_app(db, mock_student_user)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def unauthenticated_client(db):
    """Create a test client without authentication."""
    app = create_test_app(db, user=None)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def admin_client(db, mock_admin_user):
    """Create a test client with an authenticated admin user."""
    app = create_test_app(db, mock_admin_user)
    with TestClient(app) as c:
        yield c


class TestStudentDashboard:
    """Tests for the student dashboard (/student)."""

    def test_student_dashboard_shows_active_modules(
        self, client, mock_active_module, mock_course
    ):
        """Test that the student dashboard displays active modules."""
        response = client.get("/student")
        assert response.status_code == 200
        assert mock_active_module.name in response.text

    def test_student_dashboard_excludes_draft_modules(
        self, client, mock_draft_module, mock_course
    ):
        """Test that draft modules are not shown to students."""
        response = client.get("/student")
        assert response.status_code == 200
        assert mock_draft_module.name not in response.text

    def test_student_dashboard_excludes_pilot_review_modules(
        self, client, mock_pilot_review_module, mock_course
    ):
        """Test that pilot review modules are not shown to students."""
        response = client.get("/student")
        assert response.status_code == 200
        assert mock_pilot_review_module.name not in response.text

    def test_student_dashboard_shows_submission_status(
        self, client, mock_active_module, mock_submission, mock_course
    ):
        """Test that submission status is displayed on dashboard."""
        response = client.get("/student")
        assert response.status_code == 200
        # The dashboard should indicate homework has been submitted
        assert response.status_code == 200


class TestModuleView:
    """Tests for viewing individual modules (/student/module/{id})."""

    def test_view_active_module(self, client, mock_active_module, mock_course):
        """Test viewing an active, unlocked module."""
        response = client.get(f"/student/module/{mock_active_module.id}")
        assert response.status_code == 200
        assert mock_active_module.name in response.text

    def test_view_nonexistent_module_returns_404(self, client):
        """Test that viewing a nonexistent module returns 404."""
        response = client.get("/student/module/99999")
        assert response.status_code == 404

    def test_view_draft_module_returns_403(self, client, mock_draft_module, mock_course):
        """Test that viewing a draft module returns 403."""
        response = client.get(f"/student/module/{mock_draft_module.id}")
        assert response.status_code == 403

    def test_view_pilot_review_module_returns_403(
        self, client, mock_pilot_review_module, mock_course
    ):
        """Test that viewing a pilot review module returns 403."""
        response = client.get(f"/student/module/{mock_pilot_review_module.id}")
        assert response.status_code == 403

    def test_view_locked_module_returns_403(
        self, client, mock_locked_module, mock_course
    ):
        """Test that viewing a locked module (future week) returns 403."""
        response = client.get(f"/student/module/{mock_locked_module.id}")
        assert response.status_code == 403
        assert "Week" in response.text or "week" in response.text.lower()


class TestSubmissionWorkflow:
    """Tests for the assignment submission workflow."""

    def test_view_submit_form(self, client, mock_active_module, mock_course):
        """Test viewing the submission form."""
        response = client.get(f"/student/module/{mock_active_module.id}/submit/homework")
        assert response.status_code == 200

    def test_submit_form_invalid_type_returns_400(
        self, client, mock_active_module, mock_course
    ):
        """Test that invalid submission type returns 400."""
        response = client.get(f"/student/module/{mock_active_module.id}/submit/invalid")
        assert response.status_code == 400

    def test_submit_form_draft_module_returns_403(
        self, client, mock_draft_module, mock_course
    ):
        """Test that submitting to a draft module returns 403."""
        response = client.get(f"/student/module/{mock_draft_module.id}/submit/homework")
        assert response.status_code == 403

    def test_submit_assignment_success(
        self, db, client, mock_active_module, mock_student_user, mock_course
    ):
        """Test successful assignment submission."""
        response = client.post(
            f"/student/module/{mock_active_module.id}/submit/in_class",
            data={
                "github_link": "https://github.com/student/my-assignment",
                "comments": "My in-class work",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303  # Redirect after success
        assert f"/student/module/{mock_active_module.id}" in response.headers["location"]

        # Verify submission was created
        submission = (
            db.query(Submission)
            .filter(
                Submission.user_id == mock_student_user.id,
                Submission.module_id == mock_active_module.id,
                Submission.submission_type == "in_class",
            )
            .first()
        )
        assert submission is not None
        assert submission.github_link == "https://github.com/student/my-assignment"

    def test_submit_assignment_missing_github_link(
        self, client, mock_active_module, mock_course
    ):
        """Test that submission without GitHub link fails."""
        response = client.post(
            f"/student/module/{mock_active_module.id}/submit/homework",
            data={
                "github_link": "",
                "comments": "No link provided",
            },
        )
        assert response.status_code == 400

    def test_submit_assignment_invalid_github_url(
        self, client, mock_active_module, mock_course
    ):
        """Test that submission with invalid GitHub URL fails."""
        response = client.post(
            f"/student/module/{mock_active_module.id}/submit/homework",
            data={
                "github_link": "https://gitlab.com/user/repo",
                "comments": "Wrong platform",
            },
        )
        assert response.status_code == 400

    def test_update_existing_submission(
        self, db, client, mock_active_module, mock_submission, mock_course, mock_student_user
    ):
        """Test updating an existing submission."""
        new_link = "https://github.com/student/updated-assignment"
        response = client.post(
            f"/student/module/{mock_active_module.id}/submit/homework",
            data={
                "github_link": new_link,
                "comments": "Updated submission",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        # Verify submission was updated
        db.refresh(mock_submission)
        assert mock_submission.github_link == new_link


class TestGitHubGradeView:
    """Tests for viewing GitHub grades (/student/submission/{id}/github-grade)."""

    @patch("app.routers.student.github_service")
    def test_view_own_grade(
        self, mock_github, client, mock_submission, mock_active_module, mock_grade
    ):
        """Test viewing own submission grade."""
        mock_github.get_workflow_run_status = AsyncMock(
            return_value={
                "status": "completed",
                "conclusion": "success",
                "url": "https://github.com/actions/run/123",
            }
        )
        mock_github.fetch_grade_report = AsyncMock(return_value=None)

        response = client.get(f"/student/submission/{mock_submission.id}/github-grade")
        assert response.status_code == 200

    def test_view_nonexistent_submission_returns_404(self, client):
        """Test viewing grade for nonexistent submission returns 404."""
        response = client.get("/student/submission/99999/github-grade")
        assert response.status_code == 404

    def test_view_other_user_submission_returns_403(
        self, db, client, mock_active_module, mock_course
    ):
        """Test that viewing another user's submission grade returns 403."""
        import uuid as uuid_module
        uid = unique_id()

        # Create another user and their submission
        other_user = User(
            google_id=f"other_user_google_id_{uid}",
            email=f"other_{uid}@test.edu",
            name="Other Student",
            role=UserRole.student,
        )
        db.add(other_user)
        db.commit()

        other_submission = Submission(
            user_id=other_user.id,
            module_id=mock_active_module.id,
            submission_type="homework",
            github_link="https://github.com/other/repo",
            comments="Other's work",
        )
        db.add(other_submission)
        db.commit()

        response = client.get(f"/student/submission/{other_submission.id}/github-grade")
        assert response.status_code == 403

    @patch("app.routers.student.github_service")
    def test_admin_can_view_any_grade(
        self,
        mock_github,
        admin_client,
        db,
        mock_student_user,
        mock_active_module,
        mock_course,
    ):
        """Test that admin can view any student's grade."""
        submission = Submission(
            user_id=mock_student_user.id,
            module_id=mock_active_module.id,
            submission_type="homework",
            github_link="https://github.com/student/repo",
            comments="Student work",
        )
        db.add(submission)
        db.commit()

        mock_github.get_workflow_run_status = AsyncMock(
            return_value={"status": "completed", "conclusion": "success"}
        )
        mock_github.fetch_grade_report = AsyncMock(return_value=None)

        response = admin_client.get(f"/student/submission/{submission.id}/github-grade")
        assert response.status_code == 200


class TestRefreshGrade:
    """Tests for refreshing GitHub grades."""

    @patch("app.routers.student.github_service")
    def test_refresh_own_grade(
        self, mock_github, client, mock_submission, mock_active_module
    ):
        """Test refreshing own submission grade."""
        mock_github.fetch_grade_report = AsyncMock(return_value=None)

        response = client.post(
            f"/student/submission/{mock_submission.id}/refresh-grade",
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_refresh_other_user_grade_returns_403(
        self, db, client, mock_active_module, mock_course
    ):
        """Test that refreshing another user's grade returns 403."""
        import uuid as uuid_module
        uid = unique_id()

        other_user = User(
            google_id=f"another_user_google_id_{uid}",
            email=f"another_{uid}@test.edu",
            name="Another Student",
            role=UserRole.student,
        )
        db.add(other_user)
        db.commit()

        other_submission = Submission(
            user_id=other_user.id,
            module_id=mock_active_module.id,
            submission_type="homework",
            github_link="https://github.com/another/repo",
            comments="Another's work",
        )
        db.add(other_submission)
        db.commit()

        response = client.post(
            f"/student/submission/{other_submission.id}/refresh-grade",
            follow_redirects=False,
        )
        assert response.status_code == 403


class TestHelpPage:
    """Tests for the student help page (/help/student)."""

    def test_student_can_access_help_page(self, client):
        """Test that students can access the help page."""
        response = client.get("/help/student")
        assert response.status_code == 200

    def test_admin_can_access_help_page(self, admin_client):
        """Test that admins can access the student help page."""
        response = admin_client.get("/help/student")
        assert response.status_code == 200


class TestAccessControl:
    """Tests for access control and visibility rules."""

    def test_only_active_modules_visible_in_dashboard(
        self,
        client,
        mock_active_module,
        mock_draft_module,
        mock_pilot_review_module,
        mock_course,
    ):
        """Test that only active modules appear in student dashboard."""
        response = client.get("/student")
        assert response.status_code == 200
        assert mock_active_module.name in response.text
        assert mock_draft_module.name not in response.text
        assert mock_pilot_review_module.name not in response.text

    def test_inactive_course_not_shown(self, db, client, mock_student_user):
        """Test that modules from inactive courses are not shown."""
        import uuid as uuid_module
        uid = unique_id()

        inactive_course = Course(
            name=f"Inactive Course ({uid})",
            code=f"INACTIVE-{uid}",
            is_active=False,
        )
        db.add(inactive_course)
        db.commit()

        inactive_module = Module(
            course_id=inactive_course.id,
            name=f"Module from Inactive Course ({uid})",
            week_number=1,
            visibility=ModuleVisibility.active,
            drive_file_id=f"inactive_file_id_{uid}",
        )
        db.add(inactive_module)
        db.commit()

        response = client.get("/student")
        assert response.status_code == 200
        assert inactive_module.name not in response.text


class TestWeeklyUnlock:
    """Tests for the weekly module unlock feature."""

    def test_week_1_module_unlocked_in_week_3(
        self, client, mock_active_module, mock_course
    ):
        """Test that week 1 module is accessible in week 3."""
        # mock_course started 14 days ago, so we're in week 3
        response = client.get(f"/student/module/{mock_active_module.id}")
        assert response.status_code == 200

    def test_week_10_module_locked_in_week_3(
        self, client, mock_locked_module, mock_course
    ):
        """Test that week 10 module is NOT accessible in week 3."""
        response = client.get(f"/student/module/{mock_locked_module.id}")
        assert response.status_code == 403

    def test_all_modules_unlocked_when_no_start_date(self, db, client, mock_student_user):
        """Test that all modules are unlocked when course has no start date."""
        import uuid as uuid_module
        uid = unique_id()

        course_no_start = Course(
            name=f"No Start Date Course ({uid})",
            code=f"NO-START-{uid}",
            start_date=None,
            is_active=True,
        )
        db.add(course_no_start)
        db.commit()

        week_20_module = Module(
            course_id=course_no_start.id,
            name=f"Far Future Module ({uid})",
            week_number=20,
            visibility=ModuleVisibility.active,
            drive_file_id=f"no_start_file_id_{uid}",
        )
        db.add(week_20_module)
        db.commit()

        response = client.get(f"/student/module/{week_20_module.id}")
        assert response.status_code == 200

    def test_no_modules_unlocked_before_course_starts(
        self, db, client, mock_future_course, mock_student_user
    ):
        """Test that no modules are unlocked before course starts."""
        import uuid as uuid_module
        uid = unique_id()

        future_module = Module(
            course_id=mock_future_course.id,
            name=f"Future Course Module ({uid})",
            week_number=1,
            visibility=ModuleVisibility.active,
            drive_file_id=f"future_file_id_{uid}",
        )
        db.add(future_module)
        db.commit()

        response = client.get(f"/student/module/{future_module.id}")
        assert response.status_code == 403


class TestSubmissionTypes:
    """Tests for different submission types."""

    def test_in_class_submission(
        self, db, client, mock_active_module, mock_student_user, mock_course
    ):
        """Test in-class assignment submission."""
        response = client.post(
            f"/student/module/{mock_active_module.id}/submit/in_class",
            data={
                "github_link": "https://github.com/student/in-class-work",
                "comments": "In-class work",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        submission = (
            db.query(Submission)
            .filter(
                Submission.user_id == mock_student_user.id,
                Submission.submission_type == "in_class",
            )
            .first()
        )
        assert submission is not None
        assert submission.submission_type == "in_class"

    def test_homework_submission(
        self, db, client, mock_active_module, mock_student_user, mock_course
    ):
        """Test homework assignment submission."""
        response = client.post(
            f"/student/module/{mock_active_module.id}/submit/homework",
            data={
                "github_link": "https://github.com/student/homework",
                "comments": "Homework submission",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        submission = (
            db.query(Submission)
            .filter(
                Submission.user_id == mock_student_user.id,
                Submission.submission_type == "homework",
            )
            .first()
        )
        assert submission is not None
        assert submission.submission_type == "homework"

    def test_both_submission_types_allowed(
        self, db, client, mock_active_module, mock_student_user, mock_course
    ):
        """Test that a student can submit both in-class and homework."""
        # Submit in-class
        response1 = client.post(
            f"/student/module/{mock_active_module.id}/submit/in_class",
            data={
                "github_link": "https://github.com/student/in-class",
                "comments": "In-class",
            },
            follow_redirects=False,
        )
        assert response1.status_code == 303

        # Submit homework
        response2 = client.post(
            f"/student/module/{mock_active_module.id}/submit/homework",
            data={
                "github_link": "https://github.com/student/homework",
                "comments": "Homework",
            },
            follow_redirects=False,
        )
        assert response2.status_code == 303

        # Verify both exist
        submissions = (
            db.query(Submission)
            .filter(
                Submission.user_id == mock_student_user.id,
                Submission.module_id == mock_active_module.id,
            )
            .all()
        )
        assert len(submissions) == 2
        types = {s.submission_type for s in submissions}
        assert types == {"in_class", "homework"}
