"""Google OAuth authentication helpers."""
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config

from app.config import settings

# OAuth client configuration
oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def get_google_oauth():
    """Get the configured Google OAuth client."""
    return oauth.google
