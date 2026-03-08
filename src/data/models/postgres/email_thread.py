from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket


class EmailThread(Base):
    """Tracks inbound email threads linked to tickets (Zapier / email ingestion)."""

    __tablename__ = "email_threads"

    thread_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    in_reply_to: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    raw_subject: Mapped[str] = mapped_column(String(500), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="email_threads")