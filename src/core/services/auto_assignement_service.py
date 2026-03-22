from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.auth_client import AuthServiceClient, UserDTO
from src.data.repositories.ticket_assignment_repositoty import (
    AgentStats,
    TicketAssignmentRepository,
)
from src.core.services.ticket_service import TicketService
from src.schemas.ticket_schema import TicketAssignRequest
from src.constants.enum import UserRole
from src.config.settings import get_settings

logger = logging.getLogger(__name__)

SYSTEM_ASSIGNER_ID: str = "SYSTEM"
SYSTEM_ASSIGNER_ROLE: str = "admin"




PROFICIENCY_WEIGHTS = {
    "expert": 100,
    "intermediate": 50,
    "beginner": 10,
}

EXPERIENCE_WEIGHT = 5        # Points per resolved ticket
WORKLOAD_PENALTY = -10       # Points per active ticket


@dataclass(frozen=True)
class AssignmentResult:
    """Result of an assignment attempt."""
    ticket_id: int
    assigned_to: str | None       # agent user_id, or None if failed
    team_id: str | None           # team the agent belongs to, or None
    strategy: str                 # 'skill_based', 'least_loaded', 'no_agents'
    score: float | None = None    # Score used for selection (if applicable)
    reason: str | None = None     # Human-readable explanation


