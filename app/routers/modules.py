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
from app.models import Module, ModuleVisibility, Submission, User, UserRole, UserModuleSelection
from app.slack import notify_slack_new_reviewer

router = APIRouter(prefix="/modules", tags=["modules"])
templates = Jinja2Templates(directory="templates")


# Import Request for form handling
from fastapi import Form


def can_user_view_module(user: User, module: Module) -> bool:
    """Check if a user can view a module based on visibility and role."""
    if user.role == UserRole.admin:
        return True
    if module.visibility == ModuleVisibility.archived:
        return False
    if module.visibility == ModuleVisibility.draft:
        return False
    if module.visibility == ModuleVisibility.active:
        return True
    if module.visibility == ModuleVisibility.pilot_review:
        return user.role == UserRole.reviewer
    return False


@router.get("", response_class=HTMLResponse)
async def list_modules(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List all modules visible to the current user."""
    if user.role == UserRole.admin:
        modules = db.query(Module).order_by(Module.week_number).all()
    elif user.role == UserRole.student:
        modules = (
            db.query(Module)
            .filter(Module.visibility == ModuleVisibility.active)
            .order_by(Module.week_number)
            .all()
        )
    else:
        # Reviewers only see pilot_review modules
        modules = (
            db.query(Module)
            .filter(Module.visibility == ModuleVisibility.pilot_review)
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
                User.role == UserRole.reviewer,
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
            User.role == UserRole.reviewer,
        )
        .scalar()
    )
    student_count = (
        db.query(func.count(User.id))
        .filter(
            User.selected_module_id == module.id,
            User.role == UserRole.student,
        )
        .scalar()
    )

    # Check if user already selected this module
    is_selected = user.selected_module_id == module.id

    # Check capacity
    if user.role == UserRole.reviewer:
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
    """Select a module to review/study (max 2 for reviewers)."""
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if not can_user_view_module(user, module):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if already selected this module
    existing_selection = (
        db.query(UserModuleSelection)
        .filter(
            UserModuleSelection.user_id == user.id,
            UserModuleSelection.module_id == module_id,
        )
        .first()
    )
    if existing_selection:
        raise HTTPException(
            status_code=400,
            detail="You have already selected this module.",
        )

    # Check how many modules user has selected (max 2 for reviewers)
    current_selections = (
        db.query(UserModuleSelection)
        .filter(UserModuleSelection.user_id == user.id)
        .count()
    )
    max_modules = 2 if user.role == UserRole.reviewer else 1
    if current_selections >= max_modules:
        raise HTTPException(
            status_code=400,
            detail=f"You can select up to {max_modules} module(s). Please release one first.",
        )

    # Check capacity
    if user.role == UserRole.reviewer:
        reviewer_count = (
            db.query(func.count(UserModuleSelection.id))
            .join(User)
            .filter(
                UserModuleSelection.module_id == module.id,
                User.role == UserRole.reviewer,
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
            db.query(func.count(UserModuleSelection.id))
            .join(User)
            .filter(
                UserModuleSelection.module_id == module.id,
                User.role == UserRole.student,
            )
            .scalar()
        )
        if module.max_students and student_count >= module.max_students:
            raise HTTPException(
                status_code=400,
                detail="This module has reached maximum student capacity.",
            )

    # Deactivate other selections, make this one active
    db.query(UserModuleSelection).filter(
        UserModuleSelection.user_id == user.id
    ).update({UserModuleSelection.is_active: False})

    # Create new selection
    selection = UserModuleSelection(
        user_id=user.id,
        module_id=module.id,
        selected_at=datetime.utcnow(),
        last_notified_version=module.drive_modified_time,
        is_active=True,
    )
    db.add(selection)

    # Also update legacy field for backwards compatibility
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
    """Release a selected module (only after submitting homework feedback)."""
    # Check if user has this module selected
    selection = (
        db.query(UserModuleSelection)
        .filter(
            UserModuleSelection.user_id == user.id,
            UserModuleSelection.module_id == module_id,
        )
        .first()
    )

    if not selection:
        raise HTTPException(status_code=400, detail="Module not selected")

    # Check for homework submission (required before release)
    homework_submission = (
        db.query(Submission)
        .filter(
            Submission.user_id == user.id,
            Submission.module_id == module_id,
            Submission.submission_type == "homework",
        )
        .first()
    )

    if not homework_submission:
        raise HTTPException(
            status_code=400,
            detail="Please submit your homework feedback before releasing the module.",
        )

    # Delete the selection
    db.delete(selection)

    # Update legacy field - set to another active module or None
    remaining = (
        db.query(UserModuleSelection)
        .filter(UserModuleSelection.user_id == user.id)
        .first()
    )
    if remaining:
        remaining.is_active = True
        user.selected_module_id = remaining.module_id
    else:
        user.selected_module_id = None
        user.selected_at = None

    db.commit()

    return RedirectResponse(url="/home?released=1", status_code=303)


@router.post("/{module_id}/switch")
async def switch_to_module(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Switch active view to a different selected module."""
    # Check if user has this module selected
    selection = (
        db.query(UserModuleSelection)
        .filter(
            UserModuleSelection.user_id == user.id,
            UserModuleSelection.module_id == module_id,
        )
        .first()
    )

    if not selection:
        raise HTTPException(status_code=400, detail="Module not selected")

    # Deactivate all, activate this one
    db.query(UserModuleSelection).filter(
        UserModuleSelection.user_id == user.id
    ).update({UserModuleSelection.is_active: False})

    selection.is_active = True

    # Update legacy field
    user.selected_module_id = module_id
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/{module_id}/swap", response_class=HTMLResponse)
async def swap_module_page(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Show page to choose which module to release when swapping."""
    # Get the new module user wants to switch to
    new_module = db.query(Module).filter(Module.id == module_id).first()
    if not new_module:
        raise HTTPException(status_code=404, detail="Module not found")

    if not can_user_view_module(user, new_module):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check capacity
    reviewer_count = (
        db.query(func.count(UserModuleSelection.id))
        .join(User)
        .filter(
            UserModuleSelection.module_id == module_id,
            User.role == UserRole.reviewer,
        )
        .scalar()
    )
    if new_module.max_reviewers and reviewer_count >= new_module.max_reviewers:
        raise HTTPException(status_code=400, detail="This module is full")

    # Get user's current selections
    user_selections = (
        db.query(UserModuleSelection)
        .filter(UserModuleSelection.user_id == user.id)
        .all()
    )

    if not user_selections:
        # No modules selected, just redirect to select
        return RedirectResponse(url=f"/modules/{module_id}", status_code=303)

    # Check if already selected this module
    if any(s.module_id == module_id for s in user_selections):
        return RedirectResponse(url="/dashboard", status_code=303)

    # Build info about current modules
    current_modules = []
    for sel in user_selections:
        mod = db.query(Module).filter(Module.id == sel.module_id).first()
        if mod:
            hw_submitted = db.query(Submission).filter(
                Submission.user_id == user.id,
                Submission.module_id == mod.id,
                Submission.submission_type == "homework"
            ).first() is not None
            current_modules.append({
                "module": mod,
                "homework_submitted": hw_submitted,
                "can_release": hw_submitted,
            })

    return templates.TemplateResponse(
        "module_swap.html",
        {
            "request": request,
            "user": user,
            "new_module": new_module,
            "current_modules": current_modules,
        },
    )


@router.post("/{module_id}/swap")
async def swap_module(
    module_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Swap a current module for a new one."""
    form = await request.form()
    release_module_id = int(form.get("release_module_id"))

    # Get the new module
    new_module = db.query(Module).filter(Module.id == module_id).first()
    if not new_module:
        raise HTTPException(status_code=404, detail="Module not found")

    if not can_user_view_module(user, new_module):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if user has the module to release
    release_selection = (
        db.query(UserModuleSelection)
        .filter(
            UserModuleSelection.user_id == user.id,
            UserModuleSelection.module_id == release_module_id,
        )
        .first()
    )

    if not release_selection:
        raise HTTPException(status_code=400, detail="Module to release not found")

    # Check homework submitted for the module being released
    homework_submission = (
        db.query(Submission)
        .filter(
            Submission.user_id == user.id,
            Submission.module_id == release_module_id,
            Submission.submission_type == "homework",
        )
        .first()
    )

    if not homework_submission:
        raise HTTPException(
            status_code=400,
            detail="Please submit homework feedback for the module you want to release.",
        )

    # Check capacity of new module
    reviewer_count = (
        db.query(func.count(UserModuleSelection.id))
        .join(User)
        .filter(
            UserModuleSelection.module_id == module_id,
            User.role == UserRole.reviewer,
        )
        .scalar()
    )
    if new_module.max_reviewers and reviewer_count >= new_module.max_reviewers:
        raise HTTPException(status_code=400, detail="This module is now full")

    # Delete the old selection
    db.delete(release_selection)

    # Deactivate other selections
    db.query(UserModuleSelection).filter(
        UserModuleSelection.user_id == user.id
    ).update({UserModuleSelection.is_active: False})

    # Create new selection
    new_selection = UserModuleSelection(
        user_id=user.id,
        module_id=module_id,
        selected_at=datetime.utcnow(),
        last_notified_version=new_module.drive_modified_time,
        is_active=True,
    )
    db.add(new_selection)

    # Update legacy field
    user.selected_module_id = module_id
    db.commit()

    # Notify via Slack
    await notify_slack_new_reviewer(
        reviewer_name=user.name or user.email,
        reviewer_email=user.email,
        module_name=new_module.name,
    )

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
    if user.role != UserRole.admin and user.selected_module_id != module_id:
        raise HTTPException(status_code=403, detail="You must select this module first")

    # Check if drive_file_id is valid
    if not module.drive_file_id or module.drive_file_id == "PLACEHOLDER":
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "user": user,
                "error_title": "PDF Not Available",
                "error_message": "The PDF for this module hasn't been uploaded yet. Please check back later or contact the administrator.",
            },
            status_code=404,
        )

    try:
        metadata = get_file_metadata(module.drive_file_id)
        filename = metadata.get("name", f"module_{module_id}.pdf")

        return StreamingResponse(
            stream_file(module.drive_file_id),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "user": user,
                "error_title": "PDF Not Found",
                "error_message": "The PDF file could not be retrieved from Google Drive. It may have been moved or deleted. Please contact the administrator.",
            },
            status_code=404,
        )


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

    if user.role != UserRole.admin and user.selected_module_id != module_id:
        raise HTTPException(status_code=403, detail="You must select this module first")

    # Check if drive_file_id is valid
    if not module.drive_file_id or module.drive_file_id == "PLACEHOLDER":
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "user": user,
                "error_title": "PDF Not Available",
                "error_message": "The PDF for this module hasn't been uploaded yet. Please check back later or contact the administrator.",
            },
            status_code=404,
        )

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
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "user": user,
                "error_title": "PDF Not Found",
                "error_message": "The PDF file could not be retrieved from Google Drive. It may have been moved or deleted. Please contact the administrator.",
            },
            status_code=404,
        )
