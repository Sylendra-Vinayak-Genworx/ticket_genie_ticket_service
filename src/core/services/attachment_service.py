import logging
from typing import TypedDict
from fastapi import UploadFile, HTTPException, status
from src.core.services.gcs_service import upload_attachment as gcs_upload, generate_signed_url

logger = logging.getLogger(__name__)

class AttachmentMeta(TypedDict):
    file_name: str | None
    file_url: str
    blob_path: str

class AttachmentService:
    _ALLOWED_TYPES = {
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "application/pdf", "text/plain", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    _MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    async def validate_file(self, file: UploadFile) -> bytes:
        """Validate file type and size. Returns file contents."""
        if file.content_type not in self._ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"File type '{file.content_type}' is not allowed. "
                    f"Accepted: {sorted(self._ALLOWED_TYPES)}"
                ),
            )

        contents = await file.read()
        if not isinstance(contents, bytes):
            contents = bytes(contents)
        if len(contents) > self._MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds the 10 MB limit.",
            )
        return contents

    async def _upload_to_gcs(self, file: UploadFile, user_id: str, folder_prefix: str) -> AttachmentMeta:
        """Generic upload helper."""
        contents = await self.validate_file(file)
        
        try:
            blob_path = await gcs_upload(
                file_bytes=contents,
                filename=file.filename or "attachment",
                folder=f"{folder_prefix}/pending/{user_id}",
            )
            signed_url = generate_signed_url(blob_path)
            
            return {
                "file_name": file.filename,
                "file_url": signed_url,
                "blob_path": blob_path,
            }
        except Exception as exc:
            logger.exception("GCS upload failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"GCS upload failed: {exc}",
            )

    async def upload_ticket_attachment(self, file: UploadFile, user_id: str) -> AttachmentMeta:
        """Upload a ticket-level attachment."""
        return await self._upload_to_gcs(file, user_id, "tickets")

    async def upload_comment_attachment(self, file: UploadFile, user_id: str) -> AttachmentMeta:
        """Upload a comment-level attachment."""
        return await self._upload_to_gcs(file, user_id, "comments")
