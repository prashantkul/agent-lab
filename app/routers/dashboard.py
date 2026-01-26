"""Dashboard routes."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_user
from app.models import Course, Module, ModuleVisibility, Submission, Grade, User, UserRole, UserModuleSelection

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


@router.get("/home", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Home page - portal selection for admins, redirect to dashboard for others."""
    # Check if user needs to accept confidentiality agreement
    if not user.accepted_terms_at and user.role != UserRole.admin:
        return RedirectResponse(url="/confidentiality", status_code=303)

    # For admins, show portal selection
    if user.role == UserRole.admin:
        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "user": user,
            },
        )

    # For non-admins, redirect to dashboard
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Main dashboard - shows module selection or current module."""
    # Check if user needs to accept confidentiality agreement
    if not user.accepted_terms_at and user.role != UserRole.admin:
        return RedirectResponse(url="/confidentiality", status_code=303)

    # Get user's module selections
    user_selections = (
        db.query(UserModuleSelection)
        .filter(UserModuleSelection.user_id == user.id)
        .order_by(UserModuleSelection.selected_at)
        .all()
    )

    # Get active module (the one being viewed)
    active_selection = next((s for s in user_selections if s.is_active), None)
    if not active_selection and user_selections:
        # If no active, make first one active
        active_selection = user_selections[0]
        active_selection.is_active = True
        db.commit()

    # Check if user has selected a module
    if active_selection:
        module = db.query(Module).filter(Module.id == active_selection.module_id).first()
        if module:
            # Check for PDF updates
            pdf_updated = (
                module.drive_modified_time
                and module.drive_modified_time != active_selection.last_notified_version
            )

            # Get submission status
            submission_status = get_user_submission_status(user.id, module.id, db)

            # Build list of selected modules for switcher
            selected_modules = []
            for sel in user_selections:
                mod = db.query(Module).filter(Module.id == sel.module_id).first()
                if mod:
                    mod_status = get_user_submission_status(user.id, mod.id, db)
                    selected_modules.append({
                        "module": mod,
                        "selection": sel,
                        "is_active": sel.is_active,
                        "homework_submitted": mod_status["homework"]["submitted"],
                    })

            return templates.TemplateResponse(
                "dashboard.html",
                {
                    "request": request,
                    "user": user,
                    "module": module,
                    "pdf_updated": pdf_updated,
                    "submission_status": submission_status,
                    "selected_modules": selected_modules,
                    "can_select_more": len(user_selections) < 2 and user.role == UserRole.reviewer,
                },
            )

    # No module selected - show module selection
    # Get modules visible to user based on role
    if user.role == UserRole.admin:
        # Admins see all modules
        modules = db.query(Module).order_by(Module.course_id, Module.week_number).all()
    elif user.role == UserRole.student:
        # Students see active modules
        modules = (
            db.query(Module)
            .filter(Module.visibility == ModuleVisibility.active)
            .order_by(Module.course_id, Module.week_number)
            .all()
        )
    else:
        # Reviewers only see pilot_review modules (available for review)
        modules = (
            db.query(Module)
            .filter(Module.visibility == ModuleVisibility.pilot_review)
            .order_by(Module.course_id, Module.week_number)
            .all()
        )

    # Get reviewer counts for each module (using new selection table)
    module_stats = {}
    for module in modules:
        reviewer_count = (
            db.query(func.count(UserModuleSelection.id))
            .join(User)
            .filter(
                UserModuleSelection.module_id == module.id,
                User.role == UserRole.reviewer,
            )
            .scalar()
        )
        student_count = (
            db.query(func.count(UserModuleSelection.id))
            .join(User)
            .filter(
                UserModuleSelection.module_id == module.id,
                User.role == UserRole.student,
            )
            .scalar()
        )
        module_stats[module.id] = {
            "reviewer_count": reviewer_count,
            "student_count": student_count,
        }

    # Group modules by course
    courses_with_modules = {}
    modules_without_course = []
    for module in modules:
        if module.course_id:
            if module.course_id not in courses_with_modules:
                course = db.query(Course).filter(Course.id == module.course_id).first()
                courses_with_modules[module.course_id] = {
                    "course": course,
                    "modules": []
                }
            courses_with_modules[module.course_id]["modules"].append(module)
        else:
            modules_without_course.append(module)

    # Get user's current selections for the template
    user_selections = (
        db.query(UserModuleSelection)
        .filter(UserModuleSelection.user_id == user.id)
        .all()
    )
    selected_module_ids = [s.module_id for s in user_selections]

    # Build selection info with homework status
    user_selection_info = []
    for sel in user_selections:
        mod = db.query(Module).filter(Module.id == sel.module_id).first()
        if mod:
            hw_submitted = db.query(Submission).filter(
                Submission.user_id == user.id,
                Submission.module_id == mod.id,
                Submission.submission_type == "homework"
            ).first() is not None
            user_selection_info.append({
                "module": mod,
                "homework_submitted": hw_submitted,
            })

    return templates.TemplateResponse(
        "module_select.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "module_stats": module_stats,
            "courses_with_modules": list(courses_with_modules.values()),
            "modules_without_course": modules_without_course,
            "selected_module_ids": selected_module_ids,
            "user_selection_info": user_selection_info,
            "max_modules": 2 if user.role == UserRole.reviewer else 1,
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


@router.get("/confidentiality", response_class=HTMLResponse)
async def confidentiality_agreement(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Display confidentiality agreement for first-time reviewers."""
    # If already accepted, redirect to dashboard
    if user.accepted_terms_at:
        return RedirectResponse(url="/dashboard", status_code=303)

    # Admins don't need to accept
    if user.role == UserRole.admin:
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(
        "confidentiality.html",
        {"request": request, "user": user},
    )


@router.post("/accept-terms")
async def accept_terms(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Accept the confidentiality agreement."""
    form = await request.form()

    if form.get("agree") != "on":
        return RedirectResponse(url="/confidentiality?error=must_agree", status_code=303)

    user.accepted_terms_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url="/home", status_code=303)


@router.get("/help/reviewer", response_class=HTMLResponse)
async def reviewer_help(
    request: Request,
    user: User = Depends(require_user),
):
    """Display reviewer help page."""
    return templates.TemplateResponse(
        "help/reviewer.html",
        {"request": request, "user": user},
    )


@router.get("/help/student", response_class=HTMLResponse)
async def student_help(
    request: Request,
    user: User = Depends(require_user),
):
    """Display student help page."""
    return templates.TemplateResponse(
        "help/student.html",
        {"request": request, "user": user},
    )
