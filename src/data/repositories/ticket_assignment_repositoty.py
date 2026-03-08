"""
TicketAssignmentRepository
~~~~~~~~~~~~~~~~~~~~~~~~~~
All raw SQL / ORM queries needed by the auto-assignment service.
Kept here so the service layer stays free of query concerns.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AgentStats:
    assignee_id: str
    experience: int   # resolved / closed tickets for the area
    workload: int     # currently open / in-progress tickets


class TicketAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Primary path: agents with area experience                           #
    # ------------------------------------------------------------------ #

    async def get_agent_stats_for_area(self, area_of_concern: str) -> list[AgentStats]:
        """
        For a given area_of_concern return every agent that has ever resolved
        a ticket there, together with their current open workload.

        Only agents who have at least 1 resolved/closed ticket for the area
        are returned (the experience > 0 filter in HAVING).
        """
        sql = text(
            """
            SELECT
                assignee_id,
                COUNT(*) FILTER (
                    WHERE status IN ('RESOLVED', 'CLOSED')
                )::int AS experience,
                COUNT(*) FILTER (
                    WHERE status IN ('OPEN', 'IN_PROGRESS')
                )::int AS workload
            FROM tickets
            WHERE area_of_concern = :area
              AND assignee_id IS NOT NULL
            GROUP BY assignee_id
            HAVING COUNT(*) FILTER (
                       WHERE status IN ('RESOLVED', 'CLOSED')
                   ) > 0
            ORDER BY experience DESC
            """
        )
        result = await self._session.execute(sql, {"area": area_of_concern})
        rows = result.fetchall()
        return [
            AgentStats(
                assignee_id=row.assignee_id,
                experience=row.experience,
                workload=row.workload,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ #
    # Fallback path: least-loaded agent across all areas                  #
    # ------------------------------------------------------------------ #

    async def get_least_loaded_agent(self) -> str | None:
        """
        Returns the assignee_id of the agent with the fewest active tickets
        globally.  Returns None when there are no agents with any tickets.
        """
        sql = text(
            """
            SELECT assignee_id, COUNT(*) AS workload
            FROM tickets
            WHERE status IN ('OPEN', 'IN_PROGRESS')
              AND assignee_id IS NOT NULL
            GROUP BY assignee_id
            ORDER BY workload ASC
            LIMIT 1
            """
        )
        result = await self._session.execute(sql)
        row = result.fetchone()
        return row.assignee_id if row else None

