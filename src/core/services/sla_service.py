import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.config.settings import get_settings
from src.constants.enum import Priority, Severity
from src.data.models.postgres.ticket import Ticket
from src.data.repositories.sla_repository import SLARepository
from src.data.repositories.sla_rule_repository import SLARuleRepository

logger = logging.getLogger(__name__)


@dataclass
class SLAConfig:
    """Deadline durations returned by SLA rule lookup."""
    sla_id: int | None
    response_deadline_minutes: int
    resolution_deadline_minutes: int
    escalation_after_minutes: int
    used_default: bool = False


class SLAService:
    def __init__(self, sla_repo: SLARepository, sla_rule_repo: SLARuleRepository) -> None:
        """
          init  .
        
        Args:
            sla_repo (SLARepository): Input parameter.
            sla_rule_repo (SLARuleRepository): Input parameter.
        """
        self._repo = sla_repo
        self._rule_repo = sla_rule_repo

    # ── Rule lookup ───────────────────────────────────────────────────────────

    async def resolve_config(
        self,
        customer_tier_id: int | None,
        severity: Severity,
        priority: Priority,
    ) -> SLAConfig:
        """Look up SLA rule and return deadline durations (minutes)."""
        settings = get_settings()
        sla = None
        rule = None

        if customer_tier_id is not None:
            sla = await self._repo.get_active_sla_for_tier(customer_tier_id)
            if sla:
                rule = await self._rule_repo.get_rule(sla.sla_id, severity, priority)

        if rule is None:
            logger.warning(
                "sla_service: no rule for tier=%s sev=%s pri=%s — using defaults",
                customer_tier_id, severity, priority,
            )
            return SLAConfig(
                sla_id=sla.sla_id if sla else None,
                response_deadline_minutes=settings.DEFAULT_RESPONSE_TIME_MINUTES,
                resolution_deadline_minutes=settings.DEFAULT_RESOLUTION_TIME_MINUTES,
                escalation_after_minutes=settings.DEFAULT_ESCALATION_AFTER_MINUTES,
                used_default=True,
            )

        return SLAConfig(
            sla_id=sla.sla_id,
            response_deadline_minutes=rule.response_time_minutes,
            resolution_deadline_minutes=rule.resolution_time_minutes,
            escalation_after_minutes=rule.escalation_after_minutes,
        )


    def start_response_sla(self, ticket: Ticket, now: datetime) -> None:
        """Called at ticket creation (NEW)."""
        ticket.response_sla_started_at = now

    def complete_response_sla(self, ticket: Ticket, now: datetime) -> None:
        """
        Called when:
        - Status transitions to IN_PROGRESS
        - First agent comment is added
        """
        if ticket.response_sla_completed_at is None:
            ticket.response_sla_completed_at = now

    def mark_first_response(self, ticket: Ticket, now: datetime) -> None:
        """Called when an agent posts the first comment."""
        if ticket.first_response_at is None:
            ticket.first_response_at = now
        self.complete_response_sla(ticket, now)

    def check_response_breach(self, ticket: Ticket, now: datetime) -> bool:
        """
        Returns True if response SLA is breached and not yet marked.
        Only applies while ticket is in NEW / ACKNOWLEDGED / OPEN.
        """
        from src.constants.enum import TicketStatus
        if ticket.response_sla_completed_at is not None:
            return False
        if ticket.response_sla_breached_at is not None:
            return False
        if ticket.status not in (
            TicketStatus.NEW, TicketStatus.ACKNOWLEDGED, TicketStatus.OPEN
        ):
            return False
        if ticket.response_sla_started_at is None:
            return False
        if ticket.response_sla_deadline_minutes is None:
            return False
        deadline = ticket.response_sla_started_at + timedelta(
            minutes=ticket.response_sla_deadline_minutes
        )
        return now >= deadline

    # ── Resolution SLA ────────────────────────────────────────────────────────

    def start_resolution_sla(self, ticket: Ticket, now: datetime) -> None:
        """Called when status → IN_PROGRESS."""
        ticket.resolution_sla_started_at = now
        ticket.resolution_sla_total_pause_duration = 0
        ticket.resolution_sla_paused_at = None

    def pause_resolution_sla(self, ticket: Ticket, now: datetime) -> None:
        """Called when status → ON_HOLD."""
        if ticket.resolution_sla_started_at and ticket.resolution_sla_paused_at is None:
            ticket.resolution_sla_paused_at = now

    def resume_resolution_sla(self, ticket: Ticket, now: datetime) -> None:
        """Called when status → IN_PROGRESS from ON_HOLD."""
        if ticket.resolution_sla_paused_at:
            elapsed = int((now - ticket.resolution_sla_paused_at).total_seconds() / 60)
            ticket.resolution_sla_total_pause_duration += elapsed
            ticket.resolution_sla_paused_at = None

    def complete_resolution_sla(self, ticket: Ticket, now: datetime) -> None:
        """Called when status → RESOLVED."""
        ticket.resolution_sla_completed_at = now

    def restart_resolution_sla(self, ticket: Ticket, now: datetime) -> None:
        """Called on reopen (CLOSED → OPEN). Clears all resolution SLA fields."""
        ticket.resolution_sla_started_at = None
        ticket.resolution_sla_paused_at = None
        ticket.resolution_sla_total_pause_duration = 0
        ticket.resolution_sla_completed_at = None
        ticket.resolution_sla_breached_at = None

    def check_resolution_breach(self, ticket: Ticket, now: datetime) -> bool:
        """
        Returns True if resolution SLA is breached and not yet marked.
        Only applies while ticket is IN_PROGRESS (not paused).
        """
        from src.constants.enum import TicketStatus
        if ticket.resolution_sla_completed_at is not None:
            return False
        if ticket.resolution_sla_breached_at is not None:
            return False
        if ticket.status != TicketStatus.IN_PROGRESS:
            return False
        if ticket.resolution_sla_started_at is None:
            return False
        if ticket.resolution_sla_deadline_minutes is None:
            return False
        effective_minutes = (
            ticket.resolution_sla_deadline_minutes
            + (ticket.resolution_sla_total_pause_duration or 0)
        )
        deadline = ticket.resolution_sla_started_at + timedelta(minutes=effective_minutes)
        return now >= deadline