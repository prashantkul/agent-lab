"""Admin routes for managing modules, users, and submissions."""
import csv
import io
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_admin
from app.drive import get_file_metadata
from app.grading import run_auto_grader, apply_manual_grade
from app.models import Grade, Module, ModuleVisibility, Notification, Submission, User, UserRole
from app.notifications import send_pdf_update_notification
from app.reminders import send_weekly_reminders
from app.slack import notify_slack_pdf_updated

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Admin dashboard with stats overview."""
    # Get counts
    total_users = db.query(func.count(User.id)).scalar()
    reviewer_count = (
        db.query(func.count(User.id)).filter(User.role == UserRole.REVIEWER).scalar()
    )
    student_count = (
        db.query(func.count(User.id)).filter(User.role == UserRole.STUDENT).scalar()
    )
    admin_count = (
        db.query(func.count(User.id)).filter(User.role == UserRole.ADMIN).scalar()
    )

    total_modules = db.query(func.count(Module.id)).scalar()
    active_modules = (
        db.query(func.count(Module.id))
        .filter(Module.visibility == ModuleVisibility.ACTIVE)
        .scalar()
    )

    total_submissions = db.query(func.count(Submission.id)).scalar()
    graded_submissions = (
        db.query(func.count(Grade.id)).filter(Grade.status == "completed").scalar()
    )

    # Recent submissions
    recent_submissions = (
        db.query(Submission)
        .order_by(Submission.submitted_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "user": user,
            "total_users": total_users,
            "reviewer_count": reviewer_count,
            "student_count": student_count,
            "admin_count": admin_count,
            "total_modules": total_modules,
            "active_modules": active_modules,
            "total_submissions": total_submissions,
            "graded_submissions": graded_submissions,
            "recent_submissions": recent_submissions,
        },
    )


# ==================== Module Management ====================


@router.get("/modules", response_class=HTMLResponse)
async def list_modules(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """List all modules for admin management."""
    modules = db.query(Module).order_by(Module.week_number).all()

    # Get counts for each module
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
        submission_count = (
            db.query(func.count(Submission.id))
            .filter(Submission.module_id == module.id)
            .scalar()
        )
        module_stats[module.id] = {
            "reviewer_count": reviewer_count,
            "student_count": student_count,
            "submission_count": submission_count,
        }

    return templates.TemplateResponse(
        "admin/modules.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "module_stats": module_stats,
        },
    )


@router.get("/modules/new", response_class=HTMLResponse)
async def new_module_form(
    request: Request,
    user: User = Depends(require_admin),
):
    """Show form to create a new module."""
    return templates.TemplateResponse(
        "admin/module_edit.html",
        {
            "request": request,
            "user": user,
            "module": None,
            "is_new": True,
        },
    )


@router.post("/modules")
async def create_module(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Create a new module."""
    form = await request.form()

    # Parse learning objectives and prerequisites
    objectives_raw = form.get("learning_objectives", "")
    objectives = [o.strip() for o in objectives_raw.split("\n") if o.strip()]

    prereqs_raw = form.get("prerequisites", "")
    prerequisites = [p.strip() for p in prereqs_raw.split("\n") if p.strip()]

    module = Module(
        name=form.get("name"),
        week_number=int(form.get("week_number", 1)),
        visibility=ModuleVisibility(form.get("visibility", "draft")),
        short_description=form.get("short_description"),
        detailed_description=form.get("detailed_description"),
        learning_objectives=objectives if objectives else None,
        prerequisites=prerequisites if prerequisites else None,
        expected_outcomes=form.get("expected_outcomes"),
        estimated_time_minutes=int(form.get("estimated_time_minutes", 0)) or None,
        drive_file_id=form.get("drive_file_id"),
        starter_repo_url=form.get("starter_repo_url"),
        instructions=form.get("instructions"),
        homework_instructions=form.get("homework_instructions"),
        grading_enabled=form.get("grading_enabled") == "on",
        grading_script_url=form.get("grading_script_url"),
        grading_criteria=form.get("grading_criteria"),
        max_points=int(form.get("max_points", 100)),
        max_reviewers=int(form.get("max_reviewers", 10)),
        max_students=int(form.get("max_students")) if form.get("max_students") else None,
    )

    db.add(module)
    db.commit()

    return RedirectResponse(url="/admin/modules", status_code=303)


@router.get("/modules/{module_id}/edit", response_class=HTMLResponse)
async def edit_module_form(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Show form to edit a module."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    return templates.TemplateResponse(
        "admin/module_edit.html",
        {
            "request": request,
            "user": user,
            "module": module,
            "is_new": False,
        },
    )


