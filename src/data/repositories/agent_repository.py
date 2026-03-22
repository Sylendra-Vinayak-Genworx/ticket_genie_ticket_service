

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import UserRole
from src.data.models.postgres.agent_profile import AgentProfile
from src.schemas.agent_schema import AgentProfileSyncRequest

"""keept for backward compatibility, we are not using this."""
class AgentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_user_id(self, user_id: str) -> Optional[AgentProfile]:
        result = await self.db.execute(
            select(AgentProfile).where(AgentProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_available_agents(self) -> list[AgentProfile]:
        """
        Returns all AgentProfiles that are currently available for assignment.
        """
        result = await self.db.execute(
            select(AgentProfile).where(AgentProfile.is_available == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_available_agent_ids(self) -> set[str]:
        """
        Returns a set of ``user_id`` strings for all currently-available agents.

        Lighter than ``get_available_agents()`` — only fetches the user_id
        column, which is all the similarity-routing path needs for an
        availability cross-check.
        """
        result = await self.db.execute(
            select(AgentProfile.user_id).where(AgentProfile.is_available == True)  # noqa: E712
        )
        return {row[0] for row in result.fetchall()}

    async def get_available_leads(self) -> list[AgentProfile]:
        """
        Returns AgentProfiles whose Auth Service role is LEAD.
        Because role lives in Auth Service, we maintain a local role_cache column.
        For now we return all available agents and let the caller filter.
        """
        result = await self.db.execute(
            select(AgentProfile).where(AgentProfile.is_available == True)
        )
        return list(result.scalars().all())

    async def get_lead_agent(self) -> Optional[AgentProfile]:
        """
        Return the first available team-lead profile.
        Convention: the lead has display_name containing 'Lead' or is
        explicitly flagged.  For now we pick the agent with the lowest
        user_id among available agents whose display_name contains 'Lead'.
        Falls back to any available agent if no lead found.
        """
        result = await self.db.execute(
            select(AgentProfile)
            .where(
                AgentProfile.is_available == True,  
                AgentProfile.display_name.ilike("%lead%"),
            )
            .order_by(AgentProfile.user_id)
            .limit(1)
        )
        lead = result.scalar_one_or_none()
        if lead:
            return lead

        result = await self.db.execute(
            select(AgentProfile)
            .where(AgentProfile.is_available == True) 
            .order_by(AgentProfile.user_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def sync_agent_profile(self, payload: AgentProfileSyncRequest) -> AgentProfile:
        """
        Create or update an agent profile from Auth Service sync.
        Used when agents are created/updated in the Auth Service.
        """
        existing = await self.get_by_user_id(payload.user_id)
        
        if existing:
            # Update existing profile
            existing.display_name = payload.display_name
            existing.is_available = payload.is_available
            existing.customer_tier_id = payload.customer_tier_id
            existing.max_open_tickets = payload.max_open_tickets
            self.db.add(existing)
            await self.db.flush()
            return existing
        
        # Create new profile
        new_profile = AgentProfile(
            user_id=payload.user_id,
            display_name=payload.display_name,
            is_available=payload.is_available,
            customer_tier_id=payload.customer_tier_id,
            max_open_tickets=payload.max_open_tickets,
        )
        self.db.add(new_profile)
        await self.db.flush()
        return new_profile

    async def update_availability(self, user_id: str, is_available: bool) -> Optional[AgentProfile]:
        """
        Update an agent's availability status.
        Used when agents go online/offline.
        """
        profile = await self.get_by_user_id(user_id)
        if profile:
            profile.is_available = is_available
            self.db.add(profile)
            await self.db.flush()
        return profile