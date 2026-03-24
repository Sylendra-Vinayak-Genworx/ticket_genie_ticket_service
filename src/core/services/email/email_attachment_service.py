import logging
from src.core.services.gcs_service import upload_attachment as gcs_upload
from src.schemas.email_schema import EmailPayload

logger = logging.getLogger(__name__)

class EmailAttachmentService:
    async def upload_email_attachments(
        self,
        payload: EmailPayload,
        folder: str,
    ) -> list[str]:
        blob_paths: list[str] = []
        for att in (payload.attachments or []):
            try:
                blob_path = await gcs_upload(
                    file_bytes=att.data,
                    filename=att.filename,
                    folder=folder,
                )
                blob_paths.append(blob_path)
                logger.info(
                    "email_ingest: uploaded attachment filename=%r blob=%s",
                    att.filename, blob_path,
                )
            except Exception:
                logger.exception(
                    "email_ingest: failed to upload attachment filename=%r — skipping",
                    att.filename,
                )
        return blob_paths
