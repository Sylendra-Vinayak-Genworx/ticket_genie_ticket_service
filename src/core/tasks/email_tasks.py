
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


async def _get_imap_config() -> dict | None:
    """
    Load IMAP configuration from the database.
    Returns a config dict if an active config exists, otherwise None.
    Falls back gracefully so the caller can use env vars instead.
    """
    try:
        from src.core.services.email_config_service import EmailConfigService
        async with AsyncSessionFactory() as session:
            service = EmailConfigService(session)
            config = await service.get_decrypted_config()
            if config and config.get("is_active"):
                # Validate that the essential IMAP fields are present
                if config.get("imap_host") and config.get("imap_user"):
                    logger.info("poll_mailbox: using database IMAP configuration")
                    return config
                logger.warning(
                    "poll_mailbox: database config found but missing imap_host/imap_user"
                )
    except Exception as exc:
        logger.warning("poll_mailbox: could not load database config: %s", exc)
    return None


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
    # ── Load IMAP config (DB first, env fallback) ──────────────────────────
    db_config = run_async(_get_imap_config())

    settings = get_settings()

    if db_config:
        imap_host     = db_config["imap_host"]
        imap_port     = int(db_config.get("imap_port", 993))
        imap_user     = db_config["imap_user"]
        imap_password = db_config["imap_password"]
        imap_mailbox  = db_config.get("imap_mailbox", "INBOX")
        logger.info("poll_mailbox: config source=database host=%s", imap_host)
    else:
        imap_host     = settings.IMAP_HOST
        imap_port     = settings.IMAP_PORT
        imap_user     = settings.IMAP_USER
        imap_password = settings.IMAP_PASSWORD
        imap_mailbox  = settings.IMAP_MAILBOX
        logger.info("poll_mailbox: config source=environment host=%s", imap_host)

    if not imap_host or not imap_user:
        logger.warning("poll_mailbox: IMAP not configured — skipping")
        return {"processed": 0, "errors": 0}

    logger.info(
        "poll_mailbox: starting poll host=%s mailbox=%s user=%s",
        imap_host, imap_mailbox, imap_user,
    )

    processed, errors = 0, 0

    try:
        poller = IMAPPoller(
            host=imap_host,
            port=imap_port,
            user=imap_user,
            password=imap_password,
            mailbox=imap_mailbox,
        )
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
        error_str = str(exc)
        logger.exception("poll_mailbox: IMAP connection error: %s", exc)

        # Auth failures won't self-heal on retry — bail out immediately
        # so we don't pile up retries with the same wrong credentials.
        if "Invalid credentials" in error_str or "Authentication" in error_str:
            logger.error(
                "poll_mailbox: credential failure for user=%s — "
                "check IMAP password / App Password configuration. Not retrying.",
                imap_user,
            )
            return {"processed": 0, "errors": 1}

        raise self.retry(exc=exc, countdown=60)

    logger.info("poll_mailbox: done processed=%d errors=%d", processed, errors)
    return {"processed": processed, "errors": errors}


async def _ingest_one(payload: EmailPayload) -> None:
    """Open a fresh DB session, process one email, commit."""
    async with AsyncSessionFactory() as session:
        svc = EmailIngestService(db=session, auth_client=auth_client)
        created_ticket = await svc.process(payload)
        await session.commit()

    if created_ticket:
        from src.core.tasks.assignment_task import auto_assign_ticket
        ticket_id, ticket_title = created_ticket
        auto_assign_ticket.delay(ticket_id=ticket_id, ticket_title=ticket_title)
        logger.info(
            "email_tasks: enqueued auto_assign_ticket for ticket_id=%s", ticket_id
        )