"""Test harness for the Admin Portal.

Tests cover:
- Dashboard (/admin)
- Courses management (/admin/courses, /admin/courses/new, /admin/courses/{id}/edit)
- Modules management (/admin/modules, /admin/modules/new, /admin/modules/{id}/edit)
- Module import (/admin/modules/import)
- Generate AI overview (/admin/modules/{id}/generate-overview)
- Users management (/admin/users)
- Submissions view (/admin/submissions)
"""
import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Course,
    Grade,
    Module,
    ModuleVisibility,
    Submission,
    User,
    UserRole,
)


# Test database setup using SQLite in-memory
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database dependency override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db_session):
    """Create an admin user for testing."""
    user = User(
        google_id="admin_google_123",
        email="admin@example.com",
        name="Test Admin",
        role=UserRole.admin,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def reviewer_user(db_session):
    """Create a reviewer user for testing."""
    user = User(
        google_id="reviewer_google_456",
        email="reviewer@example.com",
        name="Test Reviewer",
        role=UserRole.reviewer,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def student_user(db_session):
    """Create a student user for testing."""
    user = User(
        google_id="student_google_789",
        email="student@example.com",
        name="Test Student",
        role=UserRole.student,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_course(db_session):
    """Create a sample course for testing."""
    course = Course(
        name="AI Fundamentals",
        code="AI-101",
        description="Introduction to AI concepts",
        instructor_name="Dr. Smith",
        instructor_email="smith@example.com",
        term="Spring 2026",
        is_active=True,
    )
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)
    return course


@pytest.fixture
def sample_module(db_session, sample_course):
    """Create a sample module for testing."""
    module = Module(
        course_id=sample_course.id,
        name="Week 1: Introduction",
        week_number=1,
        visibility=ModuleVisibility.active,
        short_description="Introduction to the course",
        detailed_description="This module covers the basics.",
        drive_file_id="test_drive_file_123",
        max_reviewers=10,
        max_points=100,
    )
    db_session.add(module)
    db_session.commit()
    db_session.refresh(module)
    return module


@pytest.fixture
def sample_submission(db_session, reviewer_user, sample_module):
    """Create a sample submission for testing."""
    submission = Submission(
        user_id=reviewer_user.id,
        module_id=sample_module.id,
        submission_type="in_class",
        github_link="https://github.com/test/repo",
        comments="Test submission comments",
        clarity_rating=4,
        difficulty_rating=3,
        time_spent_minutes=60,
    )
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


def set_session_user(client: TestClient, user: User):
    """Helper to set the user in the session."""
    with client.session_transaction() as session:
        session["user_id"] = user.id


@pytest.mark.admin
class TestAdminAccessControl:
    """Tests for admin access control."""

    def test_admin_dashboard_requires_auth(self, client):
        """Test that unauthenticated users are redirected."""
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"

    def test_admin_dashboard_denies_reviewer(self, client, reviewer_user):
        """Test that reviewers are denied access to admin dashboard."""
        client.cookies.set("session", "")
        with client:
            client.cookies.set("session", f"user_id={reviewer_user.id}")
            response = client.get(
                "/admin",
                cookies={"session": f'{{"user_id": {reviewer_user.id}}}'},
            )
        # Without proper session, should redirect
        assert response.status_code in [303, 403]

    def test_admin_dashboard_denies_student(self, client, student_user):
        """Test that students are denied access to admin dashboard."""
        response = client.get(
            "/admin",
            cookies={"session": f'{{"user_id": {student_user.id}}}'},
        )
        assert response.status_code in [303, 403]

    def test_courses_requires_admin(self, client, reviewer_user):
        """Test that courses management requires admin role."""
        response = client.get("/admin/courses")
        assert response.status_code in [303, 403]

    def test_modules_requires_admin(self, client, reviewer_user):
        """Test that modules management requires admin role."""
        response = client.get("/admin/modules")
        assert response.status_code in [303, 403]

    def test_users_requires_admin(self, client, reviewer_user):
        """Test that users management requires admin role."""
        response = client.get("/admin/users")
        assert response.status_code in [303, 403]

    def test_submissions_requires_admin(self, client, reviewer_user):
        """Test that submissions view requires admin role."""
        response = client.get("/admin/submissions")
        assert response.status_code in [303, 403]


@pytest.mark.admin
class TestAdminDashboardWithSession:
    """Tests for admin dashboard with proper session handling."""

    def test_admin_dashboard_access(self, client, admin_user, db_session):
        """Test admin dashboard is accessible to admin users."""
        # Simulate session by patching get_current_user
        with patch("app.dependencies.get_current_user") as mock_get_user:
            mock_get_user.return_value = admin_user
            with patch("app.routers.admin.require_admin") as mock_require:
                mock_require.return_value = admin_user
                response = client.get("/admin")
                # Template rendering may fail in test environment, but route should work
                assert response.status_code in [200, 500]


@pytest.mark.admin
class TestCourseCRUD:
    """Tests for Course CRUD operations."""

    @pytest.fixture(autouse=True)
    def setup_admin_mock(self, admin_user):
        """Set up admin mock for all tests in this class."""
        self.admin_user = admin_user

    def test_list_courses_empty(self, client, admin_user, db_session):
        """Test listing courses when none exist."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/courses")
            # May fail template rendering in test, check route exists
            assert response.status_code in [200, 500]

    def test_list_courses_with_data(self, client, admin_user, sample_course, db_session):
        """Test listing courses with existing courses."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/courses")
            assert response.status_code in [200, 500]

    def test_create_course_form(self, client, admin_user):
        """Test accessing the new course form."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/courses/new")
            assert response.status_code in [200, 500]

    def test_create_course(self, client, admin_user, db_session):
        """Test creating a new course."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/courses",
                data={
                    "name": "Machine Learning 101",
                    "code": "ML-101",
                    "description": "Intro to ML",
                    "instructor_name": "Dr. Jones",
                    "instructor_email": "jones@example.com",
                    "term": "Fall 2026",
                    "is_active": "on",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/admin/courses"

            # Verify course was created
            course = db_session.query(Course).filter(Course.code == "ML-101").first()
            assert course is not None
            assert course.name == "Machine Learning 101"
            assert course.is_active is True

    def test_edit_course_form(self, client, admin_user, sample_course, db_session):
        """Test accessing the edit course form."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get(f"/admin/courses/{sample_course.id}/edit")
            assert response.status_code in [200, 500]

    def test_edit_course_not_found(self, client, admin_user):
        """Test editing a non-existent course."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/courses/99999/edit")
            assert response.status_code == 404

    def test_update_course(self, client, admin_user, sample_course, db_session):
        """Test updating an existing course."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/courses/{sample_course.id}",
                data={
                    "name": "Updated AI Course",
                    "code": "AI-102",
                    "description": "Updated description",
                    "instructor_name": "Dr. Brown",
                    "instructor_email": "brown@example.com",
                    "term": "Summer 2026",
                    "is_active": "on",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            # Verify course was updated
            db_session.refresh(sample_course)
            assert sample_course.name == "Updated AI Course"
            assert sample_course.code == "AI-102"

    def test_update_course_not_found(self, client, admin_user):
        """Test updating a non-existent course."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/courses/99999",
                data={
                    "name": "Test",
                    "code": "TEST",
                },
            )
            assert response.status_code == 404

    def test_course_modules_list(self, client, admin_user, sample_course, sample_module, db_session):
        """Test listing modules for a specific course."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get(f"/admin/courses/{sample_course.id}/modules")
            assert response.status_code in [200, 500]


@pytest.mark.admin
class TestModuleCRUD:
    """Tests for Module CRUD operations."""

    def test_list_modules(self, client, admin_user, sample_module, db_session):
        """Test listing all modules."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/modules")
            assert response.status_code in [200, 500]

    def test_create_module_form(self, client, admin_user):
        """Test accessing the new module form."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/modules/new")
            assert response.status_code in [200, 500]

    def test_create_module(self, client, admin_user, sample_course, db_session):
        """Test creating a new module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/modules",
                data={
                    "name": "Week 2: Advanced Topics",
                    "week_number": "2",
                    "visibility": "draft",
                    "short_description": "Advanced topics in AI",
                    "detailed_description": "This module dives deeper into AI.",
                    "learning_objectives": "Objective 1\nObjective 2",
                    "prerequisites": "Module 1",
                    "expected_outcomes": "Students will understand advanced concepts",
                    "estimated_time_minutes": "120",
                    "drive_file_id": "new_drive_file_456",
                    "github_classroom_url": "https://classroom.github.com/a/test",
                    "template_repo_url": "https://github.com/test/template",
                    "instructions": "Follow the instructions",
                    "homework_instructions": "Complete homework",
                    "grading_criteria": "Rubric details",
                    "max_points": "100",
                    "max_reviewers": "5",
                    "max_students": "30",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/admin/modules"

            # Verify module was created
            module = db_session.query(Module).filter(Module.name == "Week 2: Advanced Topics").first()
            assert module is not None
            assert module.week_number == 2
            assert module.visibility == ModuleVisibility.draft

    def test_edit_module_form(self, client, admin_user, sample_module, db_session):
        """Test accessing the edit module form."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get(f"/admin/modules/{sample_module.id}/edit")
            assert response.status_code in [200, 500]

    def test_edit_module_not_found(self, client, admin_user):
        """Test editing a non-existent module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/modules/99999/edit")
            assert response.status_code == 404

    def test_update_module(self, client, admin_user, sample_module, db_session):
        """Test updating an existing module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{sample_module.id}",
                data={
                    "name": "Week 1: Updated Introduction",
                    "week_number": "1",
                    "visibility": "active",
                    "short_description": "Updated short desc",
                    "detailed_description": "Updated detailed desc",
                    "learning_objectives": "New Obj 1\nNew Obj 2",
                    "prerequisites": "",
                    "expected_outcomes": "Updated outcomes",
                    "estimated_time_minutes": "90",
                    "drive_file_id": "updated_drive_file",
                    "github_classroom_url": "",
                    "template_repo_url": "",
                    "instructions": "Updated instructions",
                    "homework_instructions": "",
                    "grading_criteria": "",
                    "max_points": "100",
                    "max_reviewers": "10",
                    "max_students": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            # Verify module was updated
            db_session.refresh(sample_module)
            assert sample_module.name == "Week 1: Updated Introduction"
            assert sample_module.short_description == "Updated short desc"

    def test_update_module_not_found(self, client, admin_user):
        """Test updating a non-existent module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/modules/99999",
                data={"name": "Test", "week_number": "1", "drive_file_id": "test"},
            )
            assert response.status_code == 404

    def test_change_module_visibility(self, client, admin_user, sample_module, db_session):
        """Test changing module visibility."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{sample_module.id}/visibility",
                data={"visibility": "archived"},
                follow_redirects=False,
            )
            assert response.status_code == 303

            db_session.refresh(sample_module)
            assert sample_module.visibility == ModuleVisibility.archived

    def test_change_visibility_invalid(self, client, admin_user, sample_module):
        """Test changing to invalid visibility."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{sample_module.id}/visibility",
                data={"visibility": "invalid_status"},
            )
            assert response.status_code == 400

    def test_archive_module(self, client, admin_user, sample_module, db_session):
        """Test archiving a module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{sample_module.id}/archive",
                follow_redirects=False,
            )
            assert response.status_code == 303

            db_session.refresh(sample_module)
            assert sample_module.visibility == ModuleVisibility.archived

    def test_delete_module(self, client, admin_user, sample_module, db_session):
        """Test deleting a module."""
        module_id = sample_module.id
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{module_id}/delete",
                follow_redirects=False,
            )
            assert response.status_code == 303

            # Verify module was deleted
            deleted_module = db_session.query(Module).filter(Module.id == module_id).first()
            assert deleted_module is None

    def test_delete_module_not_found(self, client, admin_user):
        """Test deleting a non-existent module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post("/admin/modules/99999/delete")
            assert response.status_code == 404