class AutoAssignmentService:
    """Service for intelligent ticket assignment."""

    def __init__(
        self, 
        session: AsyncSession,
        auth_client: AuthServiceClient,
    ) -> None:
        self._session = session
        self._repo = TicketAssignmentRepository(session)
        self._ticket_svc = TicketService(session, auth_client)
        self._auth = auth_client

    async def assign(
        self, 
        ticket_id: int, 
        area_id: int | None,
    ) -> AssignmentResult:
        """
        Intelligently assign a ticket to the best available agent.

        Assignment Strategy
        -------------------
        1. If area_id provided → try skill-based assignment
        2. Fall back to least-loaded agent
        3. If no agents available → return None (caller handles fallback to lead)

        Parameters
        ----------
        ticket_id : int
            ID of ticket to assign
        area_id : int | None
            Area of concern ID for skill matching (can be None)

        Returns
        -------
        AssignmentResult
            Contains assigned agent (or None), team, strategy used, and score

        Notes
        -----
        - NEVER assigns to leads (they're filtered out in _get_active_agents)
        - NEVER assigns to inactive agents
        - Prevents race conditions via atomic lock
        """
        # ── Step 0: Acquire assignment lock ────────────────────────────────
        lock_acquired = await self._repo.try_acquire_assignment_lock(ticket_id)
        if not lock_acquired:
            logger.info(
                "[ticket=%s] Assignment already in progress, skipping",
                ticket_id,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="already_assigned",
                reason="Another worker is assigning this ticket",
            )

        # ── Step 1: Fetch active agents from Auth Service ─────────────────
        try:
            active_agents = await self._get_active_agents()
        except Exception as exc:
            logger.exception(
                "[ticket=%s] Failed to fetch active agents from Auth Service",
                ticket_id,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="auth_service_error",
                reason=f"Auth Service unavailable: {exc}",
            )

        if not active_agents:
            logger.warning(
                "[ticket=%s] No active agents available in the system",
                ticket_id,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="no_agents",
                reason="No active agents in system",
            )

        # ── Step 2: Try skill-based assignment ────────────────────────────
        if area_id is not None:
            result = await self._assign_by_skill(
                ticket_id=ticket_id,
                area_id=area_id,
                active_agents=active_agents,
            )
            if result.assigned_to:
                return result

        # ── Step 3: Fall back to least-loaded agent ───────────────────────
        return await self._assign_least_loaded(
            ticket_id=ticket_id,
            active_agents=active_agents,
        )

    # ────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ────────────────────────────────────────────────────────────────────

    async def _get_active_agents(self) -> list[UserDTO]:
        """
        Fetch all ACTIVE AGENTS from Auth Service.

        Returns
        -------
        list[UserDTO]
            List of active users with role='support_agent'

        Notes
        -----
        - Filters out leads and admins
        - Filters out inactive users (is_active=False)
        """
        all_users = await self._auth.get_all_users()

        return [
            user for user in all_users
            if user.role in (UserRole.AGENT.value, "support_agent")
            and user.is_active
        ]

    async def _assign_by_skill(
        self,
        ticket_id: int,
        area_id: int,
        active_agents: list[UserDTO],
    ) -> AssignmentResult:
        """
        Assign based on agent skills for the given area.

        Scoring Algorithm
        -----------------
        score = proficiency_weight + (experience * 5) - (workload * 10)

        Where:
        - proficiency_weight: expert=100, intermediate=50, beginner=10
        - experience: number of tickets resolved in this area
        - workload: current active tickets

        Returns
        -------
        AssignmentResult
            With assigned_to populated if skill match found, else None
        """
        active_agent_ids = [user.id for user in active_agents]
        agent_map = {user.id: user for user in active_agents}

        # Fetch agents with skills for this area
        stats: list[AgentStats] = await self._repo.get_agents_for_area(
            area_id=area_id,
            active_agent_ids=active_agent_ids,
        )

        if not stats:
            logger.info(
                "[ticket=%s] No agents have skills for area_id=%s",
                ticket_id,
                area_id,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="skill_based",
                reason=f"No agents skilled in area {area_id}",
            )

        # Enrich with team_id from Auth Service
        enriched_stats = []
        for stat in stats:
            user = agent_map.get(stat.user_id)
            if user:
                enriched_stats.append(
                    AgentStats(
                        user_id=stat.user_id,
                        team_id=user.team_id,
                        proficiency_level=stat.proficiency_level,
                        tickets_resolved=stat.tickets_resolved,
                        current_workload=stat.current_workload,
                    )
                )

        if not enriched_stats:
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="skill_based",
                reason="Skilled agents not found in active users",
            )

        # ── Fix 3: Hard workload cap — exclude overloaded agents before scoring ─
        settings = get_settings()
        eligible_stats = [
            a for a in enriched_stats
            if a.current_workload < settings.MAX_AGENT_WORKLOAD
        ]
        if not eligible_stats:
            logger.info(
                "[ticket=%s] All skilled agents at or above MAX_AGENT_WORKLOAD=%d — "
                "falling through to least-loaded fallback",
                ticket_id, settings.MAX_AGENT_WORKLOAD,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="skill_based",
                reason=f"All skilled agents at workload cap ({settings.MAX_AGENT_WORKLOAD})",
            )

        # ── Fix 6: Fair tiebreaking ───────────────────────────────────────────
        # Find all agents sharing the maximum score, then pick the one with the
        # lowest workload among them.  If still tied, pick randomly.
        import random
        max_score = max(self._calculate_score(a) for a in eligible_stats)
        top_agents = [a for a in eligible_stats if self._calculate_score(a) == max_score]
        min_workload = min(a.current_workload for a in top_agents)
        least_loaded_top = [a for a in top_agents if a.current_workload == min_workload]
        best = random.choice(least_loaded_top)
        best_score = max_score

        logger.info(
            "[ticket=%s] Skill-based assignment: agent=%s team=%s score=%.2f "
            "(proficiency=%s, experience=%d, workload=%d)",
            ticket_id,
            best.user_id,
            best.team_id,
            best_score,
            best.proficiency_level,
            best.tickets_resolved,
            best.current_workload,
        )

        # Execute assignment
        await self._ticket_svc.assign_ticket(
            ticket_id=ticket_id,
            payload=TicketAssignRequest(assignee_id=best.user_id),
            current_user_id=SYSTEM_ASSIGNER_ID,
            current_user_role=SYSTEM_ASSIGNER_ROLE,
            team_id=best.team_id,
        )

        return AssignmentResult(
            ticket_id=ticket_id,
            assigned_to=best.user_id,
            team_id=best.team_id,
            strategy="skill_based",
            score=best_score,
            reason=(
                f"Best skill match: {best.proficiency_level} proficiency, "
                f"{best.tickets_resolved} tickets resolved, "
                f"{best.current_workload} current workload"
            ),
        )

    async def _assign_least_loaded(
        self,
        ticket_id: int,
        active_agents: list[UserDTO],
    ) -> AssignmentResult:
        """
        Assign to agent with least workload (no skill consideration).

        Returns
        -------
        AssignmentResult
            With assigned_to populated if any agent available, else None
        """
        active_agent_ids = [user.id for user in active_agents]
        agent_map = {user.id: user for user in active_agents}

        agent_id = await self._repo.get_least_loaded_agent(active_agent_ids)

        if not agent_id:
            logger.warning(
                "[ticket=%s] No agent found for least-loaded assignment",
                ticket_id,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="least_loaded",
                reason="No agents available",
            )

        user = agent_map.get(agent_id)
        if not user:
            logger.error(
                "[ticket=%s] Least-loaded agent %s not in active users map",
                ticket_id,
                agent_id,
            )
            return AssignmentResult(
                ticket_id=ticket_id,
                assigned_to=None,
                team_id=None,
                strategy="least_loaded",
                reason="Selected agent not found in active users",
            )

        workload = await self._repo.get_agent_workload(agent_id)

        logger.info(
            "[ticket=%s] Least-loaded assignment: agent=%s team=%s workload=%d",
            ticket_id,
            agent_id,
            user.team_id,
            workload,
        )

        # Execute assignment
        await self._ticket_svc.assign_ticket(
            ticket_id=ticket_id,
            payload=TicketAssignRequest(assignee_id=agent_id),
            current_user_id=SYSTEM_ASSIGNER_ID,
            current_user_role=SYSTEM_ASSIGNER_ROLE,
            team_id=user.team_id,
        )

        return AssignmentResult(
            ticket_id=ticket_id,
            assigned_to=agent_id,
            team_id=user.team_id,
            strategy="least_loaded",
            reason=f"Least loaded agent with {workload} active tickets",
        )

    # ────────────────────────────────────────────────────────────────────
    # SCORING
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _calculate_score(agent: AgentStats) -> float:
        """
        Calculate assignment score for an agent.

        Formula
        -------
        score = proficiency_weight + (experience * 5) - (workload * 10)

        Higher score = better match

        Notes
        -----
        proficiency_level is normalised to lowercase before lookup so values
        stored as 'ADVANCED', 'Expert', 'INTERMEDIATE' etc. all resolve correctly.
        'advanced' is treated as a synonym for 'expert' (both map to 100).
        Unknown levels fall back to 0 (treated as unranked).
        """
        # Normalise: lowercase + treat 'advanced' as synonym for 'expert'
        level = agent.proficiency_level.lower().strip()
        if level == "advanced":
            level = "expert"

        proficiency_weight = PROFICIENCY_WEIGHTS.get(level, 0)

        if proficiency_weight == 0 and level not in PROFICIENCY_WEIGHTS:
            logger.warning(
                "Unknown proficiency level %r for agent %s — scoring as 0. "
                "Expected one of: %s",
                agent.proficiency_level, agent.user_id, list(PROFICIENCY_WEIGHTS.keys()),
            )

        # Cap experience to prevent runaway dominance over proficiency.
        # Max contribution is EXPERIENCE_CAP * EXPERIENCE_WEIGHT = 50 * 5 = +250
        settings = get_settings()
        capped_experience = min(agent.tickets_resolved, settings.EXPERIENCE_CAP)

        score = (
            proficiency_weight
            + (capped_experience * EXPERIENCE_WEIGHT)
            + (agent.current_workload * WORKLOAD_PENALTY)
        )

        return score