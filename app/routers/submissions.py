"""Submission routes for in-class and homework assignments."""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_user
from app.grading import run_auto_grader
from app.models import Module, Submission, User
from app.notifications import send_submission_notification
from app.slack import notify_slack_new_submission

router = APIRouter(tags=["submissions"])
templates = Jinja2Templates(directory="templates")


def validate_github_url(url: str) -> bool:
    """Validate GitHub repository URL."""
    pattern = r"^https://github\.com/[\w-]+/[\w.-]+/?$"
    return bool(re.match(pattern, url))


@router.get("/submit/{submission_type}", response_class=HTMLResponse)
async def submission_form(
    submission_type: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Show submission form."""
    if submission_type not in ["in_class", "homework"]:
        raise HTTPException(status_code=400, detail="Invalid submission type")

    if not user.selected_module_id:
        return RedirectResponse(url="/dashboard", status_code=303)

    module = db.query(Module).filter(Module.id == user.selected_module_id).first()
    if not module:
        return RedirectResponse(url="/dashboard", status_code=303)

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

    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "user": user,
            "module": module,
            "submission_type": submission_type,
            "existing": existing,
        },
    )


@router.post("/submit/{submission_type}")
async def submit_assignment(
    submission_type: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Submit an assignment."""
    if submission_type not in ["in_class", "homework"]:
        raise HTTPException(status_code=400, detail="Invalid submission type")

    if not user.selected_module_id:
        raise HTTPException(status_code=400, detail="No module selected")

    module = db.query(Module).filter(Module.id == user.selected_module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    # Parse form data
    form = await request.form()
    github_link = form.get("github_link", "").strip()
    comments = form.get("comments", "").strip()

    # Parse optional ratings
    clarity_rating = form.get("clarity_rating")
    difficulty_rating = form.get("difficulty_rating")
    time_spent = form.get("time_spent_minutes")

    clarity_rating = int(clarity_rating) if clarity_rating else None
    difficulty_rating = int(difficulty_rating) if difficulty_rating else None
    time_spent = int(time_spent) if time_spent else None

    # Validate
    if not github_link:
        raise HTTPException(status_code=400, detail="GitHub link is required")
    if not validate_github_url(github_link):
        raise HTTPException(status_code=400, detail="Invalid GitHub repository URL")
    if not comments:
        raise HTTPException(status_code=400, detail="Comments are required")

    # Validate ratings if provided
    if clarity_rating is not None and (clarity_rating < 1 or clarity_rating > 5):
        raise HTTPException(status_code=400, detail="Clarity rating must be 1-5")
    if difficulty_rating is not None and (difficulty_rating < 1 or difficulty_rating > 5):
        raise HTTPException(status_code=400, detail="Difficulty rating must be 1-5")

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
        # Update existing submission
        existing.github_link = github_link.rstrip("/")
        existing.comments = comments
        existing.clarity_rating = clarity_rating
        existing.difficulty_rating = difficulty_rating
        existing.time_spent_minutes = time_spent
        existing.submitted_at = datetime.utcnow()
        submission = existing
    else:
        # Create new submission
        submission = Submission(
            user_id=user.id,
            module_id=module.id,
            submission_type=submission_type,
            github_link=github_link.rstrip("/"),
            comments=comments,
            clarity_rating=clarity_rating,
            difficulty_rating=difficulty_rating,
            time_spent_minutes=time_spent,
        )
        db.add(submission)

    db.commit()
    db.refresh(submission)

    # Send notifications
    send_submission_notification(
        reviewer_name=user.name or user.email,
        reviewer_email=user.email,
        module_name=module.name,
        submission_type=submission_type,
        github_link=submission.github_link,
        comments=comments,
        clarity_rating=clarity_rating,
        difficulty_rating=difficulty_rating,
        time_spent=time_spent,
    )

    await notify_slack_new_submission(
        reviewer_name=user.name or user.email,
        reviewer_email=user.email,
        module_name=module.name,
        submission_type=submission_type,
        github_link=submission.github_link,
        clarity_rating=clarity_rating,
        difficulty_rating=difficulty_rating,
        time_spent=time_spent,
        comments=comments,
    )

    # Trigger auto-grading if enabled
    if module.grading_enabled:
        background_tasks.add_task(run_auto_grader_task, submission.id, db)

    return RedirectResponse(url="/dashboard?submitted=1", status_code=303)


async def run_auto_grader_task(submission_id: int, db: Session):
    """Background task to run auto-grader."""
    try:
        await run_auto_grader(submission_id, db)
    except Exception as e:
        print(f"Auto-grading failed for submission {submission_id}: {e}")


@router.get("/my-submissions", response_class=HTMLResponse)
async def my_submissions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """View all user's submissions."""
    submissions = (
        db.query(Submission)
        .filter(Submission.user_id == user.id)
        .order_by(Submission.submitted_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "my_submissions.html",
        {
            "request": request,
            "user": user,
            "submissions": submissions,
        },
    )
