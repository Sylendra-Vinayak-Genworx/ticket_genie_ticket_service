"""
NotificationLog repository — manages the ``notification_logs`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import NotificationChannel, NotificationStatus
from src.data.models.postgres.notification_log import NotificationLog


class NotificationLogRepository:
    """Data-access layer for the ``notification_logs`` table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, log: NotificationLog) -> None:
        """Insert a new notification log row and flush to obtain its ID."""
        self.db.add(log)
        await self.db.flush()

    async def get_by_ticket_id(self, ticket_id: int) -> list[NotificationLog]:
        """Return all notification logs for the given ticket, newest first."""
        result = await self.db.execute(
            select(NotificationLog)
            .where(NotificationLog.ticket_id == ticket_id)
            .order_by(NotificationLog.created_at.desc())
        )
        return list(result.scalars().all())

    async def mark_as_read(self, notification_id: int) -> bool:
        """Mark a single notification as READ."""
        result = await self.db.execute(
            select(NotificationLog).where(NotificationLog.notification_id == notification_id)
        )
        log = result.scalar_one_or_none()
        if log:
            log.status = NotificationStatus.READ
            await self.db.flush()
            return True
        return False

    async def mark_all_as_read(self, recipient_user_id: str) -> int:
        """Mark all IN_APP notifications for a user as READ. Returns count updated."""
        # Using a select then update approach to stay within repo patterns or bulk update
        from sqlalchemy import update
        result = await self.db.execute(
            update(NotificationLog)
            .where(
                NotificationLog.recipient_user_id == recipient_user_id,
                NotificationLog.channel == NotificationChannel.IN_APP,
                NotificationLog.status != NotificationStatus.READ,
            )
            .values(status=NotificationStatus.READ)
        )
        await self.db.flush()
        return result.rowcount
    
    async def get_unread_for_user(
    self,
    recipient_user_id: str,
    since_hours: int = 24,
    limit: int = 50,
) -> list[NotificationLog]:
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        result = await self.db.execute(
            select(NotificationLog)
            .where(
                NotificationLog.recipient_user_id == recipient_user_id,
                NotificationLog.channel == NotificationChannel.IN_APP,
                NotificationLog.sent_at >= since,
                NotificationLog.status != NotificationStatus.READ,
                NotificationLog.payload.is_not(None),
            )
            .order_by(NotificationLog.sent_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())