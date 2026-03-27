"""
core/services/email_config_service.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Service for managing email configuration.
"""

from __future__ import annotations

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.email_config import EmailConfig
from src.data.repositories.email_config_repository import EmailConfigRepository
from src.schemas.email_config_schema import EmailConfigUpdateRequest
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class EmailConfigService:
    """
    Service for managing email configuration.
    """

    def __init__(self, db: AsyncSession) -> None:
        """
          init  .
        
        Args:
            db (AsyncSession): Input parameter.
        """
        self._db = db
        self._repo = EmailConfigRepository(db)

    async def get_config(self) -> EmailConfig | None:
        """Get current email configuration."""
        return await self._repo.get()

    async def get_decrypted_config(self) -> dict | None:
        """
        Get configuration with passwords.
        """
        config = await self._repo.get()
        if not config:
            return None

        return {
            "imap_host": config.imap_host,
            "imap_port": config.imap_port,
            "imap_user": config.imap_user,
            "imap_password": config.imap_password,
            "imap_mailbox": config.imap_mailbox,
            "smtp_host": config.smtp_host,
            "smtp_port": config.smtp_port,
            "smtp_user": config.smtp_user,
            "smtp_password": config.smtp_password,
            "smtp_from_name": config.smtp_from_name,
            "is_active": config.is_active,
        }

    async def update_config(
        self,
        request: EmailConfigUpdateRequest,
        updated_by_user_id: str,
    ) -> EmailConfig:
        """Update email configuration."""
        config = await self._repo.get()
        if not config:
            raise ValueError("Email configuration not found. Please initialize first.")

        update_fields = {}

        if request.imap_host is not None:
            update_fields["imap_host"] = request.imap_host
        if request.imap_port is not None:
            update_fields["imap_port"] = request.imap_port
        if request.imap_user is not None:
            update_fields["imap_user"] = request.imap_user
        if request.imap_password is not None:
            update_fields["imap_password"] = request.imap_password
        if request.imap_mailbox is not None:
            update_fields["imap_mailbox"] = request.imap_mailbox

        if request.smtp_host is not None:
            update_fields["smtp_host"] = request.smtp_host
        if request.smtp_port is not None:
            update_fields["smtp_port"] = request.smtp_port
        if request.smtp_user is not None:
            update_fields["smtp_user"] = request.smtp_user
        if request.smtp_password is not None:
            update_fields["smtp_password"] = request.smtp_password
        if request.smtp_from_name is not None:
            update_fields["smtp_from_name"] = request.smtp_from_name

        if request.is_active is not None:
            update_fields["is_active"] = request.is_active

        update_fields["updated_by"] = updated_by_user_id

        updated = await self._repo.update(config.config_id, **update_fields)
        await self._db.commit()

        logger.info(
            "email_config: updated by user=%s fields=%s",
            updated_by_user_id,
            list(update_fields.keys()),
        )

        return updated

    async def initialize_default_config(self) -> EmailConfig:
        """
        Create default email configuration from environment variables.
        """
        existing = await self._repo.get()
        if existing:
            logger.warning("email_config: configuration already exists")
            return existing

        settings = get_settings()

        config = EmailConfig(
            imap_host=settings.IMAP_HOST or "imap.gmail.com",
            imap_port=settings.IMAP_PORT,
            imap_user=settings.IMAP_USER or "support@example.com",
            imap_password=settings.IMAP_PASSWORD or "changeme",
            imap_mailbox=settings.IMAP_MAILBOX,
            smtp_host=settings.SMTP_HOST,
            smtp_port=settings.SMTP_PORT,
            smtp_user=settings.SMTP_USER or "support@example.com",
            smtp_password=settings.SMTP_PASSWORD or "changeme",
            smtp_from_name=settings.SMTP_FROM_NAME,
            is_active=True,
        )

        created = await self._repo.create(config)
        await self._db.commit()

        logger.info("email_config: initialized default configuration")
        return created