"""Service for agent profile management and synchronization."""

from typing import Optional

from src.data.clients.postgres_client import AsyncSessionFactory
from src.data.repositories.agent_repository import AgentRepository
from src.schemas.agent_schema import AgentProfileSyncRequest


class AgentService:
    """Handles agent profile operations including sync from Auth Service."""

    async def sync_agent_profile(self, payload: AgentProfileSyncRequest):
        """
        Sync/create/update agent profile from Auth Service.
        """
        async with AsyncSessionFactory() as session:
            repo = AgentRepository(session)
            profile = await repo.sync_agent_profile(payload)
            await session.commit()
            return profile

    async def update_agent_availability(
        self, user_id: str, is_available: bool
    ) -> Optional:
        """
        Update agent availability status.
        """
        async with AsyncSessionFactory() as session:
            repo = AgentRepository(session)
            profile = await repo.update_availability(user_id, is_available)
            if profile:
                await session.commit()
            return profile
