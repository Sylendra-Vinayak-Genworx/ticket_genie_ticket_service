"""
TicketAttachment repository — manages the ``ticket_attachments`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.ticket_attachment import TicketAttachment


class TicketAttachmentRepository:
    """Data-access layer for the ``ticket_attachments`` table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, attachment: TicketAttachment) -> None:
        """Insert a new attachment row and flush to obtain its ID."""
        self.db.add(attachment)
        await self.db.flush()

    async def get_by_ticket_id(self, ticket_id: int) -> list[TicketAttachment]:
        """Return all attachments for the given ticket, ordered by upload time."""
        result = await self.db.execute(
            select(TicketAttachment)
            .where(TicketAttachment.ticket_id == ticket_id)
            .order_by(TicketAttachment.uploaded_at.asc())
        )
        return list(result.scalars().all())
