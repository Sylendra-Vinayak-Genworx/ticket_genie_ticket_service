from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.area_of_concern import AreaOfConcern

"""Repository for managing areas of concern. Provides methods to retrieve all areas of concern from the database. The repository interacts with the database using SQLAlchemy's AsyncSession and is designed to be used by the AgentSkillService for business logic related to agent skill management and area of concern retrieval."""
class AreaOfConcernRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[AreaOfConcern]:
        result = await self._session.execute(
            select(AreaOfConcern).order_by(AreaOfConcern.name)
        )
        return list(result.scalars().all())