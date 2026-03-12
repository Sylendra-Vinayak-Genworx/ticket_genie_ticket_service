from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.clients.postgres_client import get_db
from src.data.repositories.customer_tier_repository import CustomerTierRepository
from src.schemas.tier_schema import CustomerTierResponse

router = APIRouter(prefix="/tiers", tags=["tiers"])

@router.get("", response_model=list[CustomerTierResponse])
async def list_tiers(db: AsyncSession = Depends(get_db)):
    """List all available customer tiers."""
    repo = CustomerTierRepository(db)
    return await repo.list_all()