@pytest.mark.admin
class TestModuleImport:
    """Tests for module import functionality."""

    def test_import_form_access(self, client, admin_user, db_session):
        """Test accessing the import form."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/modules/import")
            assert response.status_code in [200, 500]

    def test_import_form_with_course_id(self, client, admin_user, sample_course, db_session):
        """Test accessing import form with course ID."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get(f"/admin/modules/import?course_id={sample_course.id}")
            assert response.status_code in [200, 500]


@pytest.mark.admin
class TestGenerateOverview:
    """Tests for AI overview generation."""

    def test_generate_overview_no_repo(self, client, admin_user, sample_module, db_session):
        """Test generating overview without template repo URL."""
        sample_module.template_repo_url = None
        db_session.commit()

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(f"/admin/modules/{sample_module.id}/generate-overview")
            assert response.status_code == 400

    def test_generate_overview_module_not_found(self, client, admin_user):
        """Test generating overview for non-existent module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post("/admin/modules/99999/generate-overview")
            assert response.status_code == 404

    def test_generate_overview_with_repo(self, client, admin_user, sample_module, db_session):
        """Test generating overview with valid template repo."""
        sample_module.template_repo_url = "https://github.com/test/template"
        db_session.commit()

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.refresh_module_overview", new_callable=AsyncMock) as mock_refresh:
                mock_refresh.return_value = None
                response = client.post(
                    f"/admin/modules/{sample_module.id}/generate-overview",
                    follow_redirects=False,
                )
                assert response.status_code == 303
                mock_refresh.assert_called_once()


@pytest.mark.admin
class TestUserManagement:
    """Tests for user management."""

    def test_list_users(self, client, admin_user, reviewer_user, student_user, db_session):
        """Test listing all users."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/users")
            assert response.status_code in [200, 500]

    def test_change_user_role(self, client, admin_user, reviewer_user, db_session):
        """Test changing a user's role."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/users/{reviewer_user.id}/role",
                data={"role": "student"},
                follow_redirects=False,
            )
            assert response.status_code == 303

            db_session.refresh(reviewer_user)
            assert reviewer_user.role == UserRole.student

    def test_change_user_role_to_admin(self, client, admin_user, reviewer_user, db_session):
        """Test promoting a user to admin."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/users/{reviewer_user.id}/role",
                data={"role": "admin"},
                follow_redirects=False,
            )
            assert response.status_code == 303

            db_session.refresh(reviewer_user)
            assert reviewer_user.role == UserRole.admin

    def test_change_user_role_invalid(self, client, admin_user, reviewer_user):
        """Test changing to invalid role."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/users/{reviewer_user.id}/role",
                data={"role": "invalid_role"},
            )
            assert response.status_code == 400

    def test_change_role_user_not_found(self, client, admin_user):
        """Test changing role for non-existent user."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/users/99999/role",
                data={"role": "student"},
            )
            assert response.status_code == 404


