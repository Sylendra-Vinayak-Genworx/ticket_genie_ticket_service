
from __future__ import annotations

import logging
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.services.notification.email_service import EmailNotificationService
from src.core.services.notification.sse_service import SSENotificationService
from src.schemas.notification_schema import (
    AgentCommentRequest,
    AutoClosedRequest,
    CustomerCommentRequest,
    NotificationRequest,
    NotificationType,
    SLABreachedRequest,
    StatusChangedRequest,
    TicketAssignedRequest,
    TicketCreatedRequest,
)
from src.data.clients.auth_client import AuthServiceClient, UserDTO
from src.config.settings import get_settings

logger = logging.getLogger(__name__)

# Contact mode values coming from Auth Service
_MODE_EMAIL  = "email"
_MODE_PORTAL = "portal"

# These events always use both channels — they are operational alerts
_ALWAYS_BOTH = {NotificationType.TICKET_ASSIGNED, NotificationType.SLA_BREACHED}


class NotificationManager:
    """
    Routes notification requests to the correct delivery service(s)
    based on the recipient's preferred mode of contact.
    """

    async def send(
        self,
        request: NotificationRequest,
        db: AsyncSession,
        auth_client: AuthServiceClient,
    ) -> None:
        """
        Main entry point. Resolves channels, then dispatches.
        Never raises — failures are logged so the caller's transaction
        is never rolled back by a notification error.
        """
        try:
            await self._dispatch(request, db, auth_client)
        except Exception as exc:
            logger.exception(
                "notification_manager: unhandled error type=%s: %s",
                request.type, exc,
            )

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(
        self,
        request: NotificationRequest,
        db: AsyncSession,
        auth_client: AuthServiceClient,
    ) -> None:
        email_svc = EmailNotificationService(db)
        sse_svc   = SSENotificationService(db)

        match request.type:

            case NotificationType.TICKET_CREATED:
                user = await self._resolve_user(request.customer_id, auth_client)
                if not user:
                    return
                channels = self._channels(user, request.type)
                if "email" in channels:
                    await email_svc.send_ticket_created(request, user.email)
                if "sse" in channels:
                    await sse_svc.send_ticket_created(request)

            case NotificationType.STATUS_CHANGED:
                user = await self._resolve_user(request.customer_id, auth_client)
                if not user:
                    return
                channels = self._channels(user, request.type)
                customer_name = user.email.split("@")[0]
                if "email" in channels:
                    await email_svc.send_status_changed(request, user.email, customer_name)
                if "sse" in channels:
                    await sse_svc.send_status_changed(request)

            case NotificationType.AGENT_COMMENT:
                # Always email for agent comments on EMAIL-source tickets
                user = await self._resolve_user(request.customer_id, auth_client)
                if not user:
                    return
                customer_name = user.email.split("@")[0]
                await email_svc.send_agent_comment(request, user.email, customer_name)

            case NotificationType.CUSTOMER_COMMENT:
                # Notify the assigned agent
                agent = await self._resolve_user(request.assignee_id, auth_client)
                if not agent:
                    return
                channels = self._channels(agent, request.type)
                if "email" in channels:
                    await email_svc.send_customer_comment(request, agent.email)
                if "sse" in channels:
                    await sse_svc.send_customer_comment(request)

            case NotificationType.TICKET_ASSIGNED:
                # Both channels always — operational alert
                agent = await self._resolve_user(request.assignee_id, auth_client)
                if not agent:
                    return
                agent_name = agent.email.split("@")[0]
                await email_svc.send_ticket_assigned(request, agent.email, agent_name)
                await sse_svc.send_ticket_assigned(request)

            case NotificationType.SLA_BREACHED:
                # Both channels always — operational alert
                lead = await self._resolve_user(request.lead_id, auth_client)
                if not lead:
                    return
                lead_name = lead.email.split("@")[0]
                await email_svc.send_sla_breached(request, lead.email, lead_name)
                await sse_svc.send_sla_breached(request)

            case NotificationType.AUTO_CLOSED:
                user = await self._resolve_user(request.customer_id, auth_client)
                if not user:
                    return
                channels = self._channels(user, request.type)
                customer_name = user.email.split("@")[0]
                if "email" in channels:
                    await email_svc.send_auto_closed(request, user.email, customer_name)
                if "sse" in channels:
                    await sse_svc.send_auto_closed(request)

            case _:
                logger.warning(
                    "notification_manager: unknown request type=%s", request.type
                )

    # ── Channel resolver ──────────────────────────────────────────────────────

    @staticmethod
    def _channels(user: UserDTO, ntype: NotificationType) -> set[str]:
        """
        Returns {"email"}, {"sse"}, or {"email", "sse"} based on
        the user's preferred_mode_of_contact.

        TICKET_ASSIGNED and SLA_BREACHED always return both.
        """
        if ntype in _ALWAYS_BOTH:
            return {"email", "sse"}

        mode = getattr(user, "preferred_mode_of_contact", _MODE_EMAIL) or _MODE_EMAIL

        if mode == _MODE_EMAIL:
            return {"email"}
        if mode == _MODE_PORTAL:
            return {"sse"}

        # Unrecognised value → safe default
        logger.warning(
            "notification_manager: unknown contact mode=%r for user=%s — defaulting to email",
            mode, user.id,
        )
        return {"email"}

    # ── User resolution ───────────────────────────────────────────────────────

    @staticmethod
    async def _resolve_user(
        user_id: str, auth_client: AuthServiceClient
    ) -> Optional[UserDTO]:
        """
        Fetch user from Auth Service.
        Returns None on failure so the caller can skip gracefully.
        Also adds preferred_mode_of_contact from the /by-email enrichment
        if UserDTO doesn't already carry it.
        """
        try:
            user = await auth_client.get_user(user_id)
            # If preferred_mode_of_contact is not yet on UserDTO, fetch it
            if not hasattr(user, "preferred_mode_of_contact") or user.preferred_mode_of_contact is None:
                user = await _enrich_contact_mode(user, auth_client)
            return user
        except Exception as exc:
            logger.warning(
                "notification_manager: could not resolve user_id=%s: %s",
                user_id, exc,
            )
            return None


async def _enrich_contact_mode(
    user: UserDTO, auth_client: AuthServiceClient
) -> UserDTO:
    """
    Fetch preferred_mode_of_contact via GET /auth/users/by-email.
    Falls back to the original UserDTO on any error.
    """
    settings = get_settings()
    base = settings.auth_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(
                f"{base}/api/v1/auth/users/by-email",
                params={"email": user.email},
            )
        if resp.status_code == 200:
            data = resp.json()
            # Patch the field onto the existing DTO
            object.__setattr__(
                user, "preferred_mode_of_contact",
                data.get("preferred_mode_of_contact", _MODE_EMAIL),
            )
    except Exception:
        pass
    return user


# Module-level singleton
notification_manager = NotificationManager()
