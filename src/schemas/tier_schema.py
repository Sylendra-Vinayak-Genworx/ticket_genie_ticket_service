from typing import Optional
from pydantic import BaseModel, ConfigDict

class CustomerTierResponse(BaseModel):
    tier_id: int
    name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
