"""
SLARule repository — manages the ``sla_rules`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import Priority, Severity
from src.data.models.postgres.sla import SLARule


class SLARuleRepository:
    """Data-access layer for the ``sla_rules`` table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── READ ─────────────────────────────────────────────────────────────────

    async def get_rule(
        self,
        sla_id: int,
        severity: Severity,
        priority: Priority,
    ) -> Optional[SLARule]:
        """Look up a single SLA rule by (sla_id, severity, priority)."""
        result = await self.db.execute(
            select(SLARule).where(
                SLARule.sla_id == sla_id,
                SLARule.severity == severity,
                SLARule.priority == priority,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, rule_id: int) -> Optional[SLARule]:
        result = await self.db.execute(
            select(SLARule).where(SLARule.rule_id == rule_id)
        )
        return result.scalar_one_or_none()

    async def list_by_sla(self, sla_id: int) -> list[SLARule]:
        result = await self.db.execute(
            select(SLARule)
            .where(SLARule.sla_id == sla_id)
            .order_by(SLARule.rule_id)
        )
        return list(result.scalars().all())

    # ── WRITE ────────────────────────────────────────────────────────────────

    async def create(self, rule: SLARule) -> SLARule:
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def save(self, rule: SLARule) -> SLARule:
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def delete(self, rule: SLARule) -> None:
        await self.db.delete(rule)
        await self.db.flush()
