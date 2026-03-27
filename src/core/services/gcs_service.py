import logging
import uuid
import httpx
import urllib.parse
from pathlib import PurePosixPath, Path
from datetime import timedelta

from fastapi import UploadFile
from src.config.settings import get_settings

logger = logging.getLogger("ticket.gcs")

TICKET_PREFIX  = "tickets"
COMMENT_PREFIX = "comments"

_credentials = None
_signing_credentials = None


async def _get_access_token() -> str:
    global _credentials
    import asyncio
    
    def _refresh():
        global _credentials
        import google.auth
        import google.auth.transport.requests
        if _credentials is None:
            _credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not _credentials.valid:
            req = google.auth.transport.requests.Request()
            _credentials.refresh(req)
        return _credentials.token
        
    return await asyncio.to_thread(_refresh)


def _get_signing_credentials():
    global _signing_credentials
    if _signing_credentials is not None:
        return _signing_credentials
    import google.auth
    import google.auth.transport.requests
    from google.auth import impersonated_credentials

    s = get_settings()
    source_creds, _ = google.auth.default()
    req = google.auth.transport.requests.Request()
    source_creds.refresh(req)

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


async def upload_attachment(file_bytes: bytes, filename: str, folder: str) -> str:
    """
    Upload attachment.
    
    Args:
        file_bytes (bytes): Input parameter.
        filename (str): Input parameter.
        folder (str): Input parameter.
    
    Returns:
        str: The expected output.
    """
    s = get_settings()
    safe_name = Path(filename).name.replace(" ", "_")[:100]
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    blob_path = f"{s.GCS_BUCKET_PREFIX}/attachments/{folder}/{unique_name}"
    
    token = await _get_access_token()
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{s.GCS_BUCKET_NAME}/o?uploadType=media&name={urllib.parse.quote(blob_path, safe='')}"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            content=file_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream"
            }
        )
        resp.raise_for_status()

    logger.info(f"[GCS] upload: {blob_path}")
    return blob_path


async def upload_image(file: UploadFile, prefix: str = TICKET_PREFIX) -> dict:
    """
    Upload image.
    
    Args:
        file (UploadFile): Input parameter.
        prefix (str): Input parameter.
    
    Returns:
        dict: The expected output.
    """
    s = get_settings()
    data = await file.read()
    original_name = file.filename or "upload"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
    stored_name = f"{uuid.uuid4()}.{ext}"
    obj_name = _object_name(prefix, stored_name)
    
    token = await _get_access_token()
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{s.GCS_BUCKET_NAME}/o?uploadType=media&name={urllib.parse.quote(obj_name, safe='')}"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            content=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": file.content_type,
                "Cache-Control": "private, max-age=3600"
            }
        )
        resp.raise_for_status()
        
    file_url = get_public_url(obj_name)
    logger.info(f"[GCS] upload_image: {obj_name}")
    return {
        "original_name": original_name,
        "stored_name":   stored_name,
        "content_type":  file.content_type,
        "size_bytes":    len(data),
        "path":          obj_name,
        "file_url":      file_url,
    }


async def download_attachment(blob_path: str) -> bytes:
    """
    Download attachment.
    
    Args:
        blob_path (str): Input parameter.
    
    Returns:
        bytes: The expected output.
    """
    s = get_settings()
    token = await _get_access_token()
    url = f"https://storage.googleapis.com/storage/v1/b/{s.GCS_BUCKET_NAME}/o/{urllib.parse.quote(blob_path, safe='')}?alt=media"
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        data = resp.content
        
    logger.info(f"[GCS] download: {blob_path} ({len(data)} bytes)")
    return data


def get_public_url(blob_path: str) -> str:
    """Return blob path — signed URL generated on read, not on write."""
    return blob_path


def get_public_url_disabled(blob_path: str) -> str:
    """
    Get public url disabled.
    
    Args:
        blob_path (str): Input parameter.
    
    Returns:
        str: The expected output.
    """
    return generate_signed_url(blob_path)


def generate_signed_url(object_path: str, expiry_minutes: int = 60) -> str:
    """
    Generate signed url.
    
    Args:
        object_path (str): Input parameter.
        expiry_minutes (int): Input parameter.
    
    Returns:
        str: The expected output.
    """
    try:
        from google.cloud import storage
        s = get_settings()
        client = storage.Client(project=s.GCS_PROJECT_ID)
        blob = client.bucket(s.GCS_BUCKET_NAME).blob(object_path)
        
        signing_creds = _get_signing_credentials()
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
