from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AgentStats:
    assignee_id: str
    team_id: str | None        # team the agent belongs to (from tickets history)
    experience: int            # resolved / closed tickets for the area
    workload: int              # currently open / in-progress tickets


class TicketAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Primary path: agents with area experience                           #
    # ------------------------------------------------------------------ #

    async def get_agent_stats_for_area(self, area_of_concern: str) -> list[AgentStats]:
        """
        Return every agent that has ever resolved a ticket for the given
        area_of_concern, together with their current open workload.

        Only records where assignee_id IS NOT NULL and the ticket was
        directly assigned to an agent (routing_status = 'SUCCESS') are
        considered — this guarantees we never treat a lead's user_id as an
        agent.
        """
        sql = text(
            """
            SELECT
                assignee_id,
                team_id,
                COUNT(*) FILTER (
                    WHERE status IN ('RESOLVED', 'CLOSED')
                )::int AS experience,
                COUNT(*) FILTER (
                    WHERE status IN ('OPEN', 'IN_PROGRESS')
                )::int AS workload
            FROM tickets
            WHERE area_of_concern = :area
              AND assignee_id IS NOT NULL
              AND routing_status = 'SUCCESS'
            GROUP BY assignee_id, team_id
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
                team_id=row.team_id,
                experience=row.experience,
                workload=row.workload,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ #
    # Fallback path: least-loaded agent across all areas                  #
    # ------------------------------------------------------------------ #

    async def get_least_loaded_agent(self) -> tuple[str, str | None] | None:
        """
        Returns (assignee_id, team_id) of the agent with the fewest active
        tickets globally.

        Only SUCCESS-routed tickets are counted so lead user_ids can never
        appear here.

        Returns None when no agents have any tickets at all.
        """
        sql = text(
            """
            SELECT assignee_id, team_id, COUNT(*) AS workload
            FROM tickets
            WHERE status IN ('OPEN', 'IN_PROGRESS')
              AND assignee_id IS NOT NULL
              AND routing_status = 'SUCCESS'
            GROUP BY assignee_id, team_id
            ORDER BY workload ASC
            LIMIT 1
            """
        )
        result = await self._session.execute(sql)
        row = result.fetchone()
        if row is None:
            return None
        return row.assignee_id, row.team_id

    # ------------------------------------------------------------------ #
    # Fallback-to-lead: least-loaded lead per team                        #
    # ------------------------------------------------------------------ #

    async def get_least_loaded_lead_for_team(
        self,
        lead_ids: list[str],
        team_id: str | None,
    ) -> str | None:
        """
        Given an explicit list of lead user_ids (sourced from Auth Service),
        and an optional preferred team_id, return the lead with the fewest
        active tickets.

        Preference order:
          1. Leads whose tickets share team_id (same team, least loaded)
          2. Any lead in lead_ids (cross-team, least loaded)

        This function never infers who a lead is from ticket data — that is
        always the caller's responsibility.
        """
        if not lead_ids:
            return None

        placeholders = ", ".join(f":lid_{i}" for i in range(len(lead_ids)))
        params: dict = {f"lid_{i}": lid for i, lid in enumerate(lead_ids)}
        params["team_id"] = team_id

        sql = text(
            f"""
            SELECT assignee_id, COUNT(*) AS workload
            FROM tickets
            WHERE status IN ('OPEN', 'IN_PROGRESS')
              AND assignee_id IN ({placeholders})
            GROUP BY assignee_id
            ORDER BY
                CASE WHEN team_id = :team_id THEN 0 ELSE 1 END,
                workload ASC
            LIMIT 1
            """
        )

        result = await self._session.execute(sql, params)
        row = result.fetchone()

        if row:
            return row.assignee_id

        # All leads have zero tickets — prefer same-team lead, else first
        return lead_ids[0]