from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.area_of_concern import AreaOfConcern


class AreaOfConcernRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[AreaOfConcern]:
        result = await self._session.execute(
            select(AreaOfConcern).order_by(AreaOfConcern.name)
        )
        return list(result.scalars().all())