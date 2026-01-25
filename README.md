# Course Material Review Portal

A web application for crowdsourcing reviews of course materials for a graduate-level Agentic AI Systems course at UCLA Extension.

## Features

- **Google Sign-In** - Reviewers/students authenticate with Google OAuth
- **Module Selection** - Choose modules to review with capacity limits
- **Rich Module Details** - Learning objectives, prerequisites, grading criteria
- **Google Drive Integration** - Pull and serve PDFs directly from Drive
- **Version Notifications** - Email users when module PDFs are updated
- **Submission Form** - Submit GitHub link + review comments
- **Auto-Grading** - Run evaluation scripts against GitHub repos
- **Grade Display** - Score breakdown, strengths, improvements, feedback
- **Admin Dashboard** - Manage modules, users, visibility, grades
- **Weekly Reminders** - Automated emails to users with pending work

## Tech Stack

- **Backend:** Python FastAPI
- **Database:** PostgreSQL (Railway managed)
- **Auth:** Google OAuth 2.0
- **Frontend:** Jinja2 templates + Tailwind CSS
- **File Storage:** Google Drive (via Service Account)
- **Email:** Resend
- **Slack:** Webhooks for admin notifications
- **Deployment:** Railway

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL database
- Google Cloud project with OAuth and Drive API enabled
- Resend account (optional, for email)
- Slack app (optional, for notifications)

### Local Development

1. Clone the repository:
```bash
git clone <repo-url>
cd course-review-portal
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the development server:
```bash
uvicorn app.main:app --reload
```

7. Visit http://localhost:8000

### Environment Variables

See `.env.example` for all required configuration variables.

## Project Structure

```
course-review-portal/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app initialization
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLAlchemy engine & session
│   ├── models.py            # ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── auth.py              # Google OAuth helpers
│   ├── drive.py             # Google Drive integration
│   ├── notifications.py     # Email sending functions
│   ├── slack.py             # Slack webhook notifications
│   ├── grading.py           # Auto-grading logic
│   ├── reminders.py         # Weekly reminder logic
│   ├── dependencies.py      # get_current_user, require_admin
│   └── routers/
│       ├── auth.py          # /auth/* routes
│       ├── dashboard.py     # /dashboard routes
│       ├── modules.py       # /modules/* routes
│       ├── submissions.py   # /submit/* routes
│       ├── grades.py        # /grades/* routes
│       └── admin.py         # /admin/* routes
├── templates/               # Jinja2 templates
├── static/                  # Static assets
├── alembic/                 # Database migrations
├── requirements.txt
├── Procfile
├── railway.toml
└── README.md
```

## API Endpoints

### Authentication
- `GET /` - Landing page
- `GET /auth/google` - Initiate OAuth
- `GET /auth/google/callback` - OAuth callback
- `POST /auth/logout` - Log out

### User Dashboard
- `GET /dashboard` - Main dashboard
- `GET /settings/reminders` - Reminder preferences

### Modules
- `GET /modules` - List available modules
- `GET /modules/{id}` - Module details
- `POST /modules/{id}/select` - Select a module
- `POST /modules/{id}/release` - Release module
- `GET /modules/{id}/pdf` - View PDF
- `GET /modules/{id}/pdf/download` - Download PDF

### Submissions
- `GET /submit/{type}` - Submission form
- `POST /submit/{type}` - Submit assignment
- `GET /my-submissions` - View all submissions

### Grades
- `GET /submissions/{id}/grade` - View grade
- `POST /submissions/{id}/regrade` - Request re-grade
- `GET /my-grades` - View all grades

### Admin
- `GET /admin` - Admin dashboard
- `GET /admin/modules` - Manage modules
- `POST /admin/modules` - Create module
- `GET /admin/modules/{id}/edit` - Edit module
- `POST /admin/modules/{id}/check-update` - Check PDF update
- `GET /admin/users` - Manage users
- `POST /admin/users/{id}/role` - Change user role
- `GET /admin/submissions` - View all submissions
- `POST /admin/submissions/{id}/grade` - Trigger grading
- `GET /admin/submissions/export` - Export CSV

## Deployment to Railway

1. Create a new Railway project
2. Add PostgreSQL database
3. Connect your GitHub repository
4. Set environment variables in Railway dashboard
5. Deploy!

The `railway.toml` is configured to run migrations automatically on deploy.

## Google Cloud Setup

### OAuth Credentials
1. Go to Google Cloud Console
2. Create a new project or select existing
3. Enable Google+ API
4. Go to Credentials > Create Credentials > OAuth client ID
5. Configure consent screen
6. Create Web application credentials
7. Add authorized redirect URI: `https://yourapp.up.railway.app/auth/google/callback`

### Service Account for Drive
1. Go to IAM & Admin > Service Accounts
2. Create new service account
3. Download JSON key
4. Share your Drive PDFs with the service account email

## License

MIT
