"""Application configuration using Pydantic settings."""
import json
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = "postgresql://localhost/course_review"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"

    # Google Drive Service Account
    GOOGLE_SERVICE_ACCOUNT_JSON: str = "{}"

    # Email (Resend)
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "noreply@example.com"
    ADMIN_EMAIL: str = "admin@example.com"

    # Slack
    SLACK_WEBHOOK_URL: Optional[str] = None

    # App Configuration
    SECRET_KEY: str = "change-me-in-production"
    APP_URL: str = "http://localhost:8000"
    ADMIN_EMAILS: str = ""  # Comma-separated list

    @property
    def admin_email_list(self) -> list[str]:
        """Parse comma-separated admin emails into a list."""
        if not self.ADMIN_EMAILS:
            return [self.ADMIN_EMAIL] if self.ADMIN_EMAIL else []
        return [e.strip() for e in self.ADMIN_EMAILS.split(",") if e.strip()]

    @property
    def google_service_account_info(self) -> dict:
        """Parse service account JSON."""
        try:
            return json.loads(self.GOOGLE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError:
            return {}

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
