"""
src/data/repositories/ticket_assignment_repositoty.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Skill-based ticket assignment repository.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AgentStats:
    """Agent skill and workload metrics for assignment scoring."""
    user_id: str
    team_id: str | None
    proficiency_level: str
    tickets_resolved: int
    current_workload: int


class TicketAssignmentRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_agents_for_area(
        self,
        area_id: int,
        active_agent_ids: list[str],
    ) -> list[AgentStats]:
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
                CASE ags.proficiency_level
                    WHEN 'expert' THEN 3
                    WHEN 'intermediate' THEN 2
                    WHEN 'beginner' THEN 1
                    ELSE 0
                END DESC,
                current_workload ASC,
                tickets_resolved DESC
            """
        )

        result = await self._session.execute(
            sql,
            {"area_id": area_id, "agent_ids": active_agent_ids}
        )

        return [
            AgentStats(
                user_id=row.user_id,
                team_id=None,
                proficiency_level=row.proficiency_level,
                tickets_resolved=row.tickets_resolved,
                current_workload=row.current_workload,
            )
            for row in result.fetchall()
        ]

    async def get_least_loaded_agent(
        self,
        active_agent_ids: list[str],
    ) -> str | None:
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
            # All agents have zero tickets — pick randomly to avoid silent insertion-
            # order bias from the Auth Service response.
            import random
            return random.choice(active_agent_ids)

        return row.assignee_id

    async def get_least_loaded_lead_for_team(
        self,
        lead_ids: list[str],
        preferred_team_id: str | None,
    ) -> str | None:
        """
        Return the least-loaded lead, preferring leads whose team_id matches
        ``preferred_team_id``.  Falls back to the globally least-loaded lead.

        «Least loaded» is measured by active ticket count (same definition as
        get_least_loaded_agent).  When all leads have zero tickets the function
        picks randomly to avoid silent bias from Auth Service insertion order.
        """
        if not lead_ids:
            return None

        # ── Preferred team: pick the least-loaded lead inside that team ───────
        if preferred_team_id:
            sql_preferred = text(
                """
                WITH lead_workload AS (
                    SELECT
                        assignee_id,
                        COUNT(*) AS workload
                    FROM tickets
                    WHERE status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
                      AND assignee_id IS NOT NULL
                      AND assignee_id = ANY(:lead_ids)
                    GROUP BY assignee_id
                )
                SELECT ap.user_id, COALESCE(lw.workload, 0) AS workload
                FROM agent_profiles ap
                LEFT JOIN lead_workload lw ON lw.assignee_id = ap.user_id
                WHERE ap.user_id = ANY(:lead_ids)
                  AND ap.team_id = :preferred_team_id
                ORDER BY workload ASC
                LIMIT 1
                """
            )
            result = await self._session.execute(
                sql_preferred,
                {"lead_ids": lead_ids, "preferred_team_id": preferred_team_id},
            )
            row = result.fetchone()
            if row is not None:
                return row.user_id

        # ── Global fallback: least-loaded lead regardless of team ─────────────
        sql_global = text(
            """
            WITH lead_workload AS (
                SELECT
                    assignee_id,
                    COUNT(*) AS workload
                FROM tickets
                WHERE status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
                  AND assignee_id IS NOT NULL
                  AND assignee_id = ANY(:lead_ids)
                GROUP BY assignee_id
            )
            SELECT ap.user_id, COALESCE(lw.workload, 0) AS workload
            FROM agent_profiles ap
            LEFT JOIN lead_workload lw ON lw.assignee_id = ap.user_id
            WHERE ap.user_id = ANY(:lead_ids)
            ORDER BY workload ASC
            LIMIT 1
            """
        )
        result = await self._session.execute(sql_global, {"lead_ids": lead_ids})
        row = result.fetchone()

        if row is None:
            # No rows at all (leads have no agent_profile rows yet) — pick randomly.
            import random
            return random.choice(lead_ids)

        # If the minimum workload is 0 we might have multiple equally unloaded leads.
        # Collect all leads at that minimum and pick randomly to avoid bias.
        if row.workload == 0:
            sql_zeros = text(
                """
                WITH lead_workload AS (
                    SELECT
                        assignee_id,
                        COUNT(*) AS workload
                    FROM tickets
                    WHERE status IN ('OPEN', 'IN_PROGRESS', 'ON_HOLD')
                      AND assignee_id IS NOT NULL
                      AND assignee_id = ANY(:lead_ids)
                    GROUP BY assignee_id
                )
                SELECT ap.user_id
                FROM agent_profiles ap
                LEFT JOIN lead_workload lw ON lw.assignee_id = ap.user_id
                WHERE ap.user_id = ANY(:lead_ids)
                  AND COALESCE(lw.workload, 0) = 0
                """
            )
            zero_result = await self._session.execute(sql_zeros, {"lead_ids": lead_ids})
            zero_ids = [r.user_id for r in zero_result.fetchall()]
            if zero_ids:
                import random
                return random.choice(zero_ids)

        return row.user_id

    async def get_agent_workload(self, user_id: str) -> int:
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
    
    async def try_acquire_assignment_lock(self, ticket_id: int) -> bool:
        """
        Atomically mark ticket as 'being assigned' to prevent concurrent assignment.
        Returns True if lock acquired, False if ticket already being processed.
        """
        from sqlalchemy import text as _text
        sql = _text(
            """
            UPDATE tickets
            SET routing_status = 'ASSIGNING',
                updated_at = CURRENT_TIMESTAMP
            WHERE ticket_id = :ticket_id
              AND routing_status NOT IN ('ASSIGNING')
            RETURNING ticket_id
            """
        )
        result = await self._session.execute(sql, {"ticket_id": ticket_id})
        await self._session.flush()
        return result.fetchone() is not None

    async def get_team_queue_size(self, team_id: str) -> int:
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