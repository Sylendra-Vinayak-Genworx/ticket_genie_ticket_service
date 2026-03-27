from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.area_of_concern import AreaOfConcern
from src.data.repositories.area_of_concern_repository import AreaOfConcernRepository


class AreaOfConcernService:
    '''Service layer for managing areas of concern. Provides methods to list all areas of concern, which are used to categorize tickets based on their issue type or domain. The service interacts with the AreaOfConcernRepository to perform database operations and can include additional business logic related to area management in the future.'''
    def __init__(self, session: AsyncSession) -> None:
        """
          init  .
        
        Args:
            session (AsyncSession): Input parameter.
        """
        self._repo = AreaOfConcernRepository(session)

    async def list_areas(self) -> list[AreaOfConcern]:
        """
        List areas.
        
        Returns:
            list[AreaOfConcern]: The expected output.
        """
        return await self._repo.get_all()