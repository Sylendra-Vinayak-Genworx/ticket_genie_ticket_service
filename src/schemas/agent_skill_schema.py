from pydantic import BaseModel, ConfigDict
from typing import List

class AgentSkillBase(BaseModel):
    area_id: int
    proficiency_level: str = "intermediate"

class AgentSkillResponse(AgentSkillBase):
    area_name: str
    
    model_config = ConfigDict(from_attributes=True)

class AgentSkillUpdateRequest(BaseModel):
    skills: List[AgentSkillBase]

class AgentSkillListResponse(BaseModel):
    skills: List[AgentSkillResponse]
