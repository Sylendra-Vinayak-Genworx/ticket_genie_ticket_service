from fastapi import HTTPException
from src.data.repositories.agent_skill_repository import AgentSkillRepository
from src.schemas.agent_skill_schema import AgentSkillListResponse, AgentSkillUpdateRequest


class AgentSkillService:
    def __init__(self, repo: AgentSkillRepository):
        self.repo = repo

    def _format_skills(self, skills) -> list[dict]:
        return [
            {
                "area_id": skill.area_id,
                "area_name": skill.area.name,
                "proficiency_level": skill.proficiency_level,
            }
            for skill in skills
        ]

    async def get_skills(self, user_id: str) -> AgentSkillListResponse:
        skills = await self.repo.get_by_user_id(user_id)
        return AgentSkillListResponse(skills=self._format_skills(skills))

    async def update_skills(self, user_id: str, payload: AgentSkillUpdateRequest) -> AgentSkillListResponse:
        area_ids = [skill.area_id for skill in payload.skills]

        if area_ids:
            existing_area_ids = await self.repo.get_existing_area_ids(area_ids)
            missing_areas = set(area_ids) - existing_area_ids
            if missing_areas:
                raise HTTPException(status_code=400, detail=f"Invalid area_ids: {missing_areas}")

        await self.repo.delete_by_user_id(user_id)
        await self.repo.bulk_create(
            user_id,
            [{"area_id": s.area_id, "proficiency_level": s.proficiency_level} for s in payload.skills]
        )
        await self.repo.commit()

        skills = await self.repo.get_by_user_id(user_id)
        return AgentSkillListResponse(skills=self._format_skills(skills))