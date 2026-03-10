"""
data/models/postgres/email_thread.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tracks every inbound email linked to a ticket.

Added on top of the original skeleton:
  direction      — always INBOUND now; reserved for future OUTBOUND use
  raw_body_text  — plain-text body for reference / search
  processed_at   — stamped when ingestion succeeds
  processing_error — set when ingestion fails (for debug / retry)
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger, DateTime, Enum as SAEnum,
    ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket


class EmailDirection(str, enum.Enum):
    INBOUND = "INBOUND"


class EmailThread(Base):
    __tablename__ = "email_threads"

    thread_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── RFC 2822 identifiers ──────────────────────────────────────────────────
    message_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    in_reply_to: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    raw_subject: Mapped[str] = mapped_column(String(500), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # ── Direction (INBOUND only for now) ──────────────────────────────────────
    direction: Mapped[EmailDirection] = mapped_column(
        SAEnum(EmailDirection, name="email_direction_enum", create_type=True),
        nullable=False,
        default=EmailDirection.INBOUND,
    )

    # ── Content ───────────────────────────────────────────────────────────────
    raw_body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Timestamps & error capture ────────────────────────────────────────────
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="email_threads")

    __table_args__ = (
        Index("ix_email_threads_in_reply_to", "in_reply_to"),
    )