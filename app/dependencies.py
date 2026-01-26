"""FastAPI dependencies for authentication and authorization."""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.config import settings


async def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """Get the current authenticated user from session."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    return user


async def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Require an authenticated user, redirect to login if not."""
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/"},
        )
    return user


async def require_admin(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Require an admin user."""
    user = await require_user(request, db)
    if user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def is_admin_email(email: str) -> bool:
    """Check if an email is in the admin list."""
    return email in settings.admin_email_list