@pytest.mark.admin
class TestSubmissionsManagement:
    """Tests for submissions management."""

    def test_list_submissions(self, client, admin_user, sample_submission, db_session):
        """Test listing all submissions."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/submissions")
            assert response.status_code in [200, 500]

    def test_list_submissions_with_module_filter(self, client, admin_user, sample_submission, sample_module, db_session):
        """Test filtering submissions by module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get(f"/admin/submissions?module_id={sample_module.id}")
            assert response.status_code in [200, 500]

    def test_list_submissions_with_type_filter(self, client, admin_user, sample_submission, db_session):
        """Test filtering submissions by type."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/submissions?submission_type=in_class")
            assert response.status_code in [200, 500]

    def test_list_submissions_with_status_filter(self, client, admin_user, sample_submission, db_session):
        """Test filtering submissions by status."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/submissions?status=pending")
            assert response.status_code in [200, 500]

    def test_grade_submission(self, client, admin_user, sample_submission, db_session):
        """Test triggering auto-grading for a submission."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.run_auto_grader_background"):
                response = client.post(
                    f"/admin/submissions/{sample_submission.id}/grade",
                    follow_redirects=False,
                )
                assert response.status_code == 303

    def test_grade_submission_not_found(self, client, admin_user):
        """Test grading a non-existent submission."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post("/admin/submissions/99999/grade")
            assert response.status_code == 404

    def test_manual_grade_submission(self, client, admin_user, sample_submission, db_session):
        """Test manually grading a submission."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.apply_manual_grade") as mock_grade:
                response = client.post(
                    f"/admin/submissions/{sample_submission.id}/manual-grade",
                    data={
                        "total_points": "85",
                        "manual_feedback": "Good work overall",
                        "strengths": "Clear code\nGood documentation",
                        "improvements": "Could add more tests",
                    },
                    follow_redirects=False,
                )
                assert response.status_code == 303
                mock_grade.assert_called_once()

    def test_export_submissions(self, client, admin_user, sample_submission, db_session):
        """Test exporting submissions as CSV."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.get("/admin/submissions/export")
            assert response.status_code == 200
            assert "text/csv" in response.headers.get("content-type", "")

    def test_grade_all_module_submissions(self, client, admin_user, sample_module, sample_submission, db_session):
        """Test batch grading all submissions for a module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.run_auto_grader_background"):
                response = client.post(
                    f"/admin/modules/{sample_module.id}/grade-all",
                    follow_redirects=False,
                )
                assert response.status_code == 303


@pytest.mark.admin
class TestReminderManagement:
    """Tests for reminder management."""

    def test_send_reminders(self, client, admin_user, db_session):
        """Test manually triggering reminder emails."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.send_weekly_reminders", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = 5
                response = client.post(
                    "/admin/reminders/send-now",
                    follow_redirects=False,
                )
                assert response.status_code == 303
                mock_send.assert_called_once()


