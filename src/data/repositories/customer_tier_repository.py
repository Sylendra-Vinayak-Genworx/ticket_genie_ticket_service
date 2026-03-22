from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.customer_tier import CustomerTier
"""Repository for managing customer tiers. Provides methods to retrieve all customer tiers from the database. The repository interacts with the database using SQLAlchemy's AsyncSession and is designed to be used by services that need to access customer tier information for business logic related to ticket routing, prioritization, or agent assignment based on customer tier."""
class CustomerTierRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[CustomerTier]:
        result = await self.db.execute(select(CustomerTier).order_by(CustomerTier.tier_id))
        return list(result.scalars().all())
