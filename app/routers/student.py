"""Student portal routes."""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_user
from app.models import Course, Module, ModuleVisibility, Submission, Grade, User, UserRole
from app.services.github import github_service

router = APIRouter(prefix="/student", tags=["student"])
templates = Jinja2Templates(directory="templates")


def get_current_week(course: Course) -> int:
    """Calculate the current week number based on course start date."""
    if not course.start_date:
        return 99  # No start date = all weeks unlocked

    today = datetime.utcnow().date()
    start = course.start_date.date()

    if today < start:
        return 0  # Course hasn't started

    days_elapsed = (today - start).days
    return (days_elapsed // 7) + 1


def is_module_unlocked(module: Module, current_week: int) -> bool:
    """Check if a module is unlocked based on current week."""
    return module.week_number <= current_week


def get_student_submission_status(user_id: int, module_id: int, db: Session) -> dict:
    """Get submission and grade status for a student's module."""
    result = {
        "in_class": {"submitted": False, "grade": None, "status": "not_started"},
        "homework": {"submitted": False, "grade": None, "status": "not_started"},
    }

    for sub_type in ["in_class", "homework"]:
        submission = (
            db.query(Submission)
            .filter(
                Submission.user_id == user_id,
                Submission.module_id == module_id,
                Submission.submission_type == sub_type,
            )
            .first()
        )

        if submission:
            result[sub_type]["submitted"] = True
            result[sub_type]["submission"] = submission
            result[sub_type]["status"] = "submitted"

            grade = (
                db.query(Grade)
                .filter(Grade.submission_id == submission.id)
                .first()
            )

            if grade:
                result[sub_type]["grade"] = grade
                if grade.status == "completed":
                    result[sub_type]["status"] = "graded"
                elif grade.status == "running":
                    result[sub_type]["status"] = "grading"
                elif grade.status == "failed":
                    result[sub_type]["status"] = "failed"

    return result


@router.get("", response_class=HTMLResponse)
async def student_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Student dashboard showing all modules with weekly unlock."""
    # Get active courses with their modules
    courses = (
        db.query(Course)
        .filter(Course.is_active == True)
        .order_by(Course.name)
        .all()
    )

    courses_data = []
    for course in courses:
        current_week = get_current_week(course)

        # Get active modules for this course
        modules = (
            db.query(Module)
            .filter(
                Module.course_id == course.id,
                Module.visibility == ModuleVisibility.active,
            )
            .order_by(Module.week_number)
            .all()
        )

        modules_data = []
        for module in modules:
            unlocked = is_module_unlocked(module, current_week)
            status = get_student_submission_status(user.id, module.id, db)

            # Calculate progress
            total_items = 2  # in_class + homework
            completed = 0
            if status["in_class"]["status"] == "graded":
                completed += 1
            if status["homework"]["status"] == "graded":
                completed += 1

            modules_data.append({
                "module": module,
                "unlocked": unlocked,
                "status": status,
                "progress": completed,
                "total": total_items,
                "in_class_submitted": status["in_class"]["submitted"],
                "homework_submitted": status["homework"]["submitted"],
            })

        if modules_data:
            courses_data.append({
                "course": course,
                "current_week": current_week,
                "modules": modules_data,
            })

    return templates.TemplateResponse(
        "student/dashboard.html",
        {
            "request": request,
            "user": user,
            "courses_data": courses_data,
        },
    )


@router.get("/module/{module_id}", response_class=HTMLResponse)
async def student_module_view(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """View a specific module as a student."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if module.visibility != ModuleVisibility.active:
        raise HTTPException(status_code=403, detail="Module not available")

    # Check if module is unlocked
    course = db.query(Course).filter(Course.id == module.course_id).first()
    if course:
        current_week = get_current_week(course)
        if not is_module_unlocked(module, current_week):
            raise HTTPException(
                status_code=403,
                detail=f"This module unlocks in Week {module.week_number}. Current week: {current_week}",
            )

    # Get submission status
    submission_status = get_student_submission_status(user.id, module.id, db)

    return templates.TemplateResponse(
        "student/module.html",
        {
            "request": request,
            "user": user,
            "module": module,
            "course": course,
            "submission_status": submission_status,
        },
    )


@router.get("/module/{module_id}/submit/{submission_type}", response_class=HTMLResponse)
async def student_submit_form(
    module_id: int,
    submission_type: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Show submission form for students."""
    if submission_type not in ["in_class", "homework"]:
        raise HTTPException(status_code=400, detail="Invalid submission type")

    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if module.visibility != ModuleVisibility.active:
        raise HTTPException(status_code=403, detail="Module not available")

    # Check existing submission
    existing = (
        db.query(Submission)
        .filter(
            Submission.user_id == user.id,
            Submission.module_id == module.id,
            Submission.submission_type == submission_type,
        )
        .first()
    )

    return templates.TemplateResponse(
        "student/submit.html",
        {
            "request": request,
            "user": user,
            "module": module,
            "submission_type": submission_type,
            "existing": existing,
        },
    )


@router.post("/module/{module_id}/submit/{submission_type}")
async def student_submit(
    module_id: int,
    submission_type: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Handle student submission."""
    if submission_type not in ["in_class", "homework"]:
        raise HTTPException(status_code=400, detail="Invalid submission type")

    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    form = await request.form()
    github_link = form.get("github_link", "").strip()
    comments = form.get("comments", "").strip()

    # Validate GitHub URL
    if not github_link:
        raise HTTPException(status_code=400, detail="GitHub link is required")

    if not github_link.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="Please provide a valid GitHub URL")

    # Check for existing submission
    existing = (
        db.query(Submission)
        .filter(
            Submission.user_id == user.id,
            Submission.module_id == module.id,
            Submission.submission_type == submission_type,
        )
        .first()
    )

    if existing:
        # Update existing
        existing.github_link = github_link.rstrip("/")
        existing.comments = comments
        existing.submitted_at = datetime.utcnow()
        submission = existing
    else:
        # Create new
        submission = Submission(
            user_id=user.id,
            module_id=module.id,
            submission_type=submission_type,
            github_link=github_link.rstrip("/"),
            comments=comments,
        )
        db.add(submission)

    db.commit()

    return RedirectResponse(
        url=f"/student/module/{module_id}?submitted={submission_type}",
        status_code=303,
    )


@router.get("/submission/{submission_id}/github-grade", response_class=HTMLResponse)
async def view_github_grade(
    submission_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """View detailed grade from GitHub Actions."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if submission.user_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Access denied")

    module = db.query(Module).filter(Module.id == submission.module_id).first()

    # Get workflow status
    workflow_status = await github_service.get_workflow_run_status(submission.github_link)

    # Try to get grade report
    grade_report = None
    if workflow_status.get("status") == "completed" and workflow_status.get("conclusion") == "success":
        grade_report = await github_service.fetch_grade_report(submission.github_link)

    return templates.TemplateResponse(
        "student/github_grade.html",
        {
            "request": request,
            "user": user,
            "submission": submission,
            "module": module,
            "workflow_status": workflow_status,
            "grade_report": grade_report,
        },
    )


@router.post("/submission/{submission_id}/refresh-grade")
async def refresh_github_grade(
    submission_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Fetch latest grade from GitHub and update local database."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if submission.user_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Access denied")

    # Fetch grade report from GitHub
    grade_report = await github_service.fetch_grade_report(submission.github_link)

    if grade_report:
        # Update or create Grade record
        grade = db.query(Grade).filter(Grade.submission_id == submission.id).first()

        if not grade:
            grade = Grade(submission_id=submission.id)
            db.add(grade)

        grade.status = "completed"
        grade.total_points = grade_report.total
        grade.max_points = grade_report.max_score
        grade.graded_at = grade_report.timestamp

        # Store detailed report as JSON
        grade.feedback = json.dumps({
            "sections": [
                {
                    "name": s.name,
                    "score": s.score,
                    "max_score": s.max_score,
                    "details": s.details,
                }
                for s in grade_report.sections
            ],
            "errors": grade_report.errors,
            "workflow_url": grade_report.workflow_url,
        })

        db.commit()

    return RedirectResponse(
        url=f"/student/submission/{submission_id}/github-grade?refreshed=1",
        status_code=303,
    )
