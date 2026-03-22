from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.clients.postgres_client import get_db
from src.data.repositories.agent_skill_repository import AgentSkillRepository
from src.core.services.agent_skill_service import AgentSkillService
from src.schemas.agent_skill_schema import AgentSkillListResponse, AgentSkillUpdateRequest

router = APIRouter()


def get_service(db: AsyncSession = Depends(get_db)) -> AgentSkillService:
    return AgentSkillService(AgentSkillRepository(db))

""""get the agent's skills """
@router.get("/admin/users/{user_id}/skills", response_model=AgentSkillListResponse)
async def get_agent_skills(user_id: str, service: AgentSkillService = Depends(get_service)):
    return await service.get_skills(user_id)

"""update the agent's skills."""
@router.put("/admin/users/{user_id}/skills", response_model=AgentSkillListResponse)
async def update_agent_skills(user_id: str, payload: AgentSkillUpdateRequest, service: AgentSkillService = Depends(get_service)):
    return await service.update_skills(user_id, payload)