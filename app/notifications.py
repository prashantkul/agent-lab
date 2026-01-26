"""Email notifications using Resend."""
from typing import Optional

import resend

from app.config import settings


def init_resend():
    """Initialize Resend API key."""
    if settings.RESEND_API_KEY:
        resend.api_key = settings.RESEND_API_KEY


def send_email(to: str, subject: str, html: str):
    """Send an email via Resend."""
    if not settings.RESEND_API_KEY:
        print(f"[Email Skipped - No API Key] To: {to}, Subject: {subject}")
        return

    init_resend()
    resend.Emails.send(
        {
            "from": f"Course Review Portal <{settings.FROM_EMAIL}>",
            "to": to,
            "subject": subject,
            "html": html,
        }
    )


def send_pdf_update_notification(to_email: str, user_name: str, module_name: str):
    """Notify user when a module's PDF has been updated."""
    subject = f"[Course Review] Updated materials: {module_name}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h2 style="color: white; margin: 0;">Module Materials Updated</h2>
        </div>
        <div style="background: white; padding: 30px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
            <p style="color: #1e293b; font-size: 16px;">Hi {user_name},</p>
            <p style="color: #64748b;">The PDF for <strong>{module_name}</strong> has been updated.</p>
            <p style="color: #64748b;">Please download the latest version before completing your review.</p>
            <div style="text-align: center; margin-top: 30px;">
                <a href="{settings.APP_URL}/dashboard"
                   style="display: inline-block; background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
                          color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px;
                          font-weight: 600;">
                    View Updated Materials
                </a>
            </div>
            <p style="color: #94a3b8; font-size: 14px; margin-top: 30px;">
                Thanks,<br>Course Review Portal
            </p>
        </div>
    </div>
    """
    send_email(to_email, subject, html)


def send_submission_notification(
    reviewer_name: str,
    reviewer_email: str,
    module_name: str,
    submission_type: str,
    github_link: Optional[str],
    comments: str,
    clarity_rating: Optional[int],
    difficulty_rating: Optional[int],
    time_spent: Optional[int],
    feedback_responses: Optional[dict] = None,
):
    """Notify admin when a new submission is received."""
    subject = f"[Course Review] New feedback submission: {module_name}"

    time_str = f"{time_spent} minutes" if time_spent else "Not specified"

    # Build ratings display from feedback_responses
    ratings_html = ""
    if feedback_responses:
        labels = {
            "q_objectives": "Learning Objectives",
            "q_content": "Content Quality",
            "q_starter_code": "Starter Code",
            "q_difficulty": "Difficulty Level",
            "q_overall": "Overall Rating",
        }
        for key, label in labels.items():
            value = feedback_responses.get(key, "N/A")
            ratings_html += f'<tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>{label}</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{value}/10</td></tr>'

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h2 style="color: white; margin: 0;">New Module Feedback</h2>
        </div>
        <div style="background: white; padding: 30px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
            <table style="border-collapse: collapse; width: 100%;">
                <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Reviewer</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{reviewer_name} ({reviewer_email})</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Module</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{module_name}</td></tr>
                <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Time Spent</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{time_str}</td></tr>
                {ratings_html}
            </table>
            <h3 style="color: #1e293b; margin-top: 20px;">Additional Comments</h3>
            <div style="background: #f5f5f5; padding: 16px; border-radius: 8px; white-space: pre-wrap;">{comments if comments else 'No additional comments'}</div>
            <p style="margin-top: 24px;">
                <a href="{settings.APP_URL}/admin/submissions" style="color: #3b82f6;">View All Submissions</a>
            </p>
        </div>
    </div>
    """
    send_email(settings.ADMIN_EMAIL, subject, html)


def send_grade_notification(
    to_email: str,
    user_name: str,
    module_name: str,
    submission_type: str,
    submission_id: int,
    total_points: float,
    max_points: int,
    letter_grade: str,
):
    """Notify user when their grade is ready."""
    subject = f"[Course] Your grade is ready: {module_name}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h2 style="color: white; margin: 0;">Your submission has been graded!</h2>
        </div>
        <div style="background: white; padding: 30px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
            <p style="color: #1e293b; font-size: 16px;">Hi {user_name},</p>
            <p style="color: #64748b;">
                Your <strong>{submission_type.replace('_', ' ')}</strong> submission
                for <strong>{module_name}</strong> has been graded.
            </p>
            <div style="background: #f0fdf4; border: 1px solid #86efac; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
                <h3 style="margin: 0; color: #166534;">Score: {total_points}/{max_points} ({letter_grade})</h3>
            </div>
            <div style="text-align: center; margin-top: 30px;">
                <a href="{settings.APP_URL}/submissions/{submission_id}/grade"
                   style="display: inline-block; background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
                          color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px;
                          font-weight: 600;">
                    View Full Feedback
                </a>
            </div>
        </div>
    </div>
    """
    send_email(to_email, subject, html)


def send_reminder_email(user_email: str, user_name: str, pending_items: list):
    """Send weekly reminder email to user with pending work."""
    not_submitted = [p for p in pending_items if p["status"] == "not_submitted"]
    awaiting_grade = [p for p in pending_items if p["status"] == "awaiting_grade"]
    has_updates = [p for p in pending_items if p["status"] == "new_version_available"]

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">Weekly Progress Reminder</h1>
        </div>
        <div style="background: white; padding: 30px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
            <p style="color: #1e293b; font-size: 16px;">Hi {user_name},</p>
            <p style="color: #64748b;">Here's a quick update on your course evaluation progress:</p>
    """

    if not_submitted:
        html += """
            <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                <h3 style="color: #92400e; margin: 0 0 10px 0; font-size: 14px;">Pending Submissions</h3>
                <ul style="margin: 0; padding-left: 20px; color: #78350f;">
        """
        for item in not_submitted:
            type_label = "In-Class Exercise" if item["type"] == "in_class" else "Homework"
            html += f"<li>{item['module']} - {type_label}</li>"
        html += "</ul></div>"

    if has_updates:
        html += """
            <div style="background: #dbeafe; border-left: 4px solid #3b82f6; padding: 15px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                <h3 style="color: #1e40af; margin: 0 0 10px 0; font-size: 14px;">Updated Materials</h3>
                <p style="margin: 0; color: #1e3a8a;">New versions available - please download the latest PDF before submitting.</p>
            </div>
        """

    if awaiting_grade:
        html += """
            <div style="background: #ecfdf5; border-left: 4px solid #10b981; padding: 15px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                <h3 style="color: #065f46; margin: 0 0 10px 0; font-size: 14px;">Submitted - Awaiting Grade</h3>
                <p style="margin: 0; color: #047857;">Your submissions are being reviewed. Grades coming soon!</p>
            </div>
        """

    html += f"""
            <div style="text-align: center; margin-top: 30px;">
                <a href="{settings.APP_URL}/dashboard"
                   style="display: inline-block; background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
                          color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px;
                          font-weight: 600; font-size: 14px;">
                    Go to Dashboard
                </a>
            </div>
            <p style="color: #94a3b8; font-size: 12px; margin-top: 30px; text-align: center;">
                <a href="{settings.APP_URL}/settings/reminders" style="color: #94a3b8;">Manage reminder preferences</a>
            </p>
        </div>
    </div>
    """

    subject = "Weekly Progress Reminder - Agentic AI Course"
    send_email(user_email, subject, html)
