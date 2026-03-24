"""
NotificationLog repository — manages the ``notification_logs`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import NotificationChannel
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
                NotificationLog.payload.is_not(None),
            )
            .order_by(NotificationLog.sent_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())