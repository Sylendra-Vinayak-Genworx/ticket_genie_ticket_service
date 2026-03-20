import logging
import uuid
from pathlib import PurePosixPath, Path
from datetime import timedelta

from fastapi import UploadFile
from src.config.settings import get_settings

logger = logging.getLogger("ticket.gcs")

TICKET_PREFIX  = "tickets"
COMMENT_PREFIX = "comments"

_bucket = None
_signing_credentials = None

def _get_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket
    from google.cloud import storage
    s = get_settings()
    client = storage.Client(project=s.GCS_PROJECT_ID)
    _bucket = client.bucket(s.GCS_BUCKET_NAME)
    logger.info(f"[GCS] bucket ready: {s.GCS_BUCKET_NAME}")
    return _bucket


def _get_signing_credentials():
    global _signing_credentials
    if _signing_credentials is not None:
        return _signing_credentials
    import google.auth
    import google.auth.transport.requests
    from google.auth import impersonated_credentials

    s = get_settings()
    source_creds, _ = google.auth.default()
    request = google.auth.transport.requests.Request()
    source_creds.refresh(request)

    _signing_credentials = impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=s.GCS_TARGET_SERVICE_ACCOUNT,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
        lifetime=3600,
    )
    logger.info(f"[GCS] signing credentials ready for {s.GCS_TARGET_SERVICE_ACCOUNT}")
    return _signing_credentials


def _object_name(area: str, filename: str) -> str:
    s = get_settings()
    prefix = (s.GCS_BUCKET_PREFIX or "").strip("/")
    parts = [p for p in [prefix, area, filename] if p]
    joined = "/".join(parts)
    path = PurePosixPath(joined)
    if any(part in (".", "..") for part in path.parts):
        raise ValueError(f"Unsafe GCS object path: {joined}")
    return joined


def upload_attachment(file_bytes: bytes, filename: str, folder: str) -> str:
    s = get_settings()
    safe_name = Path(filename).name.replace(" ", "_")[:100]
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    blob_path = f"{s.GCS_BUCKET_PREFIX}/attachments/{folder}/{unique_name}"
    blob = _get_bucket().blob(blob_path)
    blob.upload_from_string(file_bytes, content_type="application/octet-stream")
    logger.info(f"[GCS] upload: {blob_path}")
    return blob_path


async def upload_image(file: UploadFile, prefix: str = TICKET_PREFIX) -> dict:
    data = await file.read()
    original_name = file.filename or "upload"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
    stored_name = f"{uuid.uuid4()}.{ext}"
    obj_name = _object_name(prefix, stored_name)
    blob = _get_bucket().blob(obj_name)
    blob.cache_control = "private, max-age=3600"
    blob.upload_from_string(data, content_type=file.content_type)
    url = get_public_url(obj_name)
    logger.info(f"[GCS] upload_image: {obj_name}")
    return {
        "original_name": original_name,
        "stored_name":   stored_name,
        "content_type":  file.content_type,
        "size_bytes":    len(data),
        "path":          obj_name,
        "file_url":      url,
    }


def download_attachment(blob_path: str) -> bytes:
    blob = _get_bucket().blob(blob_path)
    data = blob.download_as_bytes()
    logger.info(f"[GCS] download: {blob_path} ({len(data)} bytes)")
    return data


def get_public_url(blob_path: str) -> str:
    """Return blob path — signed URL generated on read, not on write."""
    return blob_path

def get_public_url_disabled(blob_path: str) -> str:
    return generate_signed_url(blob_path)


def generate_signed_url(object_path: str, expiry_minutes: int = 60) -> str:
    try:
        signing_creds = _get_signing_credentials()
        blob = _get_bucket().blob(object_path)
        url = blob.generate_signed_url(
            expiration=timedelta(minutes=expiry_minutes),
            method="GET",
            version="v4",
            credentials=signing_creds,
        )
        logger.info(f"[GCS] signed URL ok for {object_path}")
        return url
    except Exception as exc:
        logger.error(f"[GCS] Signed URL failed for '{object_path}': {exc}")
        s = get_settings()
        return f"https://storage.googleapis.com/{s.GCS_BUCKET_NAME}/{object_path}"
