from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from src.data.models.postgres.agent_skill import AgentSkill
from src.data.models.postgres.area_of_concern import AreaOfConcern


class AgentSkillRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: str) -> list[AgentSkill]:
        stmt = (
            select(AgentSkill)
            .where(AgentSkill.user_id == user_id)
            .options(selectinload(AgentSkill.area))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_existing_area_ids(self, area_ids: list[str]) -> set[str]:
        stmt = select(AreaOfConcern.area_id).where(AreaOfConcern.area_id.in_(area_ids))
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def delete_by_user_id(self, user_id: str) -> None:
        await self.db.execute(delete(AgentSkill).where(AgentSkill.user_id == user_id))

    async def bulk_create(self, user_id: str, skills_data: list[dict]) -> None:
        for skill_data in skills_data:
            self.db.add(AgentSkill(
                user_id=user_id,
                area_id=skill_data["area_id"],
                proficiency_level=skill_data["proficiency_level"]
            ))

    async def commit(self) -> None:
        await self.db.commit()