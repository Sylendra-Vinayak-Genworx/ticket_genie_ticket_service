from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db
from src.core.services.area_of_concern_service import AreaOfConcernService

router = APIRouter(prefix="/areas-of-concern", tags=["areas-of-concern"])


class AreaOfConcernResponse(BaseModel):
    area_id: int
    name: str

    model_config = {"from_attributes": True}


def _svc(session: AsyncSession = Depends(get_db)) -> AreaOfConcernService:
    return AreaOfConcernService(session)


@router.get("", response_model=list[AreaOfConcernResponse])
async def list_areas_of_concern(
    svc: AreaOfConcernService = Depends(_svc),
) -> list[AreaOfConcernResponse]:
    """Return all areas of concern for ticket creation dropdowns."""
    return await svc.list_areas()