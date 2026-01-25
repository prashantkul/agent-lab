"""Google Drive integration for serving PDFs."""
import io
from typing import Generator, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def get_drive_service():
    """Create Drive API service using service account."""
    service_account_info = settings.google_service_account_info
    if not service_account_info or not service_account_info.get("type"):
        raise ValueError("Google Service Account not configured")

    creds = service_account.Credentials.from_service_account_info(
        service_account_info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def get_file_metadata(file_id: str) -> dict:
    """Get file metadata including modifiedTime."""
    service = get_drive_service()
    return (
        service.files()
        .get(fileId=file_id, fields="id,name,mimeType,modifiedTime,size")
        .execute()
    )


def stream_file(file_id: str) -> Generator[bytes, None, None]:
    """Generator that yields file chunks for streaming response."""
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        buffer.seek(0)
        yield buffer.read()
        buffer.seek(0)
        buffer.truncate()


def get_file_content(file_id: str) -> bytes:
    """Download entire file content."""
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    buffer.seek(0)
    return buffer.read()
