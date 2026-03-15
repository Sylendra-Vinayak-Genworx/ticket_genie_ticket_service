from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.email_thread import EmailThread


class EmailThreadRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── READ ──────────────────────────────────────────────────────────────────

    async def get_by_message_id(self, message_id: str) -> Optional[EmailThread]:
        """
        Idempotency check.
        Returns the row if this exact Message-ID was already ingested.
        Normalises to lowercase — message_ids are stored lowercase by the poller.
        """
        result = await self.db.execute(
            select(EmailThread).where(EmailThread.message_id == message_id.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_in_reply_to(self, in_reply_to: str) -> Optional[EmailThread]:
        """
        Thread linkage.
        Finds the stored email whose message_id matches the given In-Reply-To
        value so we can retrieve the linked ticket_id.
        Normalises to lowercase — both sides stored lowercase by the poller.
        """
        result = await self.db.execute(
            select(EmailThread).where(EmailThread.message_id == in_reply_to.lower())
        )
        return result.scalar_one_or_none()

    # ── WRITE ─────────────────────────────────────────────────────────────────

    async def add(self, thread: EmailThread) -> EmailThread:
        self.db.add(thread)
        await self.db.flush()
        return thread