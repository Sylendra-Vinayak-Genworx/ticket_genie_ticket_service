"""
TicketEvent repository — manages the ``ticket_events`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import EventType
from src.data.models.postgres.ticket_event import TicketEvent


class TicketEventRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, event: TicketEvent) -> None:
        """Insert a new event row and flush to obtain its ID."""
        self.db.add(event)
        await self.db.flush()

    async def get_for_ticket(self, ticket_id: int) -> list[TicketEvent]:
        """All events for a ticket, oldest first."""
        result = await self.db.execute(
            select(TicketEvent)
            .where(TicketEvent.ticket_id == ticket_id)
            .order_by(TicketEvent.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_timeline(self, ticket_id: int) -> list[TicketEvent]:
        """
        Status transitions only — the ticket timeline.
        Filters event_type = STATUS_CHANGED, ordered chronologically.
        """
        result = await self.db.execute(
            select(TicketEvent)
            .where(
                TicketEvent.ticket_id == ticket_id,
                TicketEvent.event_type == EventType.STATUS_CHANGED,
            )
            .order_by(TicketEvent.created_at.asc())
        )
        return list(result.scalars().all())