"""
core/tasks/email_tasks.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Single Celery task: poll_mailbox.

Runs every minute via Beat. Connects to the IMAP mailbox, fetches UNSEEN
messages, and routes each one through EmailIngestService.

Each message gets its own DB session and commit so a failure on one email
never rolls back the others already processed in the same cycle.

Uses the existing run_async() bridge from _loop.py, same as sla_tasks.py
and assignment_task.py.
"""

from __future__ import annotations

import logging

from src.celery_app import celery_app
from src.config.settings import get_settings
from src.core.services.email_ingestion_service import EmailIngestService
from src.core.services.imap_poller import IMAPPoller
from src.core.tasks._loop import run_async
from src.data.clients.auth_client import auth_client
from src.data.clients.postgres_client import AsyncSessionFactory
from src.schemas.email_schema import EmailPayload

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.poll_mailbox",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def poll_mailbox(self):
    """
    Beat task — polls IMAP for UNSEEN emails every 1 minute.
    Returns {"processed": N, "errors": N} for observability.
    """
    settings = get_settings()

    if not settings.IMAP_HOST or not settings.IMAP_USER:
        logger.warning("poll_mailbox: IMAP not configured — skipping")
        return {"processed": 0, "errors": 0}

    logger.info(
        "poll_mailbox: starting poll host=%s mailbox=%s",
        settings.IMAP_HOST, settings.IMAP_MAILBOX,
    )

    processed, errors = 0, 0

    try:
        poller = IMAPPoller()
        for payload in poller.fetch_unseen():
            try:
                run_async(_ingest_one(payload))
                processed += 1
            except Exception as exc:
                errors += 1
                logger.exception(
                    "poll_mailbox: ingest failed message_id=%s: %s",
                    payload.message_id, exc,
                )

    except Exception as exc:
        # IMAP connection error — retry the whole task
        logger.exception("poll_mailbox: IMAP connection error: %s", exc)
        raise self.retry(exc=exc, countdown=60)

    logger.info("poll_mailbox: done processed=%d errors=%d", processed, errors)
    return {"processed": processed, "errors": errors}


async def _ingest_one(payload: EmailPayload) -> None:
    """Open a fresh DB session, process one email, commit."""
    created_ticket = None
    async with AsyncSessionFactory() as session:
        svc = EmailIngestService(db=session, auth_client=auth_client)
        created_ticket = await svc.process(payload)
        await session.commit()
    
    if created_ticket:
        from src.core.tasks.assignment_task import auto_assign_ticket
        ticket_id, ticket_title = created_ticket
        auto_assign_ticket.delay(ticket_id=ticket_id, ticket_title=ticket_title)
        logger.info("email_tasks: enqueued auto_assign_ticket for ticket_id=%s", ticket_id)