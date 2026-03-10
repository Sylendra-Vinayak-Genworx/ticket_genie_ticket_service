
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.auth_client import auth_client
from src.data.repositories.ticket_assignment_repositoty import AgentStats, TicketAssignmentRepository
from src.core.services.ticket_service import TicketService
from src.schemas.ticket_schema import TicketAssignRequest

logger = logging.getLogger(__name__)

SYSTEM_ASSIGNER_ID: str = "SYSTEM"
SYSTEM_ASSIGNER_ROLE: str = "admin"


@dataclass(frozen=True)
class AssignmentResult:
    ticket_id: int
    assigned_to: str | None      
    strategy: str               
    score: float | None = None


class AutoAssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = TicketAssignmentRepository(session)
        self._ticket_svc = TicketService(session, auth_client)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def assign(self, ticket_id: int, area_of_concern: str | None) -> AssignmentResult:
        if area_of_concern:
            result = await self._assign_by_area(ticket_id, area_of_concern)
            if result.assigned_to:
                return result

        return await self._assign_least_loaded(ticket_id)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _assign_by_area(self, ticket_id: int, area: str) -> AssignmentResult:
        stats: list[AgentStats] = await self._repo.get_agent_stats_for_area(area)

        if not stats:
            logger.info(
                "No experienced agents for area=%r (ticket_id=%s). Falling back.",
                area, ticket_id,
            )
            return AssignmentResult(ticket_id=ticket_id, assigned_to=None, strategy="experience_score")

        best_agent, best_score = self._pick_best(stats)

        logger.info(
            "Auto-assigning ticket_id=%s to agent=%r via experience_score (score=%.4f, area=%r)",
            ticket_id, best_agent, best_score, area,
        )
        await self._ticket_svc.assign_ticket(
            ticket_id=ticket_id,
            payload=TicketAssignRequest(assignee_id=best_agent),
            current_user_id=SYSTEM_ASSIGNER_ID,
            current_user_role=SYSTEM_ASSIGNER_ROLE,
        )
        return AssignmentResult(
            ticket_id=ticket_id,
            assigned_to=best_agent,
            strategy="experience_score",
            score=best_score,
        )

    async def _assign_least_loaded(self, ticket_id: int) -> AssignmentResult:
        agent_id = await self._repo.get_least_loaded_agent()

        if not agent_id:
            logger.warning(
                "No available agents found for ticket_id=%s. Ticket left unassigned.",
                ticket_id,
            )
            return AssignmentResult(ticket_id=ticket_id, assigned_to=None, strategy="unassigned")

        logger.info(
            "Auto-assigning ticket_id=%s to agent=%r via least_loaded fallback.",
            ticket_id, agent_id,
        )
        await self._ticket_svc.assign_ticket(
            ticket_id=ticket_id,
            payload=TicketAssignRequest(assignee_id=agent_id),
            current_user_id=SYSTEM_ASSIGNER_ID,
            current_user_role=SYSTEM_ASSIGNER_ROLE,
        )
        return AssignmentResult(ticket_id=ticket_id, assigned_to=agent_id, strategy="least_loaded")

    # ------------------------------------------------------------------ #
    # Scoring                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _pick_best(stats: list[AgentStats]) -> tuple[str, float]:
        best_agent = stats[0].assignee_id
        best_score = AutoAssignmentService._score(stats[0])

        for agent in stats[1:]:
            s = AutoAssignmentService._score(agent)
            if s > best_score:
                best_score = s
                best_agent = agent.assignee_id

        return best_agent, best_score

    @staticmethod
    def _score(agent: AgentStats) -> float:
        return agent.experience / (1 + agent.workload)