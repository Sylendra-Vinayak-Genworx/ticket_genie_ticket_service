from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from sqlalchemy.orm import selectinload
from src.data.models.postgres.agent_skill import AgentSkill
from src.data.models.postgres.area_of_concern import AreaOfConcern


class AgentSkillRepository:

    def __init__(self, db: AsyncSession):
        self.db = db
    """Repository for managing agent skills. Provides methods to retrieve, update, and delete agent skills based on user ID. Also includes methods to check for existing areas of concern and to bulk create new agent skill records. The repository interacts with the database using SQLAlchemy's AsyncSession and is designed to be used by the AgentSkillService for business logic related to agent skill management."""
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
        await self.db.flush()

    async def _reset_sequence(self) -> None:
        """Reset the agent_skills primary key sequence to avoid duplicate key errors."""
        await self.db.execute(
            text("SELECT setval('agent_skills_agent_skill_id_seq', COALESCE((SELECT MAX(agent_skill_id) FROM agent_skills), 0))")
        )

    async def bulk_create(self, user_id: str, skills_data: list[dict]) -> None:
        await self._reset_sequence()
        for skill_data in skills_data:
            self.db.add(AgentSkill(
                user_id=user_id,
                area_id=skill_data["area_id"],
                proficiency_level=skill_data["proficiency_level"]
            ))

    async def commit(self) -> None:
        await self.db.commit()