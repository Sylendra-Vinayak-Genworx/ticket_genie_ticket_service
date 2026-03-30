from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.customer_tier import CustomerTier

"""Repository for managing customer tiers. Provides methods to retrieve all customer tiers from the database. The repository interacts with the database using SQLAlchemy's AsyncSession and is designed to be used by services that need to access customer tier information for business logic related to ticket routing, prioritization, or agent assignment based on customer tier."""


class CustomerTierRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[CustomerTier]:
        """
        List all customer tiers ordered by tier_id.

        Returns:
            list[CustomerTier]: All customer tiers.
        """
        result = await self.db.execute(select(CustomerTier).order_by(CustomerTier.tier_id))
        return list(result.scalars().all())

    async def get_by_id(self, tier_id: int) -> Optional[CustomerTier]:
        """
        Get a customer tier by primary key.

        Args:
            tier_id (int): Tier primary key.

        Returns:
            Optional[CustomerTier]: The tier, or None if not found.
        """
        result = await self.db.execute(
            select(CustomerTier).where(CustomerTier.tier_id == tier_id)
        )
        return result.scalar_one_or_none()
