"""Authentication routes for Google OAuth."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_google_oauth
from app.config import settings
from app.database import get_db
from app.dependencies import is_admin_email, require_user
from app.models import User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/google")
async def google_login(request: Request):
    """Initiate Google OAuth flow."""
    google = get_google_oauth()
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """Handle Google OAuth callback."""
    try:
        google = get_google_oauth()
        token = await google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to get user info")

        google_id = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        # Find or create user
        user = db.query(User).filter(User.google_id == google_id).first()

        if not user:
            # Determine role based on email
            role = UserRole.admin if is_admin_email(email) else UserRole.reviewer

            user = User(
                google_id=google_id,
                email=email,
                name=name,
                picture_url=picture,
                role=role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # Update user info
            user.name = name
            user.picture_url = picture
            user.email = email
            db.commit()

        # Set session
        request.session["user_id"] = user.id

        # Redirect to confidentiality agreement if not accepted (except admins)
        if not user.accepted_terms_at and user.role != UserRole.admin:
            return RedirectResponse(url="/confidentiality", status_code=303)

        return RedirectResponse(url="/home", status_code=303)

    except Exception as e:
        print(f"OAuth error: {e}")
        return RedirectResponse(url="/?error=auth_failed", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    """Log out the current user."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
