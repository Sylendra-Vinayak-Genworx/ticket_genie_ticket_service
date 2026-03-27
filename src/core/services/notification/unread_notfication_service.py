from __future__ import annotations
from src.constants.enum import NotificationStatus
 
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.notification_log import NotificationLog
 
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
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
        """
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
                p = dict(log.payload)
                # Ensure the ID is present in the backfilled payload
                p["notification_id"] = log.notification_id
                payloads.append(p)
 
        logger.debug(
            "unread_service: user=%s returning %d notifications (since_hours=%d)",
            recipient_user_id, len(payloads), since_hours,
        )
        return payloads

    async def mark_as_read(self, user_id: str, notification_id: int) -> bool:
        """Mark a single notification as read, if it belongs to the user."""
        result = await self._repo.db.execute(
            select(NotificationLog).where(
                NotificationLog.notification_id == notification_id,
                NotificationLog.recipient_user_id == user_id
            )
        )
        log = result.scalar_one_or_none()
        if not log:
            return False
        
        log.status = NotificationStatus.READ
        await self._repo.db.flush()
        return True

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all unread IN_APP notifications for user as read."""
        return await self._repo.mark_all_as_read(user_id)