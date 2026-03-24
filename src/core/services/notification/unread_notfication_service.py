from __future__ import annotations
 
import logging
 
from sqlalchemy.ext.asyncio import AsyncSession
 
from src.data.repositories.notification_log_repository import NotificationLogRepository
 
logger = logging.getLogger(__name__)
 
_DEFAULT_SINCE_HOURS = 24
_DEFAULT_LIMIT = 50
 
 
class UnreadNotificationService:
    """
    Fetches persisted IN_APP notification payloads for a given user.
    Used exclusively by the /notifications/unread endpoint to backfill
    the frontend after an offline period.
    """
 
    def __init__(self, db: AsyncSession) -> None:
        self._repo = NotificationLogRepository(db)
 
    async def get_unread(
        self,
        recipient_user_id: str,
        since_hours: int = _DEFAULT_SINCE_HOURS,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict]:
        """
        Return a list of SSE payload dicts for the user, newest first.
        Rows with a null payload are silently skipped — they pre-date
        the payload column and cannot be replayed.
        """
        logs = await self._repo.get_unread_for_user(
            recipient_user_id=recipient_user_id,
            since_hours=since_hours,
            limit=limit,
        )
 
        payloads = []
        for log in logs:
            if log.payload:
                payloads.append(log.payload)
 
        logger.debug(
            "unread_service: user=%s returning %d notifications (since_hours=%d)",
            recipient_user_id, len(payloads), since_hours,
        )
        return payloads