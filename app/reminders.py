"""Weekly reminder system for users with pending work."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Grade, Module, Submission, User, UserRole
from app.notifications import send_reminder_email
from app.slack import notify_slack_reminders_sent


def has_grade(submission_id: int, db: Session) -> bool:
    """Check if a submission has been graded."""
    grade = db.query(Grade).filter(
        Grade.submission_id == submission_id,
        Grade.status == "completed"
    ).first()
    return grade is not None


def get_users_with_pending_work(db: Session) -> list:
    """
    Find users who have:
    - Selected a module but haven't submitted
    - Submitted but not graded (might need to check)
    - Module they selected has been updated since they last viewed
    """
    results = []

    # Get all users with selected modules
    users = db.query(User).filter(
        User.selected_module_id.isnot(None),
        User.role.in_([UserRole.REVIEWER, UserRole.STUDENT]),
    ).all()

    for user in users:
        pending_items = []
        module = user.selected_module

        if not module:
            continue

        # Check in-class submission
        in_class_sub = (
            db.query(Submission)
            .filter(
                Submission.user_id == user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "in_class",
            )
            .first()
        )

        if not in_class_sub:
            pending_items.append(
                {"type": "in_class", "module": module.name, "status": "not_submitted"}
            )
        elif not has_grade(in_class_sub.id, db):
            pending_items.append(
                {"type": "in_class", "module": module.name, "status": "awaiting_grade"}
            )

        # Check homework submission
        hw_sub = (
            db.query(Submission)
            .filter(
                Submission.user_id == user.id,
                Submission.module_id == module.id,
                Submission.submission_type == "homework",
            )
            .first()
        )

        if not hw_sub:
            pending_items.append(
                {"type": "homework", "module": module.name, "status": "not_submitted"}
            )
        elif not has_grade(hw_sub.id, db):
            pending_items.append(
                {"type": "homework", "module": module.name, "status": "awaiting_grade"}
            )

        # Check if PDF was updated since user selected
        if (
            module.drive_modified_time
            and module.drive_modified_time != user.last_notified_version
        ):
            pending_items.append(
                {
                    "type": "pdf_update",
                    "module": module.name,
                    "status": "new_version_available",
                }
            )

        if pending_items:
            results.append((user, pending_items))

    return results


async def send_weekly_reminders(db: Session) -> int:
    """
    Send reminder emails to users with incomplete evaluations.
    Called by cron job every Monday at 9 AM.
    """
    users_to_remind = get_users_with_pending_work(db)

    reminder_count = 0
    for user, pending_items in users_to_remind:
        if not user.reminder_enabled:
            continue

        # Don't spam - check if reminded in last 6 days
        if user.last_reminder_sent and user.last_reminder_sent > datetime.utcnow() - timedelta(days=6):
            continue

        # Send personalized reminder
        send_reminder_email(user.email, user.name or user.email, pending_items)

        # Update last reminded timestamp
        user.last_reminder_sent = datetime.utcnow()
        reminder_count += 1

    db.commit()

    # Notify admin via Slack
    await notify_slack_reminders_sent(reminder_count)

    return reminder_count