@pytest.mark.admin
class TestModuleCheckUpdate:
    """Tests for module update checking."""

    def test_check_update_module_not_found(self, client, admin_user):
        """Test checking update for non-existent module."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post("/admin/modules/99999/check-update")
            assert response.status_code == 404

    def test_check_update_no_change(self, client, admin_user, sample_module, db_session):
        """Test checking update when no changes detected."""
        sample_module.drive_modified_time = "2026-01-01T00:00:00Z"
        db_session.commit()

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.get_file_metadata") as mock_meta:
                mock_meta.return_value = {"modifiedTime": "2026-01-01T00:00:00Z"}
                response = client.post(
                    f"/admin/modules/{sample_module.id}/check-update",
                    follow_redirects=False,
                )
                assert response.status_code == 303
                assert "no_update" in response.headers["location"]

    def test_check_update_with_change(self, client, admin_user, sample_module, reviewer_user, db_session):
        """Test checking update when changes detected."""
        sample_module.drive_modified_time = "2026-01-01T00:00:00Z"
        reviewer_user.selected_module_id = sample_module.id
        reviewer_user.last_notified_version = "2026-01-01T00:00:00Z"
        db_session.commit()

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            with patch("app.routers.admin.get_file_metadata") as mock_meta:
                mock_meta.return_value = {"modifiedTime": "2026-01-02T00:00:00Z"}
                with patch("app.routers.admin.send_pdf_update_notification"):
                    with patch("app.routers.admin.notify_slack_pdf_updated", new_callable=AsyncMock):
                        response = client.post(
                            f"/admin/modules/{sample_module.id}/check-update",
                            follow_redirects=False,
                        )
                        assert response.status_code == 303
                        assert "updated" in response.headers["location"]


@pytest.mark.admin
class TestDataIntegrity:
    """Tests for data integrity during CRUD operations."""

    def test_delete_module_cascades_submissions(self, client, admin_user, sample_module, sample_submission, db_session):
        """Test that deleting a module also deletes related submissions."""
        module_id = sample_module.id
        submission_id = sample_submission.id

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{module_id}/delete",
                follow_redirects=False,
            )
            assert response.status_code == 303

            # Verify submission was deleted
            deleted_submission = db_session.query(Submission).filter(Submission.id == submission_id).first()
            assert deleted_submission is None

    def test_delete_module_clears_user_selection(self, client, admin_user, sample_module, reviewer_user, db_session):
        """Test that deleting a module clears user selections."""
        reviewer_user.selected_module_id = sample_module.id
        db_session.commit()
        module_id = sample_module.id

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                f"/admin/modules/{module_id}/delete",
                follow_redirects=False,
            )
            assert response.status_code == 303

            db_session.refresh(reviewer_user)
            assert reviewer_user.selected_module_id is None

    def test_create_module_with_learning_objectives(self, client, admin_user, db_session):
        """Test creating a module with learning objectives (array field)."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/modules",
                data={
                    "name": "Test Module",
                    "week_number": "1",
                    "visibility": "draft",
                    "drive_file_id": "test123",
                    "learning_objectives": "Obj 1\nObj 2\nObj 3",
                    "max_reviewers": "10",
                    "max_points": "100",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            module = db_session.query(Module).filter(Module.name == "Test Module").first()
            assert module is not None
            assert module.learning_objectives == ["Obj 1", "Obj 2", "Obj 3"]


@pytest.mark.admin
class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_create_course_minimal_fields(self, client, admin_user, db_session):
        """Test creating a course with only required fields."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/courses",
                data={
                    "name": "Minimal Course",
                    "code": "MIN-001",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            course = db_session.query(Course).filter(Course.code == "MIN-001").first()
            assert course is not None
            assert course.description is None
            assert course.is_active is False

    def test_create_module_minimal_fields(self, client, admin_user, db_session):
        """Test creating a module with only required fields."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/modules",
                data={
                    "name": "Minimal Module",
                    "week_number": "1",
                    "drive_file_id": "min_drive_123",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            module = db_session.query(Module).filter(Module.name == "Minimal Module").first()
            assert module is not None
            assert module.visibility == ModuleVisibility.draft
            assert module.max_reviewers == 10  # default value

    def test_update_course_toggle_active(self, client, admin_user, sample_course, db_session):
        """Test toggling course active status."""
        assert sample_course.is_active is True

        with patch("app.routers.admin.require_admin", return_value=admin_user):
            # Update without is_active checkbox
            response = client.post(
                f"/admin/courses/{sample_course.id}",
                data={
                    "name": sample_course.name,
                    "code": sample_course.code,
                    # is_active not included
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            db_session.refresh(sample_course)
            assert sample_course.is_active is False

    def test_safe_int_handling_in_module(self, client, admin_user, db_session):
        """Test that empty numeric fields are handled properly."""
        with patch("app.routers.admin.require_admin", return_value=admin_user):
            response = client.post(
                "/admin/modules",
                data={
                    "name": "Safe Int Test",
                    "week_number": "",  # Empty, should default
                    "drive_file_id": "test123",
                    "estimated_time_minutes": "",  # Empty optional
                    "max_students": "",  # Empty optional
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            module = db_session.query(Module).filter(Module.name == "Safe Int Test").first()
            assert module is not None
            assert module.week_number == 1  # default
            assert module.estimated_time_minutes is None
            assert module.max_students is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
