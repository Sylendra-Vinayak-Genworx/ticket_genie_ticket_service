"""
TicketComment repository — manages the ``ticket_comments`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.data.models.postgres.ticket_comment import TicketComment


class TicketCommentRepository:
    """Data-access layer for the ``ticket_comments`` table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, comment: TicketComment) -> TicketComment:
        """Insert a new comment row and flush to obtain its ID."""
        self.db.add(comment)
        await self.db.flush()
        await self.db.refresh(comment, attribute_names=["attachments"])
        return comment

    async def get_by_ticket_id(self, ticket_id: int) -> list[TicketComment]:
        """Return all comments for the given ticket, oldest first, with attachments."""
        result = await self.db.execute(
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket_id)
            .options(selectinload(TicketComment.attachments))
            .order_by(TicketComment.created_at.asc())
        )
        return list(result.scalars().all())