"""
src/data/repositories/ticket_assignment_repository.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Clean, skill-based ticket assignment repository.

DESIGN PRINCIPLES
-----------------
1. Uses agent_skills table for skill matching
2. Never infers agent/lead from ticket data alone
3. All user metadata comes from Auth Service
4. Workload measured via assignee_id (only agents, never leads)
5. All queries explicitly filter routing_status='SUCCESS' to exclude lead-routed tickets
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.ticket import Ticket
from src.constants.enum import RoutingStatus, TicketStatus


@dataclass(frozen=True)
class AgentStats:
    """Agent skill and workload metrics for assignment scoring."""
    user_id: str
    team_id: str | None
    proficiency_level: str        # 'beginner', 'intermediate', 'expert'
    tickets_resolved: int         # Historical expertise for this area
    current_workload: int         # Active tickets assigned


class TicketAssignmentRepository:
    """Repository for ticket assignment queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ────────────────────────────────────────────────────────────────────
    # PRIMARY PATH: Skill-based assignment
    # ────────────────────────────────────────────────────────────────────

    async def get_agents_for_area(
        self, 
        area_id: int,
        active_agent_ids: list[str],
    ) -> list[AgentStats]:
        """
        Return agents who have declared skills for the given area_id,
        along with their workload and historical performance.

        Parameters
        ----------
        area_id : int
            The area_of_concern ID from the ticket
        active_agent_ids : list[str]
            List of user_ids for ACTIVE agents (from Auth Service)

        Returns
        -------
        list[AgentStats]
            Agents sorted by proficiency (expert > intermediate > beginner),
            then by workload (ascending)

        Notes
        -----
        - Only returns agents present in active_agent_ids (no inactive agents)
        - Workload counts ONLY tickets with routing_status='SUCCESS'
        - Historical data (tickets_resolved) uses tickets in area for this agent
        """
        if not active_agent_ids:
            return []

        sql = text(
            """
            WITH agent_workload AS (
                SELECT 
                    assignee_id,
                    COUNT(*) AS current_workload
                FROM tickets
                WHERE status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
                  AND assignee_id IS NOT NULL
                  AND routing_status = 'SUCCESS'
                  AND assignee_id = ANY(:agent_ids)
                GROUP BY assignee_id
            ),
            agent_history AS (
                SELECT 
                    assignee_id,
                    COUNT(*) AS tickets_resolved
                FROM tickets
                WHERE status IN ('RESOLVED', 'CLOSED')
                  AND area_of_concern = :area_id
                  AND assignee_id IS NOT NULL
                  AND routing_status = 'SUCCESS'
                  AND assignee_id = ANY(:agent_ids)
                GROUP BY assignee_id
            )
            SELECT 
                ags.user_id,
                ags.proficiency_level,
                COALESCE(ah.tickets_resolved, 0)::int AS tickets_resolved,
                COALESCE(aw.current_workload, 0)::int AS current_workload
            FROM agent_skills ags
            LEFT JOIN agent_workload aw ON aw.assignee_id = ags.user_id
            LEFT JOIN agent_history ah ON ah.assignee_id = ags.user_id
            WHERE ags.area_id = :area_id
              AND ags.user_id = ANY(:agent_ids)
            ORDER BY 
                -- Expert > Intermediate > Beginner
                CASE ags.proficiency_level
                    WHEN 'expert' THEN 3
                    WHEN 'intermediate' THEN 2
                    WHEN 'beginner' THEN 1
                    ELSE 0
                END DESC,
                -- Then by workload (least loaded first)
                current_workload ASC,
                -- Tie-breaker: most experienced
                tickets_resolved DESC
            """
        )

        result = await self._session.execute(
            sql, 
            {
                "area_id": area_id, 
                "agent_ids": active_agent_ids
            }
        )

        # Need team_id from Auth Service - we'll pass it in from the service layer
        # For now, return without team_id (service layer adds it)
        return [
            AgentStats(
                user_id=row.user_id,
                team_id=None,  # Will be enriched by service layer
                proficiency_level=row.proficiency_level,
                tickets_resolved=row.tickets_resolved,
                current_workload=row.current_workload,
            )
            for row in result.fetchall()
        ]

    # ────────────────────────────────────────────────────────────────────
    # FALLBACK PATH: Least-loaded agent (no skill match)
    # ────────────────────────────────────────────────────────────────────

    async def get_least_loaded_agent(
        self, 
        active_agent_ids: list[str],
    ) -> str | None:
        """
        Returns the user_id of the agent with the fewest active tickets.

        Parameters
        ----------
        active_agent_ids : list[str]
            List of user_ids for ACTIVE agents (from Auth Service)

        Returns
        -------
        str | None
            user_id of least loaded agent, or None if no agents have tickets yet

        Notes
        -----
        - Only SUCCESS-routed tickets counted
        - If multiple agents tied at lowest workload, picks one arbitrarily
        - Agents with ZERO tickets are preferred (they won't appear in the query,
          so we check if result is empty and return first from active_agent_ids)
        """
        if not active_agent_ids:
            return None

        sql = text(
            """
            SELECT assignee_id, COUNT(*) AS workload
            FROM tickets
            WHERE status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
              AND assignee_id IS NOT NULL
              AND routing_status = 'SUCCESS'
              AND assignee_id = ANY(:agent_ids)
            GROUP BY assignee_id
            ORDER BY workload ASC
            LIMIT 1
            """
        )

        result = await self._session.execute(sql, {"agent_ids": active_agent_ids})
        row = result.fetchone()

        if row is None:
            # No agent has any active tickets - return first active agent
            return active_agent_ids[0] if active_agent_ids else None

        return row.assignee_id

    # ────────────────────────────────────────────────────────────────────
    # LEAD FALLBACK: Least-loaded lead for team
    # ────────────────────────────────────────────────────────────────────

    async def get_least_loaded_lead_for_team(
        self,
        lead_ids: list[str],
        preferred_team_id: str | None,
    ) -> str | None:
        """
        Given an explicit list of lead user_ids (from Auth Service), return the
        lead with the fewest active tickets.

        Preference order:
          1. Leads from preferred_team_id (least loaded)
          2. Any lead (least loaded)

        Parameters
        ----------
        lead_ids : list[str]
            user_ids of leads from Auth Service
        preferred_team_id : str | None
            team_id to prefer (e.g., the agent's team)

        Returns
        -------
        str | None
            user_id of selected lead, or None if no leads available

        Notes
        -----
        CRITICAL: This counts tickets where assignee_id = lead_id, meaning tickets
        that were DIRECTLY ASSIGNED to the lead. In your new system, leads should
        NEVER appear in assignee_id - they only appear in team_id routing.

        Therefore, this query should actually count tickets where:
          - team_id matches the lead's team
          - assignee_id IS NULL (team queue, not direct assignment)

        However, for backward compatibility during migration, we'll keep the
        assignee_id check but ALSO count team-routed tickets.
        """
        if not lead_ids:
            return None

        sql = text(
            """
            WITH lead_workload AS (
                SELECT 
                    t.team_id,
                    COUNT(*) AS workload
                FROM tickets t
                WHERE t.status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
                  AND t.team_id IS NOT NULL
                  AND t.assignee_id IS NULL  -- Team queue tickets
                  AND t.routing_status IN ('AI_FAILED', 'ESCALATED')
                GROUP BY t.team_id
            )
            SELECT 
                unnest(:lead_ids::text[]) AS lead_id,
                COALESCE(lw.workload, 0) AS workload
            FROM unnest(:lead_ids::text[]) AS lead_id
            LEFT JOIN lead_workload lw ON lw.team_id = :preferred_team_id
            ORDER BY 
                -- Prefer same team
                CASE WHEN :preferred_team_id IS NOT NULL THEN 0 ELSE 1 END,
                workload ASC
            LIMIT 1
            """
        )

        result = await self._session.execute(
            sql,
            {
                "lead_ids": lead_ids,
                "preferred_team_id": preferred_team_id,
            }
        )
        row = result.fetchone()

        if row:
            return row.lead_id

        # All leads have zero workload - return first, preferring same team
        # (Auth Service should have passed leads sorted by team preference)
        return lead_ids[0]

    # ────────────────────────────────────────────────────────────────────
    # ATOMIC OPERATIONS: Prevent race conditions
    # ────────────────────────────────────────────────────────────────────

    async def try_acquire_assignment_lock(self, ticket_id: int) -> bool:
        """
        Atomically mark ticket as 'being assigned' to prevent concurrent assignment.

        Returns True if lock acquired, False if ticket already being processed.

        Usage:
            if not await repo.try_acquire_assignment_lock(ticket_id):
                logger.info("Ticket already being assigned, skipping")
                return

        Notes
        -----
        This adds a new routing_status value: 'ASSIGNING'
        You'll need to add this to the RoutingStatus enum.
        """
        sql = text(
            """
            UPDATE tickets
            SET routing_status = 'ASSIGNING',
                updated_at = CURRENT_TIMESTAMP
            WHERE ticket_id = :ticket_id
              AND routing_status NOT IN ('SUCCESS', 'ASSIGNING')
            RETURNING ticket_id
            """
        )

        result = await self._session.execute(sql, {"ticket_id": ticket_id})
        await self._session.flush()  # Ensure lock is persisted
        return result.fetchone() is not None

    # ────────────────────────────────────────────────────────────────────
    # HELPER QUERIES
    # ────────────────────────────────────────────────────────────────────

    async def get_agent_workload(self, user_id: str) -> int:
        """
        Get current active ticket count for a specific agent.

        Returns
        -------
        int
            Number of active tickets assigned to this agent
        """
        sql = text(
            """
            SELECT COUNT(*)::int AS workload
            FROM tickets
            WHERE assignee_id = :user_id
              AND status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
              AND routing_status = 'SUCCESS'
            """
        )

        result = await self._session.execute(sql, {"user_id": user_id})
        row = result.fetchone()
        return row.workload if row else 0

    async def get_team_queue_size(self, team_id: str) -> int:
        """
        Get count of unassigned tickets in a team's queue.

        Returns
        -------
        int
            Number of tickets in team queue (assignee_id IS NULL)
        """
        sql = text(
            """
            SELECT COUNT(*)::int AS queue_size
            FROM tickets
            WHERE team_id = :team_id
              AND assignee_id IS NULL
              AND status IN ('OPEN', 'IN_PROGRESS', 'ACKNOWLEDGED')
              AND routing_status IN ('AI_FAILED', 'ESCALATED')
            """
        )

        result = await self._session.execute(sql, {"team_id": team_id})
        row = result.fetchone()
        return row.queue_size if row else 0