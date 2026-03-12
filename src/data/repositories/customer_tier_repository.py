from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.customer_tier import CustomerTier

class CustomerTierRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[CustomerTier]:
        result = await self.db.execute(select(CustomerTier).order_by(CustomerTier.tier_id))
        return list(result.scalars().all())
