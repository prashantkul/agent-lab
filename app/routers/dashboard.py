"""Dashboard routes."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_user
from app.models import Module, ModuleVisibility, Submission, Grade, User, UserRole

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


def get_user_submission_status(user_id: int, module_id: int, db: Session) -> dict:
    """Get submission and grade status for a user's module."""
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


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Main dashboard - shows module selection or current module."""
    # Check if user has selected a module
    if user.selected_module_id:
        module = db.query(Module).filter(Module.id == user.selected_module_id).first()
        if module:
            # Check for PDF updates
            pdf_updated = (
                module.drive_modified_time
                and module.drive_modified_time != user.last_notified_version
            )

            # Get submission status
            submission_status = get_user_submission_status(user.id, module.id, db)

            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "user": user,
                    "module": module,
                    "pdf_updated": pdf_updated,
                    "submission_status": submission_status,
                },
            )

    # No module selected - show module selection
    # Get modules visible to user based on role
    if user.role == UserRole.ADMIN:
        # Admins see all modules
        modules = db.query(Module).order_by(Module.week_number).all()
    elif user.role == UserRole.STUDENT:
        # Students see active modules
        modules = (
            db.query(Module)
            .filter(Module.visibility == ModuleVisibility.ACTIVE)
            .order_by(Module.week_number)
            .all()
        )
    else:
        # Reviewers see pilot_review and active modules
        modules = (
            db.query(Module)
            .filter(
                Module.visibility.in_(
                    [ModuleVisibility.PILOT_REVIEW, ModuleVisibility.ACTIVE]
                )
            )
            .order_by(Module.week_number)
            .all()
        )

    # Get reviewer counts for each module
    module_stats = {}
    for module in modules:
        reviewer_count = (
            db.query(func.count(User.id))
            .filter(
                User.selected_module_id == module.id,
                User.role == UserRole.REVIEWER,
            )
            .scalar()
        )
        student_count = (
            db.query(func.count(User.id))
            .filter(
                User.selected_module_id == module.id,
                User.role == UserRole.STUDENT,
            )
            .scalar()
        )
        module_stats[module.id] = {
            "reviewer_count": reviewer_count,
            "student_count": student_count,
        }

    return templates.TemplateResponse(
        "module_select.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "module_stats": module_stats,
        },
    )


@router.get("/settings/reminders", response_class=HTMLResponse)
async def reminder_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """User reminder settings page."""
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
        },
    )


@router.post("/settings/reminders")
async def update_reminder_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Update user reminder preferences."""
    form = await request.form()
    enabled = form.get("reminder_enabled") == "on"
    user.reminder_enabled = enabled
    db.commit()
    return RedirectResponse(url="/settings/reminders?saved=1", status_code=303)
