"""Schemas for agent profile synchronization from Auth Service."""

from typing import Optional

from pydantic import BaseModel


class AgentProfileSyncRequest(BaseModel):
    """Request body to sync/create agent profile from Auth Service."""

    user_id: str
    display_name: str
    is_available: bool = True
    customer_tier_id: Optional[int] = None
    max_open_tickets: int = 10


class AgentProfileResponse(BaseModel):
    """Response after syncing agent profile."""

    agent_profile_id: int
    user_id: str
    display_name: str
    is_available: bool
    customer_tier_id: Optional[int]
    max_open_tickets: int

    class Config:
        from_attributes = True
