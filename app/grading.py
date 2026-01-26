"""Automated grading system for submissions."""
import json
import subprocess
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Grade, Module, Submission, User
from app.notifications import send_grade_notification
from app.slack import notify_slack_grade_completed


def calculate_letter_grade(percentage: float) -> str:
    """Convert percentage to letter grade."""
    if percentage >= 93:
        return "A"
    if percentage >= 90:
        return "A-"
    if percentage >= 87:
        return "B+"
    if percentage >= 83:
        return "B"
    if percentage >= 80:
        return "B-"
    if percentage >= 77:
        return "C+"
    if percentage >= 73:
        return "C"
    if percentage >= 70:
        return "C-"
    if percentage >= 67:
        return "D+"
    if percentage >= 63:
        return "D"
    if percentage >= 60:
        return "D-"
    return "F"


def run_basic_checks(repo_path: Path, module: Module) -> dict:
    """Basic grading when no custom script is configured."""
    points = 0
    max_points = 100
    breakdown = {}
    strengths = []
    improvements = []

    # Check for README
    readme_exists = (repo_path / "README.md").exists()
    if readme_exists:
        points += 10
        breakdown["documentation"] = 10
        strengths.append("README.md is present")
    else:
        breakdown["documentation"] = 0
        improvements.append("Add a README.md with setup instructions and reflection")

    # Check for Python files
    py_files = list(repo_path.glob("**/*.py"))
    if len(py_files) >= 3:
        points += 20
        breakdown["code_structure"] = 20
        strengths.append(f"Good code organization with {len(py_files)} Python files")
    elif len(py_files) >= 1:
        points += 10
        breakdown["code_structure"] = 10
        improvements.append("Consider organizing code into more modular files")
    else:
        breakdown["code_structure"] = 0
        improvements.append("No Python files found in submission")

    # Check for requirements.txt or environment.yml
    has_deps = (repo_path / "requirements.txt").exists() or (
        repo_path / "environment.yml"
    ).exists()
    if has_deps:
        points += 10
        breakdown["dependencies"] = 10
        strengths.append("Dependencies are properly documented")
    else:
        breakdown["dependencies"] = 0
        improvements.append("Add requirements.txt or environment.yml for reproducibility")

    # Remaining points require manual review
    breakdown["implementation"] = 0
    breakdown["manual_review_pending"] = 60
    feedback = "Basic checks completed. Full grading requires instructor review."

    return {
        "total_points": points,
        "breakdown": breakdown,
        "feedback": feedback,
        "strengths": strengths,
        "improvements": improvements,
    }


async def run_auto_grader(submission_id: int, db: Session) -> Grade:
    """
    Run automated grading for a submission.

    This clones the student's repo, runs evaluation scripts,
    and stores the results.
    """
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError(f"Submission {submission_id} not found")

    module = submission.module
    user = submission.user

    # Create or get existing grade record
    grade = db.query(Grade).filter(Grade.submission_id == submission_id).first()
    if not grade:
        grade = Grade(submission_id=submission_id, status="pending")
        db.add(grade)
        db.flush()

    grade.status = "running"
    db.commit()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Clone student repo
            student_repo_path = Path(tmpdir) / "student"
            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    submission.github_link,
                    str(student_repo_path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                grade.status = "failed"
                grade.automated_feedback = f"Failed to clone repository: {result.stderr}"
                db.commit()
                return grade

            # Note: Primary grading is now handled by GitHub Classroom autograder.
            # This runs basic structural checks as a fallback/supplement.
            grading_output = run_basic_checks(student_repo_path, module)

            # Update grade record
            grade.total_points = Decimal(str(grading_output.get("total_points", 0)))
            grade.max_points = module.max_points
            percentage = (float(grade.total_points) / grade.max_points) * 100
            grade.percentage = Decimal(str(round(percentage, 2)))
            grade.letter_grade = calculate_letter_grade(percentage)
            grade.score_breakdown = grading_output.get("breakdown", {})
            grade.automated_feedback = grading_output.get("feedback", "")
            grade.strengths = grading_output.get("strengths", [])
            grade.improvements = grading_output.get("improvements", [])
            grade.status = "completed"
            grade.graded_at = datetime.utcnow()
            grade.graded_by = "auto"

    except subprocess.TimeoutExpired:
        grade.status = "failed"
        grade.automated_feedback = (
            "Grading timed out. Please check your code for infinite loops."
        )
    except Exception as e:
        grade.status = "failed"
        grade.automated_feedback = f"Unexpected error: {str(e)}"

    db.commit()

    # Send notifications if grading completed successfully
    if grade.status == "completed":
        # Email notification
        send_grade_notification(
            to_email=user.email,
            user_name=user.name or user.email,
            module_name=module.name,
            submission_type=submission.submission_type,
            submission_id=submission.id,
            total_points=float(grade.total_points),
            max_points=grade.max_points,
            letter_grade=grade.letter_grade,
        )

        # Slack notification
        await notify_slack_grade_completed(
            user_name=user.name or user.email,
            module_name=module.name,
            submission_type=submission.submission_type,
            total_points=float(grade.total_points),
            max_points=grade.max_points,
            letter_grade=grade.letter_grade,
        )

    return grade


def apply_manual_grade(
    submission_id: int,
    total_points: Decimal,
    manual_feedback: Optional[str],
    strengths: Optional[list[str]],
    improvements: Optional[list[str]],
    graded_by: str,
    db: Session,
) -> Grade:
    """Apply or override grade with manual grading."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise ValueError(f"Submission {submission_id} not found")

    module = submission.module

    # Get or create grade record
    grade = db.query(Grade).filter(Grade.submission_id == submission_id).first()
    if not grade:
        grade = Grade(submission_id=submission_id)
        db.add(grade)

    # Update with manual grade
    grade.total_points = total_points
    grade.max_points = module.max_points
    percentage = (float(total_points) / module.max_points) * 100
    grade.percentage = Decimal(str(round(percentage, 2)))
    grade.letter_grade = calculate_letter_grade(percentage)

    if manual_feedback:
        grade.manual_feedback = manual_feedback
    if strengths:
        grade.strengths = strengths
    if improvements:
        grade.improvements = improvements

    grade.status = "completed"
    grade.graded_at = datetime.utcnow()
    grade.graded_by = graded_by

    db.commit()
    return grade
