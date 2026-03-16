"""
data/repositories/email_config_repository.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Repository for EmailConfig (singleton pattern - only one row exists).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.email_config import EmailConfig


class EmailConfigRepository:
    
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self) -> EmailConfig | None:
        """Get the single email configuration row."""
        result = await self._db.execute(select(EmailConfig))
        return result.scalar_one_or_none()

    async def create(self, config: EmailConfig) -> EmailConfig:
        """Create the email configuration (should only be called once during setup)."""
        self._db.add(config)
        await self._db.flush()
        await self._db.refresh(config)
        return config

    async def update(
        self,
        config_id: int,
        **fields,
    ) -> EmailConfig:
        """Update email configuration."""
        result = await self._db.execute(
            select(EmailConfig).where(EmailConfig.config_id == config_id)
        )
        config = result.scalar_one()
        
        for key, value in fields.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)
        
        await self._db.flush()
        await self._db.refresh(config)
        return config