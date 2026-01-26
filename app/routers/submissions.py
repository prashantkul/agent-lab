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
    comments = form.get("comments", "").strip()

    # Parse scale-based feedback (1-10 ratings)
    q_objectives = form.get("q_objectives")
    q_content = form.get("q_content")
    q_starter_code = form.get("q_starter_code")
    q_difficulty = form.get("q_difficulty")
    q_overall = form.get("q_overall")
    time_spent = form.get("time_spent_minutes")

    # Validate required ratings
    if not q_objectives:
        raise HTTPException(status_code=400, detail="Please rate the learning objectives clarity")
    if not q_content:
        raise HTTPException(status_code=400, detail="Please rate the PDF materials quality")
    if not q_starter_code:
        raise HTTPException(status_code=400, detail="Please rate the starter code quality")
    if not q_difficulty:
        raise HTTPException(status_code=400, detail="Please rate the difficulty level")
    if not q_overall:
        raise HTTPException(status_code=400, detail="Please provide an overall rating")
    if not time_spent:
        raise HTTPException(status_code=400, detail="Please enter the time spent")

    # Convert to integers and validate range (1-10)
    try:
        q_objectives = int(q_objectives)
        q_content = int(q_content)
        q_starter_code = int(q_starter_code)
        q_difficulty = int(q_difficulty)
        q_overall = int(q_overall)
        time_spent = int(time_spent)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rating value")

    for rating, name in [(q_objectives, "objectives"), (q_content, "content"),
                          (q_starter_code, "starter code"), (q_difficulty, "difficulty"),
                          (q_overall, "overall")]:
        if rating < 1 or rating > 10:
            raise HTTPException(status_code=400, detail=f"Rating for {name} must be between 1 and 10")

    # Store feedback responses as JSON
    feedback_responses = {
        "q_objectives": q_objectives,
        "q_content": q_content,
        "q_starter_code": q_starter_code,
        "q_difficulty": q_difficulty,
        "q_overall": q_overall,
    }

    # Legacy fields - set defaults
    github_link = "https://github.com/feedback-only"  # Placeholder for feedback-only submissions
    clarity_rating = None
    difficulty_rating = None

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
        existing.feedback_responses = feedback_responses
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
            feedback_responses=feedback_responses,
        )
        db.add(submission)

    db.commit()
    db.refresh(submission)

    # Send notifications with new feedback format
    send_submission_notification(
        reviewer_name=user.name or user.email,
        reviewer_email=user.email,
        module_name=module.name,
        submission_type=submission_type,
        github_link=None,  # No longer required
        comments=comments,
        clarity_rating=q_objectives,  # Map to objectives rating
        difficulty_rating=q_difficulty,
        time_spent=time_spent,
        feedback_responses=feedback_responses,
    )

    await notify_slack_new_submission(
        reviewer_name=user.name or user.email,
        reviewer_email=user.email,
        module_name=module.name,
        submission_type=submission_type,
        github_link=None,
        clarity_rating=q_objectives,
        difficulty_rating=q_difficulty,
        time_spent=time_spent,
        comments=comments,
        feedback_responses=feedback_responses,
    )

    # Note: Grading is now handled by GitHub Classroom autograder

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
