
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enum import EventType, NotificationChannel, NotificationStatus
from src.schemas.notification_schema import (
    AgentCommentRequest,
    CustomerCommentRequest,
    SLABreachedRequest,
    StatusChangedRequest,
    TicketAssignedRequest,
    TicketCreatedRequest,
    AutoClosedRequest,
)
from src.data.models.postgres.notification_log import NotificationLog
from src.data.repositories.notification_log_repository import NotificationLogRepository

logger = logging.getLogger(__name__)


class SSEBus:
    """
    In-memory pub/sub bus backed by Redis pub/sub for multi-process coordination.
    user_id (str) → asyncio.Queue of JSON-encoded event strings.
    One queue per active browser tab/connection.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._redis = None
        self._listener_task = None

    async def _get_redis(self):
        if self._redis is None:
            from src.config.settings import get_settings
            import redis.asyncio as aioredis
            settings = get_settings()
            self._redis = aioredis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
        return self._redis

    async def _listen_redis(self) -> None:
        r = await self._get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe("sse_broadcast")
        logger.info("sse_bus: Redis pub/sub listener started")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        user_id = data.get("user_id")
                        event = data.get("event")
                        if user_id and event:
                            self._local_push(user_id, event)
                    except Exception as e:
                        logger.error("sse_bus: listen parse error: %s", e)
        except asyncio.CancelledError:
            logger.info("sse_bus: Redis pub/sub listener cancelled")
        except Exception as e:
            logger.error("sse_bus: Redis pub/sub listener failed with error: %s", e)
        finally:
            try:
                await pubsub.unsubscribe("sse_broadcast")
                await pubsub.close()
            except Exception:
                pass
            
            self._listener_task = None
            logger.info("sse_bus: Redis pub/sub listener stopped and task reset")

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        if self._listener_task is None or self._listener_task.done():
            logger.info("sse_bus: creating redis listener task")
            self._listener_task = asyncio.create_task(self._listen_redis())
            
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._queues.setdefault(user_id, []).append(q)
        logger.debug("sse_bus: user_id=%s subscribed (connections=%d)", user_id, len(self._queues[user_id]))
        return q

    def unsubscribe(self, user_id: str, queue: asyncio.Queue) -> None:
        queues = self._queues.get(user_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._queues.pop(user_id, None)
        logger.debug("sse_bus: user_id=%s unsubscribed", user_id)

    async def push(self, user_id: str, event: dict) -> None:
        """Publish an event to all active connections (across all processes) for this user."""
        logger.info("sse_bus: publishing event to Redis for user_id=%s type=%s", user_id, event.get("type"))
        payload = json.dumps({"user_id": user_id, "event": event})
        r = await self._get_redis()
        await r.publish("sse_broadcast", payload)

    def _local_push(self, user_id: str, event: dict) -> None:
        """Push an event to all active connections for this user locally."""
        queues = self._queues.get(user_id, [])
        if not queues:
            logger.debug("sse_bus: user_id=%s not locally connected — event dropped", user_id)
            return
        payload = json.dumps(event)
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("sse_bus: queue full for user_id=%s — event dropped", user_id)

    def is_connected(self, user_id: str) -> bool:
        return bool(self._queues.get(user_id))


sse_bus = SSEBus()



class SSENotificationService:
    """
    Pushes UI notifications via SSEBus and writes a NotificationLog row.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._repo = NotificationLogRepository(db)

    async def send_ticket_created(self, req: TicketCreatedRequest) -> None:
        await self._push(
            recipient_id=req.customer_id,
            ticket_id=req.ticket_id,
            event_type=EventType.CREATED.value,
            payload={
                "type": "TICKET_CREATED",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "message": f"Your ticket {req.ticket_number} has been received.",
            },
        )

    async def send_status_changed(self, req: StatusChangedRequest) -> None:
        await self._push(
            recipient_id=req.customer_id,
            ticket_id=req.ticket_id,
            event_type=EventType.STATUS_CHANGED.value,
            payload={
                "type": "STATUS_CHANGED",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "old_status": req.old_status,
                "new_status": req.new_status,
                "message": f"[{req.ticket_number}] status changed to {req.new_status}.",
            },
        )

    async def send_customer_comment(self, req: CustomerCommentRequest) -> None:
        await self._push(
            recipient_id=req.assignee_id,
            ticket_id=req.ticket_id,
            event_type=EventType.COMMENT_ADDED.value,
            payload={
                "type": "CUSTOMER_COMMENT",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "customer_name": req.customer_name,
                "message": f"{req.customer_name} replied on [{req.ticket_number}].",
            },
        )

    async def send_agent_comment(self, req: AgentCommentRequest) -> None:
        await self._push(
            recipient_id=req.customer_id,
            ticket_id=req.ticket_id,
            event_type=EventType.COMMENT_ADDED.value,
            payload={
                "type": "AGENT_COMMENT",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "agent_name": req.agent_name,
                "message": f"{req.agent_name} replied on [{req.ticket_number}].",
            },
        )

    async def send_ticket_assigned(self, req: TicketAssignedRequest) -> None:
        await self._push(
            recipient_id=req.assignee_id,
            ticket_id=req.ticket_id,
            event_type=EventType.ASSIGNED.value,
            payload={
                "type": "TICKET_ASSIGNED",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "severity": req.severity,
                "message": f"Ticket [{req.ticket_number}] has been assigned to you.",
            },
        )

    async def send_sla_breached(self, req: SLABreachedRequest) -> None:
        await self._push(
            recipient_id=req.lead_id,
            ticket_id=req.ticket_id,
            event_type=EventType.SLA_BREACHED.value,
            payload={
                "type": "SLA_BREACHED",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "severity": req.severity,
                "breach_type": req.breach_type,
                "message": (
                    f"[{req.ticket_number}] breached {req.breach_type} SLA. "
                    f"Immediate action required."
                ),
            },
        )

    async def send_auto_closed(self, req: AutoClosedRequest) -> None:
        await self._push(
            recipient_id=req.customer_id,
            ticket_id=req.ticket_id,
            event_type="AUTO_CLOSED",
            payload={
                "type": "AUTO_CLOSED",
                "ticket_number": req.ticket_number,
                "title": req.ticket_title,
                "message": f"Your ticket [{req.ticket_number}] has been auto-closed.",
            },
        )

    # ── Core push ─────────────────────────────────────────────────────────────

    async def _push(
        self,
        recipient_id: str,
        ticket_id: int,
        event_type: str,
        payload: dict,
    ) -> None:
        now = datetime.now(timezone.utc)
        payload["timestamp"] = now.isoformat()

        await sse_bus.push(recipient_id, payload)

        
        await self._repo.add(NotificationLog(
            ticket_id=ticket_id,
            recipient_user_id=recipient_id,
            channel=NotificationChannel.IN_APP,
            event_type=event_type,
            status=NotificationStatus.SENT,
            sent_at=now,
            payload=payload,
        ))