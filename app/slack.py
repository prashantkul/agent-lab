"""Slack webhook notifications."""
from typing import Optional

import httpx

from app.config import settings


async def send_slack_notification(message: dict):
    """Send a message to Slack via webhook."""
    if not settings.SLACK_WEBHOOK_URL:
        print(f"[Slack Skipped - No Webhook] Message: {message}")
        return

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                settings.SLACK_WEBHOOK_URL, json=message, timeout=10.0
            )
        except httpx.RequestError as e:
            print(f"[Slack Error] Failed to send notification: {e}")


async def notify_slack_new_submission(
    reviewer_name: str,
    reviewer_email: str,
    module_name: str,
    submission_type: str,
    github_link: str,
    clarity_rating: Optional[int],
    difficulty_rating: Optional[int],
    time_spent: Optional[int],
    comments: str,
):
    """Send rich Slack notification for new submission."""
    # Truncate comments for Slack (keep it digestible)
    preview_comments = comments[:500] + "..." if len(comments) > 500 else comments

    clarity_str = f"{'*' * clarity_rating} ({clarity_rating}/5)" if clarity_rating else "N/A"
    difficulty_str = f"{'*' * difficulty_rating} ({difficulty_rating}/5)" if difficulty_rating else "N/A"
    time_str = f"{time_spent} minutes" if time_spent else "N/A"

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"New {submission_type.replace('_', ' ').title()} Submission",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Module:*\n{module_name}"},
                    {"type": "mrkdwn", "text": f"*Reviewer:*\n{reviewer_name}"},
                    {"type": "mrkdwn", "text": f"*Clarity:* {clarity_str}"},
                    {"type": "mrkdwn", "text": f"*Difficulty:* {difficulty_str}"},
                    {"type": "mrkdwn", "text": f"*Time Spent:*\n{time_str}"},
                    {"type": "mrkdwn", "text": f"*Email:*\n{reviewer_email}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*GitHub:* <{github_link}|View Repository>",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Comments:*\n```{preview_comments}```",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View All Submissions"},
                        "url": f"{settings.APP_URL}/admin/submissions",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open GitHub"},
                        "url": github_link,
                    },
                ],
            },
        ]
    }

    await send_slack_notification(message)


async def notify_slack_new_reviewer(
    reviewer_name: str, reviewer_email: str, module_name: str
):
    """Notify when someone selects a module."""
    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{reviewer_name}* ({reviewer_email}) signed up to review *{module_name}*",
                },
            }
        ]
    }
    await send_slack_notification(message)


async def notify_slack_pdf_updated(module_name: str, notified_count: int):
    """Notify admin when PDF is updated and reviewers are notified."""
    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{module_name}* PDF was updated. Notified {notified_count} reviewer(s) via email.",
                },
            }
        ]
    }
    await send_slack_notification(message)


async def notify_slack_grade_completed(
    user_name: str,
    module_name: str,
    submission_type: str,
    total_points: float,
    max_points: int,
    letter_grade: str,
):
    """Notify Slack when grading is complete."""
    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Grading Complete*\n*{user_name}* - {module_name} ({submission_type.replace('_', ' ')})\nScore: *{total_points}/{max_points}* ({letter_grade})",
                },
            }
        ]
    }
    await send_slack_notification(message)


async def notify_slack_reminders_sent(count: int):
    """Notify admin via Slack when reminders are sent."""
    message = {
        "text": f"Weekly reminders sent to {count} users with pending evaluations."
    }
    await send_slack_notification(message)
