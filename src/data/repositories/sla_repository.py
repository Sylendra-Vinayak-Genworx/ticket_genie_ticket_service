"""
SLA repository — manages the ``slas`` table ONLY.

This repository must NOT query or mutate any other table.
Cross-table orchestration belongs in the service layer.
"""

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.data.models.postgres.sla import SLA


class SLARepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── READ ─────────────────────────────────────────────────────────────────

    async def get_active_sla_for_tier(self, customer_tier_id: int) -> Optional[SLA]:
        result = await self.db.execute(
            select(SLA)
            .where(
                SLA.customer_tier_id == customer_tier_id,
                SLA.is_active == True,
            )
            .options(selectinload(SLA.rules))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_sla_by_id(self, sla_id: int) -> Optional[SLA]:
        result = await self.db.execute(
            select(SLA)
            .where(SLA.sla_id == sla_id)
            .options(selectinload(SLA.rules))
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        is_active: Optional[bool] = None,
        customer_tier_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[SLA]]:
        stmt = select(SLA).options(selectinload(SLA.rules))
        if is_active is not None:
            stmt = stmt.where(SLA.is_active == is_active)
        if customer_tier_id is not None:
            stmt = stmt.where(SLA.customer_tier_id == customer_tier_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(
                select(SLA.sla_id).where(
                    *([SLA.is_active == is_active] if is_active is not None else []),
                    *([SLA.customer_tier_id == customer_tier_id] if customer_tier_id is not None else []),
                ).subquery()
            )
        )
        total = count_result.scalar_one()

        stmt = stmt.order_by(SLA.sla_id)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return total, list(result.unique().scalars().all())

    # ── WRITE ────────────────────────────────────────────────────────────────

    async def create(self, sla: SLA) -> SLA:
        self.db.add(sla)
        await self.db.flush()
        return sla

    async def save(self, sla: SLA) -> SLA:
        self.db.add(sla)
        await self.db.flush()
        return sla

    async def delete(self, sla: SLA) -> None:
        await self.db.delete(sla)
        await self.db.flush()