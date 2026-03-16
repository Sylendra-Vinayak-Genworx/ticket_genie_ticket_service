"""
data/models/postgres/email_config.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Single-row table storing system-wide email configuration.
Only one row should exist (enforced by singleton pattern in repository).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.postgres.base import Base


class EmailConfig(Base):
    __tablename__ = "email_config"

    config_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # IMAP Configuration (for email ingestion)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    imap_user: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_password: Mapped[str] = mapped_column(String(512), nullable=False)  # Encrypted
    imap_mailbox: Mapped[str] = mapped_column(String(100), nullable=False, default="INBOX")
    
    # SMTP Configuration (for sending notifications)
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_user: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_password: Mapped[str] = mapped_column(String(512), nullable=False)  # Encrypted
    smtp_from_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Support Team")
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<EmailConfig(id={self.config_id}, imap={self.imap_user}, smtp={self.smtp_user})>"