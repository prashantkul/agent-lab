"""Grade viewing and regrade request routes."""
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_user
from app.grading import run_auto_grader
from app.models import Grade, Submission, User

router = APIRouter(tags=["grades"])
templates = Jinja2Templates(directory="templates")


@router.get("/submissions/{submission_id}/grade", response_class=HTMLResponse)
async def view_grade(
    submission_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """View grade and feedback for a submission."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Verify user owns this submission
    if submission.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    grade = db.query(Grade).filter(Grade.submission_id == submission_id).first()

    return templates.TemplateResponse(
        "grade_view.html",
        {
            "request": request,
            "user": user,
            "submission": submission,
            "grade": grade,
            "module": submission.module,
        },
    )


@router.post("/submissions/{submission_id}/regrade")
async def request_regrade(
    submission_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Request re-grading of a submission."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if submission.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    module = submission.module
    if not module.grading_enabled:
        raise HTTPException(status_code=400, detail="Grading not enabled for this module")

    # Get or create grade record and set to pending
    grade = db.query(Grade).filter(Grade.submission_id == submission_id).first()
    if grade:
        grade.status = "pending"
        db.commit()

    # Trigger re-grading
    background_tasks.add_task(run_auto_grader_background, submission_id)

    return RedirectResponse(
        url=f"/submissions/{submission_id}/grade?regrade=1", status_code=303
    )


async def run_auto_grader_background(submission_id: int):
    """Background task wrapper for auto-grader."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await run_auto_grader(submission_id, db)
    except Exception as e:
        print(f"Re-grading failed for submission {submission_id}: {e}")
    finally:
        db.close()


@router.get("/my-grades", response_class=HTMLResponse)
async def my_grades(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """View all grades for the current user."""
    submissions = (
        db.query(Submission)
        .filter(Submission.user_id == user.id)
        .order_by(Submission.submitted_at.desc())
        .all()
    )

    # Get grades for each submission
    grades_by_submission = {}
    for submission in submissions:
        grade = db.query(Grade).filter(Grade.submission_id == submission.id).first()
        grades_by_submission[submission.id] = grade

    return templates.TemplateResponse(
        "my_grades.html",
        {
            "request": request,
            "user": user,
            "submissions": submissions,
            "grades": grades_by_submission,
        },
    )
