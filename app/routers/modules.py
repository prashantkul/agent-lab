"""Module routes for viewing and selecting modules."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_user
from app.drive import get_file_metadata, stream_file
from app.models import Module, ModuleVisibility, Submission, User, UserRole
from app.slack import notify_slack_new_reviewer

router = APIRouter(prefix="/modules", tags=["modules"])
templates = Jinja2Templates(directory="templates")


def can_user_view_module(user: User, module: Module) -> bool:
    """Check if a user can view a module based on visibility and role."""
    if user.role == UserRole.ADMIN:
        return True
    if module.visibility == ModuleVisibility.ARCHIVED:
        return False
    if module.visibility == ModuleVisibility.DRAFT:
        return False
    if module.visibility == ModuleVisibility.ACTIVE:
        return True
    if module.visibility == ModuleVisibility.PILOT_REVIEW:
        return user.role == UserRole.REVIEWER
    return False


@router.get("", response_class=HTMLResponse)
async def list_modules(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List all modules visible to the current user."""
    if user.role == UserRole.ADMIN:
        modules = db.query(Module).order_by(Module.week_number).all()
    elif user.role == UserRole.STUDENT:
        modules = (
            db.query(Module)
            .filter(Module.visibility == ModuleVisibility.ACTIVE)
            .order_by(Module.week_number)
            .all()
        )
    else:
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

    # Get counts
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
        module_stats[module.id] = {"reviewer_count": reviewer_count}

    return templates.TemplateResponse(
        "module_select.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "module_stats": module_stats,
        },
    )


@router.get("/{module_id}", response_class=HTMLResponse)
async def module_details(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """View detailed module information."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if not can_user_view_module(user, module):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get counts
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

    # Check if user already selected this module
    is_selected = user.selected_module_id == module.id

    # Check capacity
    if user.role == UserRole.REVIEWER:
        at_capacity = module.max_reviewers and reviewer_count >= module.max_reviewers
    else:
        at_capacity = module.max_students and student_count >= module.max_students

    return templates.TemplateResponse(
        "module_details.html",
        {
            "request": request,
            "user": user,
            "module": module,
            "reviewer_count": reviewer_count,
            "student_count": student_count,
            "is_selected": is_selected,
            "at_capacity": at_capacity,
        },
    )


@router.post("/{module_id}/select")
async def select_module(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Select a module to review/study."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if not can_user_view_module(user, module):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if already has a module selected
    if user.selected_module_id:
        raise HTTPException(
            status_code=400,
            detail="You already have a module selected. Release it first.",
        )

    # Check capacity
    if user.role == UserRole.REVIEWER:
        reviewer_count = (
            db.query(func.count(User.id))
            .filter(
                User.selected_module_id == module.id,
                User.role == UserRole.REVIEWER,
            )
            .scalar()
        )
        if module.max_reviewers and reviewer_count >= module.max_reviewers:
            raise HTTPException(
                status_code=400,
                detail="This module has reached maximum reviewer capacity.",
            )
    else:
        student_count = (
            db.query(func.count(User.id))
            .filter(
                User.selected_module_id == module.id,
                User.role == UserRole.STUDENT,
            )
            .scalar()
        )
        if module.max_students and student_count >= module.max_students:
            raise HTTPException(
                status_code=400,
                detail="This module has reached maximum student capacity.",
            )

    # Select the module
    user.selected_module_id = module.id
    user.selected_at = datetime.utcnow()
    user.last_notified_version = module.drive_modified_time
    db.commit()

    # Notify via Slack
    await notify_slack_new_reviewer(
        reviewer_name=user.name or user.email,
        reviewer_email=user.email,
        module_name=module.name,
    )

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/{module_id}/release")
async def release_module(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Release a selected module (only if no submissions yet)."""
    if user.selected_module_id != module_id:
        raise HTTPException(status_code=400, detail="Module not selected")

    # Check for submissions
    submissions = (
        db.query(Submission)
        .filter(
            Submission.user_id == user.id,
            Submission.module_id == module_id,
        )
        .count()
    )

    if submissions > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot release module after making submissions.",
        )

    user.selected_module_id = None
    user.selected_at = None
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/{module_id}/pdf")
async def get_module_pdf(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Stream PDF from Google Drive."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    # Verify user has selected this module or is admin
    if user.role != UserRole.ADMIN and user.selected_module_id != module_id:
        raise HTTPException(status_code=403, detail="You must select this module first")

    try:
        metadata = get_file_metadata(module.drive_file_id)
        filename = metadata.get("name", f"module_{module_id}.pdf")

        return StreamingResponse(
            stream_file(module.drive_file_id),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve PDF: {str(e)}")


@router.get("/{module_id}/pdf/download")
async def download_module_pdf(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Download PDF from Google Drive."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if user.role != UserRole.ADMIN and user.selected_module_id != module_id:
        raise HTTPException(status_code=403, detail="You must select this module first")

    try:
        metadata = get_file_metadata(module.drive_file_id)
        filename = metadata.get("name", f"module_{module_id}.pdf")

        # Update user's last notified version when they download
        user.last_notified_version = module.drive_modified_time
        db.commit()

        return StreamingResponse(
            stream_file(module.drive_file_id),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download PDF: {str(e)}")
