from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.area_of_concern import AreaOfConcern
from src.data.repositories.area_of_concern_repository import AreaOfConcernRepository


class AreaOfConcernService:

    def __init__(self, session: AsyncSession) -> None:
        self._repo = AreaOfConcernRepository(session)

    async def list_areas(self) -> list[AreaOfConcern]:
        return await self._repo.get_all()