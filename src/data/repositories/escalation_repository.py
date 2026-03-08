"""
EscalationHistory repository — manages the ``escalation_history`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.escalation import EscalationHistory


class EscalationRepository:
    """Data-access layer for the ``escalation_history`` table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, escalation: EscalationHistory) -> None:
        """Insert a new escalation record and flush to obtain its ID."""
        self.db.add(escalation)
        await self.db.flush()

    async def get_by_ticket_id(self, ticket_id: int) -> list[EscalationHistory]:
        """Return all escalation records for the given ticket, newest first."""
        result = await self.db.execute(
            select(EscalationHistory)
            .where(EscalationHistory.ticket_id == ticket_id)
            .order_by(EscalationHistory.escalated_at.desc())
        )
        return list(result.scalars().all())