@router.post("/modules/{module_id}")
async def update_module(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Update an existing module."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    form = await request.form()

    # Parse learning objectives and prerequisites
    objectives_raw = form.get("learning_objectives", "")
    objectives = [o.strip() for o in objectives_raw.split("\n") if o.strip()]

    prereqs_raw = form.get("prerequisites", "")
    prerequisites = [p.strip() for p in prereqs_raw.split("\n") if p.strip()]

    module.name = form.get("name")
    module.week_number = int(form.get("week_number", 1))
    module.visibility = ModuleVisibility(form.get("visibility", "draft"))
    module.short_description = form.get("short_description")
    module.detailed_description = form.get("detailed_description")
    module.learning_objectives = objectives if objectives else None
    module.prerequisites = prerequisites if prerequisites else None
    module.expected_outcomes = form.get("expected_outcomes")
    module.estimated_time_minutes = int(form.get("estimated_time_minutes", 0)) or None
    module.drive_file_id = form.get("drive_file_id")
    module.starter_repo_url = form.get("starter_repo_url")
    module.instructions = form.get("instructions")
    module.homework_instructions = form.get("homework_instructions")
    module.grading_enabled = form.get("grading_enabled") == "on"
    module.grading_script_url = form.get("grading_script_url")
    module.grading_criteria = form.get("grading_criteria")
    module.max_points = int(form.get("max_points", 100))
    module.max_reviewers = int(form.get("max_reviewers", 10))
    module.max_students = int(form.get("max_students")) if form.get("max_students") else None
    module.updated_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(url="/admin/modules", status_code=303)


@router.post("/modules/{module_id}/visibility")
async def change_visibility(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Change module visibility."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    form = await request.form()
    new_visibility = form.get("visibility")

    if new_visibility not in [v.value for v in ModuleVisibility]:
        raise HTTPException(status_code=400, detail="Invalid visibility")

    module.visibility = ModuleVisibility(new_visibility)
    module.updated_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url="/admin/modules", status_code=303)


@router.post("/modules/{module_id}/check-update")
async def check_module_update(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Check Drive for PDF updates and notify users."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    try:
        metadata = get_file_metadata(module.drive_file_id)
        new_modified_time = metadata.get("modifiedTime")

        if module.drive_modified_time != new_modified_time:
            # PDF was updated
            module.drive_modified_time = new_modified_time
            module.updated_at = datetime.utcnow()

            # Find users to notify
            users = (
                db.query(User)
                .filter(
                    User.selected_module_id == module_id,
                    User.last_notified_version != new_modified_time,
                )
                .all()
            )

            for u in users:
                send_pdf_update_notification(
                    to_email=u.email,
                    user_name=u.name or u.email,
                    module_name=module.name,
                )
                u.last_notified_version = new_modified_time

            db.commit()

            await notify_slack_pdf_updated(module.name, len(users))

            return RedirectResponse(
                url=f"/admin/modules?updated={module_id}&notified={len(users)}",
                status_code=303,
            )

        return RedirectResponse(
            url=f"/admin/modules?no_update={module_id}", status_code=303
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check update: {str(e)}")


@router.delete("/modules/{module_id}")
async def delete_module(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Soft delete a module (set to archived)."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    module.visibility = ModuleVisibility.ARCHIVED
    module.updated_at = datetime.utcnow()
    db.commit()

    return {"status": "archived"}


# ==================== User Management ====================


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """List all users."""
    users = db.query(User).order_by(User.created_at.desc()).all()

    # Get submission counts
    user_stats = {}
    for u in users:
        submission_count = (
            db.query(func.count(Submission.id))
            .filter(Submission.user_id == u.id)
            .scalar()
        )
        user_stats[u.id] = {"submission_count": submission_count}

    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "user_stats": user_stats,
        },
    )


@router.post("/users/{user_id}/role")
async def change_user_role(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Change a user's role."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    form = await request.form()
    new_role = form.get("role")

    if new_role not in [r.value for r in UserRole]:
        raise HTTPException(status_code=400, detail="Invalid role")

    target_user.role = UserRole(new_role)
    db.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


# ==================== Submission Management ====================


@router.get("/submissions", response_class=HTMLResponse)
async def list_submissions(
    request: Request,
    module_id: int = None,
    submission_type: str = None,
    status: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """List all submissions with filters."""
    query = db.query(Submission)

    if module_id:
        query = query.filter(Submission.module_id == module_id)
    if submission_type:
        query = query.filter(Submission.submission_type == submission_type)

    submissions = query.order_by(Submission.submitted_at.desc()).all()

    # Filter by grade status if specified
    if status:
        filtered = []
        for sub in submissions:
            grade = db.query(Grade).filter(Grade.submission_id == sub.id).first()
            if status == "pending" and (not grade or grade.status == "pending"):
                filtered.append(sub)
            elif status == "completed" and grade and grade.status == "completed":
                filtered.append(sub)
            elif status == "failed" and grade and grade.status == "failed":
                filtered.append(sub)
        submissions = filtered

    # Get grades for submissions
    grades_by_submission = {}
    for sub in submissions:
        grade = db.query(Grade).filter(Grade.submission_id == sub.id).first()
        grades_by_submission[sub.id] = grade

    modules = db.query(Module).order_by(Module.week_number).all()

    return templates.TemplateResponse(
        "admin/submissions.html",
        {
            "request": request,
            "user": user,
            "submissions": submissions,
            "grades": grades_by_submission,
            "modules": modules,
            "filter_module_id": module_id,
            "filter_type": submission_type,
            "filter_status": status,
        },
    )


@router.post("/submissions/{submission_id}/grade")
async def grade_submission(
    submission_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Run auto-grader for a specific submission."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    background_tasks.add_task(run_auto_grader_background, submission_id)

    return RedirectResponse(url="/admin/submissions?grading=1", status_code=303)


async def run_auto_grader_background(submission_id: int):
    """Background task for auto-grading."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await run_auto_grader(submission_id, db)
    except Exception as e:
        print(f"Auto-grading failed: {e}")
    finally:
        db.close()


@router.post("/submissions/{submission_id}/manual-grade")
async def manual_grade_submission(
    submission_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Add or override grade with manual grading."""
    form = await request.form()

    total_points = Decimal(form.get("total_points", "0"))
    manual_feedback = form.get("manual_feedback")

    strengths_raw = form.get("strengths", "")
    strengths = [s.strip() for s in strengths_raw.split("\n") if s.strip()]

    improvements_raw = form.get("improvements", "")
    improvements = [i.strip() for i in improvements_raw.split("\n") if i.strip()]

    apply_manual_grade(
        submission_id=submission_id,
        total_points=total_points,
        manual_feedback=manual_feedback,
        strengths=strengths if strengths else None,
        improvements=improvements if improvements else None,
        graded_by=admin.email,
        db=db,
    )

    return RedirectResponse(url="/admin/submissions", status_code=303)


@router.post("/modules/{module_id}/grade-all")
async def grade_all_module_submissions(
    module_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Batch grade all pending submissions for a module."""
    # Find all submissions without completed grades
    submissions = (
        db.query(Submission)
        .filter(Submission.module_id == module_id)
        .all()
    )

    pending_ids = []
    for sub in submissions:
        grade = db.query(Grade).filter(Grade.submission_id == sub.id).first()
        if not grade or grade.status != "completed":
            pending_ids.append(sub.id)

    for sub_id in pending_ids:
        background_tasks.add_task(run_auto_grader_background, sub_id)

    return RedirectResponse(
        url=f"/admin/submissions?module_id={module_id}&batch_grading={len(pending_ids)}",
        status_code=303,
    )


@router.get("/submissions/export")
async def export_submissions(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Export all submissions and grades as CSV."""
    submissions = db.query(Submission).order_by(Submission.submitted_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Submission ID",
        "User Email",
        "User Name",
        "Module",
        "Type",
        "GitHub Link",
        "Clarity Rating",
        "Difficulty Rating",
        "Time Spent (min)",
        "Submitted At",
        "Grade Status",
        "Total Points",
        "Max Points",
        "Percentage",
        "Letter Grade",
        "Graded By",
        "Comments",
    ])

    for sub in submissions:
        grade = db.query(Grade).filter(Grade.submission_id == sub.id).first()

        writer.writerow([
            sub.id,
            sub.user.email,
            sub.user.name,
            sub.module.name,
            sub.submission_type,
            sub.github_link,
            sub.clarity_rating,
            sub.difficulty_rating,
            sub.time_spent_minutes,
            sub.submitted_at.isoformat() if sub.submitted_at else "",
            grade.status if grade else "not_graded",
            float(grade.total_points) if grade and grade.total_points else "",
            grade.max_points if grade else "",
            float(grade.percentage) if grade and grade.percentage else "",
            grade.letter_grade if grade else "",
            grade.graded_by if grade else "",
            sub.comments[:100] + "..." if len(sub.comments) > 100 else sub.comments,
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=submissions_export.csv"},
    )


# ==================== Reminder Management ====================


@router.post("/reminders/send-now")
async def send_reminders_now(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Manually trigger reminder emails."""
    count = await send_weekly_reminders(db)
    return RedirectResponse(url=f"/admin?reminders_sent={count}", status_code=303)
