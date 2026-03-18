"""
src/core/services/gcs_service.py
=================================
Thin GCS wrapper for ticket attachment storage.
Uploads bytes → returns blob path stored in DB.
Downloads bytes → used when attaching files to outbound SMTP.
Public URL   → returned to frontend for download links.
"""
from __future__ import annotations

import uuid
import logging
from pathlib import Path

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

_bucket = None


def _get_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket

    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'google-cloud-storage'. "
            "Run: uv add google-cloud-storage"
        ) from exc

    s = get_settings()
    client = storage.Client(project=s.GCS_PROJECT_ID)
    _bucket = client.bucket(s.GCS_BUCKET_NAME)
    logger.info(f"GCS bucket initialised: {s.GCS_BUCKET_NAME}")
    return _bucket


def upload_attachment(file_bytes: bytes, filename: str, folder: str) -> str:
    """
    Upload bytes to GCS under:
      {GCS_BUCKET_PREFIX}/attachments/{folder}/{uuid}_{filename}

    Returns the blob path — stored in DB as file_url.

    folder examples:
      "tickets/pending/{user_id}"   for UI-uploaded ticket attachments
      "inbound/mailbox_1"           for emails received
      "outbound/dispute_3"          for FA-sent attachments
    """
    s = get_settings()
    safe_name = Path(filename).name.replace(" ", "_")[:100]
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    blob_path = f"{s.GCS_BUCKET_PREFIX}/attachments/{folder}/{unique_name}"

    blob = _get_bucket().blob(blob_path)
    blob.upload_from_string(file_bytes, content_type="application/octet-stream")
    # blob.make_public() removed — bucket uses uniform bucket-level access (UBA).
    # Public read is controlled at bucket IAM level, not per-object ACL.

    logger.info(f"GCS upload: {blob_path}")
    return blob_path


def download_attachment(blob_path: str) -> bytes:
    """Download bytes from GCS by blob path (as stored in DB)."""
    blob = _get_bucket().blob(blob_path)
    data = blob.download_as_bytes()
    logger.info(f"GCS download: {blob_path} ({len(data)} bytes)")
    return data


def get_public_url(blob_path: str) -> str:
    """Return the public HTTPS URL for a blob."""
    s = get_settings()
    return f"https://storage.googleapis.com/{s.GCS_BUCKET_NAME}/{blob_path}"