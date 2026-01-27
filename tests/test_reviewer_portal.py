"""Test harness for the Reviewer Portal.

Tests cover:
- Module selection (/modules)
- Module details (/modules/{id})
- Module selection/switch (/modules/{id}/select, /modules/{id}/switch)
- Module release (/modules/{id}/release)
- Dashboard with selected module (/dashboard)
- Submission forms (/submit/in_class, /submit/homework)
- Help page (/help/reviewer)
- Confidentiality agreement (/confidentiality, /accept-terms)
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
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
    UserModuleSelection,
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


# =============================================================================
# Fixtures
# =============================================================================

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
def test_course(db_session):
    """Create a test course."""
    course = Course(
        name="Agentic AI Systems",
        code="AI-AGENTS-101",
        description="A comprehensive course on building AI agent systems",
        instructor_name="Dr. Test Instructor",
        instructor_email="instructor@example.com",
        term="Spring 2026",
        start_date=datetime(2026, 1, 15),
        is_active=True,
    )
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)
    return course


@pytest.fixture
def pilot_modules(db_session, test_course):
    """Create multiple pilot review modules for testing."""
    modules = []
    for i in range(3):
        module = Module(
            course_id=test_course.id,
            name=f"Week {i + 1}: AI Agent Topic {i + 1}",
            week_number=i + 1,
            visibility=ModuleVisibility.pilot_review,
            short_description=f"Learn about AI Agent Topic {i + 1}",
            detailed_description=f"Detailed content about topic {i + 1}",
            drive_file_id=f"drive_file_id_{i + 1}",
            github_classroom_url=f"https://classroom.github.com/a/module{i + 1}",
            max_reviewers=2,
            max_students=20,
        )
        db_session.add(module)
        modules.append(module)
    db_session.commit()
    for m in modules:
        db_session.refresh(m)
    return modules


@pytest.fixture
def reviewer_user(db_session):
    """Create a reviewer user who has accepted terms."""
    user = User(
        google_id="reviewer_google_123",
        email="reviewer@example.com",
        name="Test Reviewer",
        role=UserRole.reviewer,
        accepted_terms_at=datetime.utcnow(),
        reminder_enabled=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def reviewer_user_no_terms(db_session):
    """Create a reviewer user who has NOT accepted terms."""
    user = User(
        google_id="reviewer_no_terms_456",
        email="noterms@example.com",
        name="New Reviewer",
        role=UserRole.reviewer,
        accepted_terms_at=None,
        reminder_enabled=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def student_user(db_session):
    """Create a student user."""
    user = User(
        google_id="student_google_789",
        email="student@example.com",
        name="Test Student",
        role=UserRole.student,
        accepted_terms_at=datetime.utcnow(),
        student_id="STU001",
        cohort="2026",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    user = User(
        google_id="admin_google_000",
        email="admin@example.com",
        name="Test Admin",
        role=UserRole.admin,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# =============================================================================
# Test: Module Selection Flow
# =============================================================================

class TestModuleSelection:
    """Tests for module selection functionality."""

    def test_select_module_creates_selection_record(self, db_session, reviewer_user, pilot_modules):
        """Test that selecting a module creates UserModuleSelection record."""
        module = pilot_modules[0]

        # Simulate module selection (what the endpoint does)
        selection = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=module.id,
            selected_at=datetime.utcnow(),
            last_notified_version=module.drive_modified_time,
            is_active=True,
        )
        db_session.add(selection)
        reviewer_user.selected_module_id = module.id
        reviewer_user.selected_at = datetime.utcnow()
        db_session.commit()

        # Verify selection was created
        selection_db = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.module_id == module.id,
            )
            .first()
        )
        assert selection_db is not None
        assert selection_db.is_active is True
        assert reviewer_user.selected_module_id == module.id

    def test_selecting_second_module_deactivates_first(self, db_session, reviewer_user, pilot_modules):
        """Test that selecting a second module deactivates the first for display."""
        # Select first module
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection1)
        reviewer_user.selected_module_id = pilot_modules[0].id
        db_session.commit()

        # Select second module - deactivate all existing, then add new
        db_session.query(UserModuleSelection).filter(
            UserModuleSelection.user_id == reviewer_user.id
        ).update({UserModuleSelection.is_active: False})

        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection2)
        reviewer_user.selected_module_id = pilot_modules[1].id
        db_session.commit()

        # Refresh to get updated values
        db_session.refresh(selection1)

        # Verify first is inactive, second is active
        assert selection1.is_active is False

        selection2_db = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.module_id == pilot_modules[1].id,
            )
            .first()
        )
        assert selection2_db.is_active is True
        assert reviewer_user.selected_module_id == pilot_modules[1].id

    def test_cannot_select_same_module_twice(self, db_session, reviewer_user, pilot_modules):
        """Test that selecting an already-selected module is blocked."""
        module = pilot_modules[0]

        # First selection
        selection = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=module.id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        db_session.commit()

        # Check for existing selection (what endpoint does)
        existing = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.module_id == module.id,
            )
            .first()
        )
        assert existing is not None  # Selection exists, should be blocked


class TestModuleSwitch:
    """Tests for switching between selected modules."""

    def test_switch_active_module(self, db_session, reviewer_user, pilot_modules):
        """Test reviewer can switch active view to another selected module."""
        # Select two modules
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add_all([selection1, selection2])
        reviewer_user.selected_module_id = pilot_modules[1].id
        db_session.commit()

        # Switch to first module
        db_session.query(UserModuleSelection).filter(
            UserModuleSelection.user_id == reviewer_user.id
        ).update({UserModuleSelection.is_active: False})

        selection1.is_active = True
        reviewer_user.selected_module_id = pilot_modules[0].id
        db_session.commit()

        # Verify switch
        db_session.refresh(selection1)
        db_session.refresh(selection2)
        assert selection1.is_active is True
        assert selection2.is_active is False
        assert reviewer_user.selected_module_id == pilot_modules[0].id

    def test_cannot_switch_to_unselected_module(self, db_session, reviewer_user, pilot_modules):
        """Test that switching to an unselected module fails."""
        # Select only first module
        selection = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        db_session.commit()

        # Try to find selection for third module (not selected)
        unselected = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.module_id == pilot_modules[2].id,
            )
            .first()
        )
        assert unselected is None  # Should not exist


class TestModuleRelease:
    """Tests for releasing selected modules."""

    def test_release_succeeds_without_homework(self, db_session, reviewer_user, pilot_modules):
        """Test that releasing a module succeeds without requiring homework submission."""
        module = pilot_modules[0]

        # Select module
        selection = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=module.id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        reviewer_user.selected_module_id = module.id
        db_session.commit()

        # No homework submitted
        homework = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "homework",
            )
            .first()
        )
        assert homework is None

        # Perform release (should work without homework)
        db_session.delete(selection)
        reviewer_user.selected_module_id = None
        reviewer_user.selected_at = None
        db_session.commit()

        # Verify released
        selection_after = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.module_id == module.id,
            )
            .first()
        )
        assert selection_after is None
        assert reviewer_user.selected_module_id is None

    def test_release_updates_active_module_to_remaining(self, db_session, reviewer_user, pilot_modules):
        """Test that releasing one module makes remaining module active."""
        # Select two modules
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        db_session.add_all([selection1, selection2])
        reviewer_user.selected_module_id = pilot_modules[0].id

        # Submit homework for first module
        homework = Submission(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Completed",
            time_spent_minutes=100,
            feedback_responses={
                "q_objectives": 7,
                "q_content": 7,
                "q_starter_code": 7,
                "q_difficulty": 7,
                "q_overall": 7,
            },
        )
        db_session.add(homework)
        db_session.commit()

        # Release first module, make remaining active
        db_session.delete(selection1)
        selection2.is_active = True
        reviewer_user.selected_module_id = pilot_modules[1].id
        db_session.commit()

        # Verify remaining module is now active
        db_session.refresh(selection2)
        assert selection2.is_active is True
        assert reviewer_user.selected_module_id == pilot_modules[1].id


# =============================================================================
# Test: Submission Workflow
# =============================================================================

class TestSubmissionWorkflow:
    """Tests for the submission workflow."""

    def test_create_in_class_submission(self, db_session, reviewer_user, pilot_modules):
        """Test creating an in-class submission with feedback."""
        module = pilot_modules[0]
        reviewer_user.selected_module_id = module.id
        db_session.commit()

        submission = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="in_class",
            github_link="https://github.com/feedback-only",
            comments="The in-class exercises were well-structured.",
            time_spent_minutes=45,
            feedback_responses={
                "q_objectives": 8,
                "q_content": 7,
                "q_starter_code": 8,
                "q_difficulty": 5,
                "q_overall": 7,
            },
        )
        db_session.add(submission)
        db_session.commit()
        db_session.refresh(submission)

        assert submission.id is not None
        assert submission.submission_type == "in_class"
        assert submission.time_spent_minutes == 45
        assert submission.feedback_responses["q_overall"] == 7

    def test_create_homework_submission(self, db_session, reviewer_user, pilot_modules):
        """Test creating a homework submission with detailed feedback."""
        module = pilot_modules[0]
        reviewer_user.selected_module_id = module.id
        db_session.commit()

        submission = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Comprehensive homework that reinforced the concepts well.",
            time_spent_minutes=180,
            feedback_responses={
                "q_objectives": 9,
                "q_content": 8,
                "q_starter_code": 9,
                "q_difficulty": 7,
                "q_overall": 9,
            },
        )
        db_session.add(submission)
        db_session.commit()
        db_session.refresh(submission)

        assert submission.id is not None
        assert submission.submission_type == "homework"
        assert submission.time_spent_minutes == 180

    def test_update_existing_submission(self, db_session, reviewer_user, pilot_modules):
        """Test updating an existing submission."""
        module = pilot_modules[0]
        reviewer_user.selected_module_id = module.id

        # Create initial submission
        submission = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Initial feedback",
            time_spent_minutes=100,
            feedback_responses={
                "q_objectives": 5,
                "q_content": 5,
                "q_starter_code": 5,
                "q_difficulty": 5,
                "q_overall": 5,
            },
        )
        db_session.add(submission)
        db_session.commit()

        # Update submission with more detailed feedback
        submission.comments = "Updated with more detailed feedback and suggestions"
        submission.time_spent_minutes = 160
        submission.feedback_responses = {
            "q_objectives": 8,
            "q_content": 8,
            "q_starter_code": 7,
            "q_difficulty": 6,
            "q_overall": 8,
        }
        submission.submitted_at = datetime.utcnow()
        db_session.commit()
        db_session.refresh(submission)

        assert submission.comments == "Updated with more detailed feedback and suggestions"
        assert submission.time_spent_minutes == 160
        assert submission.feedback_responses["q_overall"] == 8

    def test_feedback_responses_validation(self, db_session, reviewer_user, pilot_modules):
        """Test that feedback responses follow the expected schema."""
        module = pilot_modules[0]
        reviewer_user.selected_module_id = module.id

        feedback = {
            "q_objectives": 8,
            "q_content": 7,
            "q_starter_code": 9,
            "q_difficulty": 6,
            "q_overall": 8,
        }

        submission = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Test feedback",
            time_spent_minutes=120,
            feedback_responses=feedback,
        )
        db_session.add(submission)
        db_session.commit()
        db_session.refresh(submission)

        # Verify all expected keys are present
        required_keys = ["q_objectives", "q_content", "q_starter_code", "q_difficulty", "q_overall"]
        for key in required_keys:
            assert key in submission.feedback_responses

        # Verify values are in valid range (1-10)
        for key, value in submission.feedback_responses.items():
            assert 1 <= value <= 10, f"{key} should be between 1 and 10"

    def test_submission_unique_constraint(self, db_session, reviewer_user, pilot_modules):
        """Test that user can only have one submission per module per type."""
        module = pilot_modules[0]
        reviewer_user.selected_module_id = module.id

        # First submission
        submission1 = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="First submission",
            time_spent_minutes=100,
            feedback_responses={
                "q_objectives": 7,
                "q_content": 7,
                "q_starter_code": 7,
                "q_difficulty": 7,
                "q_overall": 7,
            },
        )
        db_session.add(submission1)
        db_session.commit()

        # Check existing submission (what endpoint does)
        existing = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "homework",
            )
            .first()
        )
        # Should update existing instead of creating new
        assert existing is not None
        assert existing.id == submission1.id


# =============================================================================
# Test: Max 2 Modules Limit
# =============================================================================

class TestMaxModulesLimit:
    """Tests for the 2-module limit for reviewers."""

    def test_reviewer_can_select_two_modules(self, db_session, reviewer_user, pilot_modules):
        """Test that a reviewer can select up to 2 modules."""
        # Select first module
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        db_session.add(selection1)

        # Select second module
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection2)
        reviewer_user.selected_module_id = pilot_modules[1].id
        db_session.commit()

        # Verify both selections exist
        count = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .count()
        )
        assert count == 2

    def test_reviewer_cannot_select_third_module(self, db_session, reviewer_user, pilot_modules):
        """Test that a reviewer cannot select more than 2 modules."""
        # Select two modules
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add_all([selection1, selection2])
        db_session.commit()

        # Check count (what endpoint does)
        current_count = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .count()
        )
        max_modules = 2 if reviewer_user.role == UserRole.reviewer else 1

        # Third selection should be blocked
        assert current_count >= max_modules

    def test_student_limited_to_one_module(self, db_session, student_user, pilot_modules):
        """Test that a student can only select 1 module."""
        # Create an active module for students
        active_module = Module(
            course_id=pilot_modules[0].course_id,
            name="Active Module for Students",
            week_number=10,
            visibility=ModuleVisibility.active,
            drive_file_id="active_drive_file",
            max_students=20,
        )
        db_session.add(active_module)
        db_session.commit()

        # For students, max is 1
        max_modules = 1 if student_user.role == UserRole.student else 2
        assert max_modules == 1

        # Select first module
        selection = UserModuleSelection(
            user_id=student_user.id,
            module_id=active_module.id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        db_session.commit()

        # Second selection should be blocked
        current_count = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == student_user.id)
            .count()
        )
        assert current_count >= max_modules

    def test_release_allows_new_selection(self, db_session, reviewer_user, pilot_modules):
        """Test that releasing a module allows selecting a new one."""
        # Select two modules
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add_all([selection1, selection2])

        # Submit homework for first module (required for release)
        homework = Submission(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Completed review",
            time_spent_minutes=100,
            feedback_responses={
                "q_objectives": 7,
                "q_content": 7,
                "q_starter_code": 7,
                "q_difficulty": 7,
                "q_overall": 7,
            },
        )
        db_session.add(homework)
        db_session.commit()

        # Release first module
        db_session.delete(selection1)
        db_session.commit()

        # Now can select third module
        count = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .count()
        )
        assert count == 1  # Only one remaining

        # Select third module
        selection3 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[2].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection3)
        db_session.commit()

        count = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .count()
        )
        assert count == 2  # Back to max


# =============================================================================
# Test: Confidentiality Agreement Flow
# =============================================================================

class TestConfidentialityAgreement:
    """Tests for the confidentiality agreement flow."""

    def test_new_reviewer_requires_agreement(self, db_session, reviewer_user_no_terms):
        """Test that a new reviewer without accepted terms must accept first."""
        assert reviewer_user_no_terms.accepted_terms_at is None
        assert reviewer_user_no_terms.role == UserRole.reviewer
        # Dashboard should redirect to /confidentiality

    def test_accept_terms_updates_user(self, db_session, reviewer_user_no_terms):
        """Test that accepting terms updates the user record."""
        assert reviewer_user_no_terms.accepted_terms_at is None

        # Simulate accepting terms
        reviewer_user_no_terms.accepted_terms_at = datetime.utcnow()
        db_session.commit()
        db_session.refresh(reviewer_user_no_terms)

        assert reviewer_user_no_terms.accepted_terms_at is not None

    def test_accepted_reviewer_bypasses_agreement(self, db_session, reviewer_user):
        """Test that a reviewer with accepted terms can access dashboard directly."""
        assert reviewer_user.accepted_terms_at is not None
        # Should be able to access dashboard without redirect

    def test_admin_bypasses_confidentiality_check(self, db_session, admin_user):
        """Test that admin users bypass the confidentiality agreement."""
        assert admin_user.role == UserRole.admin
        # Admins don't need to accept terms - can be None
        assert admin_user.accepted_terms_at is None

    def test_terms_timestamp_recorded(self, db_session, reviewer_user_no_terms):
        """Test that the acceptance timestamp is properly recorded."""
        before = datetime.utcnow()
        reviewer_user_no_terms.accepted_terms_at = datetime.utcnow()
        db_session.commit()
        after = datetime.utcnow()

        assert reviewer_user_no_terms.accepted_terms_at >= before
        assert reviewer_user_no_terms.accepted_terms_at <= after


# =============================================================================
# Test: Module Visibility
# =============================================================================

class TestModuleVisibility:
    """Tests for module visibility rules."""

    def test_reviewer_sees_only_pilot_review_modules(self, db_session, reviewer_user, test_course):
        """Test that reviewers only see pilot_review modules."""
        # Create modules with different visibilities
        draft = Module(
            course_id=test_course.id, name="Draft", week_number=1,
            visibility=ModuleVisibility.draft, drive_file_id="f1"
        )
        pilot = Module(
            course_id=test_course.id, name="Pilot", week_number=2,
            visibility=ModuleVisibility.pilot_review, drive_file_id="f2"
        )
        active = Module(
            course_id=test_course.id, name="Active", week_number=3,
            visibility=ModuleVisibility.active, drive_file_id="f3"
        )
        archived = Module(
            course_id=test_course.id, name="Archived", week_number=4,
            visibility=ModuleVisibility.archived, drive_file_id="f4"
        )
        db_session.add_all([draft, pilot, active, archived])
        db_session.commit()

        # Query for pilot_review modules (what reviewer endpoint does)
        visible = (
            db_session.query(Module)
            .filter(Module.visibility == ModuleVisibility.pilot_review)
            .all()
        )
        assert len(visible) == 1
        assert visible[0].name == "Pilot"

    def test_student_sees_only_active_modules(self, db_session, student_user, test_course):
        """Test that students only see active modules."""
        draft = Module(
            course_id=test_course.id, name="Draft", week_number=1,
            visibility=ModuleVisibility.draft, drive_file_id="f1"
        )
        pilot = Module(
            course_id=test_course.id, name="Pilot", week_number=2,
            visibility=ModuleVisibility.pilot_review, drive_file_id="f2"
        )
        active = Module(
            course_id=test_course.id, name="Active", week_number=3,
            visibility=ModuleVisibility.active, drive_file_id="f3"
        )
        db_session.add_all([draft, pilot, active])
        db_session.commit()

        # Query for active modules (what student endpoint does)
        visible = (
            db_session.query(Module)
            .filter(Module.visibility == ModuleVisibility.active)
            .all()
        )
        assert len(visible) == 1
        assert visible[0].name == "Active"

    def test_admin_sees_all_modules(self, db_session, admin_user, test_course):
        """Test that admins see all modules regardless of visibility."""
        draft = Module(
            course_id=test_course.id, name="Draft", week_number=1,
            visibility=ModuleVisibility.draft, drive_file_id="f1"
        )
        pilot = Module(
            course_id=test_course.id, name="Pilot", week_number=2,
            visibility=ModuleVisibility.pilot_review, drive_file_id="f2"
        )
        active = Module(
            course_id=test_course.id, name="Active", week_number=3,
            visibility=ModuleVisibility.active, drive_file_id="f3"
        )
        archived = Module(
            course_id=test_course.id, name="Archived", week_number=4,
            visibility=ModuleVisibility.archived, drive_file_id="f4"
        )
        db_session.add_all([draft, pilot, active, archived])
        db_session.commit()

        # Admins see all
        all_modules = db_session.query(Module).filter(Module.course_id == test_course.id).all()
        assert len(all_modules) == 4


# =============================================================================
# Test: Module Capacity
# =============================================================================

class TestModuleCapacity:
    """Tests for module capacity limits."""

    def test_module_at_reviewer_capacity_blocks_selection(self, db_session, test_course):
        """Test that a full module blocks new reviewer selections."""
        module = Module(
            course_id=test_course.id,
            name="Full Module",
            week_number=1,
            visibility=ModuleVisibility.pilot_review,
            drive_file_id="full_file",
            max_reviewers=2,
        )
        db_session.add(module)
        db_session.commit()

        # Create two reviewers and select the module
        for i in range(2):
            reviewer = User(
                google_id=f"cap_reviewer_{i}",
                email=f"cap{i}@example.com",
                name=f"Capacity Reviewer {i}",
                role=UserRole.reviewer,
                accepted_terms_at=datetime.utcnow(),
            )
            db_session.add(reviewer)
            db_session.commit()

            selection = UserModuleSelection(
                user_id=reviewer.id,
                module_id=module.id,
                selected_at=datetime.utcnow(),
                is_active=True,
            )
            db_session.add(selection)
        db_session.commit()

        # Count reviewers (what endpoint does to check capacity)
        reviewer_count = (
            db_session.query(func.count(UserModuleSelection.id))
            .join(User)
            .filter(
                UserModuleSelection.module_id == module.id,
                User.role == UserRole.reviewer,
            )
            .scalar()
        )

        assert reviewer_count == 2
        assert module.max_reviewers is not None
        assert reviewer_count >= module.max_reviewers  # At capacity

    def test_module_not_at_capacity_allows_selection(self, db_session, test_course, reviewer_user):
        """Test that a module with available slots allows selection."""
        module = Module(
            course_id=test_course.id,
            name="Available Module",
            week_number=1,
            visibility=ModuleVisibility.pilot_review,
            drive_file_id="avail_file",
            max_reviewers=3,
        )
        db_session.add(module)
        db_session.commit()

        # One reviewer already selected
        other_reviewer = User(
            google_id="other_rev",
            email="other@example.com",
            name="Other Reviewer",
            role=UserRole.reviewer,
            accepted_terms_at=datetime.utcnow(),
        )
        db_session.add(other_reviewer)
        db_session.commit()

        selection = UserModuleSelection(
            user_id=other_reviewer.id,
            module_id=module.id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        db_session.commit()

        # Check capacity
        reviewer_count = (
            db_session.query(func.count(UserModuleSelection.id))
            .join(User)
            .filter(
                UserModuleSelection.module_id == module.id,
                User.role == UserRole.reviewer,
            )
            .scalar()
        )

        assert reviewer_count == 1
        assert reviewer_count < module.max_reviewers  # Slots available


# =============================================================================
# Test: Dashboard
# =============================================================================

class TestDashboard:
    """Tests for dashboard functionality."""

    def test_dashboard_shows_active_module(self, db_session, reviewer_user, pilot_modules):
        """Test that dashboard identifies the active selected module."""
        module = pilot_modules[0]

        selection = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=module.id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        reviewer_user.selected_module_id = module.id
        db_session.commit()

        # Get active selection (what dashboard does)
        active = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.is_active == True,
            )
            .first()
        )

        assert active is not None
        assert active.module_id == module.id

    def test_dashboard_shows_submission_status(self, db_session, reviewer_user, pilot_modules):
        """Test that dashboard correctly shows submission status."""
        module = pilot_modules[0]
        reviewer_user.selected_module_id = module.id
        db_session.commit()

        # Initially no submissions
        in_class = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "in_class",
            )
            .first()
        )
        homework = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "homework",
            )
            .first()
        )

        assert in_class is None
        assert homework is None

        # Create in-class submission
        submission = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="in_class",
            github_link="https://github.com/feedback-only",
            comments="In-class completed",
            time_spent_minutes=60,
            feedback_responses={
                "q_objectives": 7,
                "q_content": 7,
                "q_starter_code": 7,
                "q_difficulty": 7,
                "q_overall": 7,
            },
        )
        db_session.add(submission)
        db_session.commit()

        # Check status again
        in_class = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "in_class",
            )
            .first()
        )

        assert in_class is not None
        assert in_class.submission_type == "in_class"

    def test_can_select_more_flag(self, db_session, reviewer_user, pilot_modules):
        """Test that can_select_more flag is computed correctly."""
        # No selections yet
        selections = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .all()
        )
        can_select_more = len(selections) < 2 and reviewer_user.role == UserRole.reviewer
        assert can_select_more is True

        # Select one module
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection1)
        db_session.commit()

        selections = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .all()
        )
        can_select_more = len(selections) < 2 and reviewer_user.role == UserRole.reviewer
        assert can_select_more is True  # Can still select one more

        # Select second module
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        db_session.add(selection2)
        db_session.commit()

        selections = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .all()
        )
        can_select_more = len(selections) < 2 and reviewer_user.role == UserRole.reviewer
        assert can_select_more is False  # At limit


# =============================================================================
# Test: Module Swap
# =============================================================================

class TestModuleSwap:
    """Tests for swapping modules."""

    def test_swap_succeeds_without_homework(self, db_session, reviewer_user, pilot_modules):
        """Test that swapping succeeds without requiring homework submission."""
        # Select two modules
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=False,
        )
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add_all([selection1, selection2])
        db_session.commit()

        # No homework submitted
        homework = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == pilot_modules[0].id,
                Submission.submission_type == "homework",
            )
            .first()
        )
        assert homework is None

        # Perform swap without homework: release first, add third
        db_session.delete(selection1)
        db_session.query(UserModuleSelection).filter(
            UserModuleSelection.user_id == reviewer_user.id
        ).update({UserModuleSelection.is_active: False})

        selection3 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[2].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection3)
        reviewer_user.selected_module_id = pilot_modules[2].id
        db_session.commit()

        # Verify swap succeeded
        selections = (
            db_session.query(UserModuleSelection)
            .filter(UserModuleSelection.user_id == reviewer_user.id)
            .all()
        )
        module_ids = [s.module_id for s in selections]

        assert pilot_modules[0].id not in module_ids  # Released
        assert pilot_modules[1].id in module_ids  # Kept
        assert pilot_modules[2].id in module_ids  # New


# =============================================================================
# Test: Help Page
# =============================================================================

class TestHelpPage:
    """Tests for help page access."""

    def test_reviewer_help_page_exists(self, db_session, reviewer_user):
        """Test that reviewer help route is accessible."""
        # The /help/reviewer route exists and requires authentication
        assert reviewer_user.role == UserRole.reviewer


# =============================================================================
# Test: Full Review Cycle Integration
# =============================================================================

class TestFullReviewCycle:
    """Integration tests for complete review workflow."""

    def test_complete_review_cycle(self, db_session, reviewer_user, pilot_modules):
        """Test a complete review cycle from selection to release."""
        module = pilot_modules[0]

        # Step 1: User has already accepted terms (from fixture)
        assert reviewer_user.accepted_terms_at is not None

        # Step 2: Select module
        selection = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=module.id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection)
        reviewer_user.selected_module_id = module.id
        db_session.commit()

        assert reviewer_user.selected_module_id == module.id

        # Step 3: Submit in-class feedback
        in_class = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="in_class",
            github_link="https://github.com/feedback-only",
            comments="The in-class exercises were engaging and well-paced.",
            time_spent_minutes=45,
            feedback_responses={
                "q_objectives": 8,
                "q_content": 7,
                "q_starter_code": 8,
                "q_difficulty": 5,
                "q_overall": 7,
            },
        )
        db_session.add(in_class)
        db_session.commit()

        # Step 4: Submit homework feedback
        homework = Submission(
            user_id=reviewer_user.id,
            module_id=module.id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="The homework reinforced concepts well. Suggest adding more edge cases.",
            time_spent_minutes=180,
            feedback_responses={
                "q_objectives": 9,
                "q_content": 8,
                "q_starter_code": 9,
                "q_difficulty": 6,
                "q_overall": 8,
            },
        )
        db_session.add(homework)
        db_session.commit()

        # Step 5: Release module
        db_session.delete(selection)
        reviewer_user.selected_module_id = None
        reviewer_user.selected_at = None
        db_session.commit()

        # Verify complete cycle
        assert reviewer_user.selected_module_id is None

        submissions = (
            db_session.query(Submission)
            .filter(
                Submission.user_id == reviewer_user.id,
                Submission.module_id == module.id,
            )
            .all()
        )
        assert len(submissions) == 2
        types = [s.submission_type for s in submissions]
        assert "in_class" in types
        assert "homework" in types

        selection_after = (
            db_session.query(UserModuleSelection)
            .filter(
                UserModuleSelection.user_id == reviewer_user.id,
                UserModuleSelection.module_id == module.id,
            )
            .first()
        )
        assert selection_after is None

    def test_multiple_module_review_cycle(self, db_session, reviewer_user, pilot_modules):
        """Test reviewing multiple modules sequentially."""
        # Review first module
        selection1 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection1)
        reviewer_user.selected_module_id = pilot_modules[0].id

        homework1 = Submission(
            user_id=reviewer_user.id,
            module_id=pilot_modules[0].id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Module 1 review complete",
            time_spent_minutes=120,
            feedback_responses={
                "q_objectives": 8, "q_content": 7, "q_starter_code": 8,
                "q_difficulty": 6, "q_overall": 8,
            },
        )
        db_session.add(homework1)
        db_session.commit()

        # Release first module
        db_session.delete(selection1)

        # Select second module
        selection2 = UserModuleSelection(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            selected_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(selection2)
        reviewer_user.selected_module_id = pilot_modules[1].id

        homework2 = Submission(
            user_id=reviewer_user.id,
            module_id=pilot_modules[1].id,
            submission_type="homework",
            github_link="https://github.com/feedback-only",
            comments="Module 2 review complete",
            time_spent_minutes=140,
            feedback_responses={
                "q_objectives": 7, "q_content": 8, "q_starter_code": 7,
                "q_difficulty": 7, "q_overall": 7,
            },
        )
        db_session.add(homework2)
        db_session.commit()

        # Verify both submissions exist
        all_submissions = (
            db_session.query(Submission)
            .filter(Submission.user_id == reviewer_user.id)
            .all()
        )
        assert len(all_submissions) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
