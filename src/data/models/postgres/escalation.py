from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket


class EscalationHistory(Base):
    """
    Records each escalation event for a ticket.

    escalated_by_user_id  →  plain Integer (Auth Service user_id, no FK).
    escalated_to_user_id  →  plain Integer (Auth Service user_id, no FK).
    """

    __tablename__ = "escalation_history"

    escalation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False
    )

    # Cross-service user references — plain Integers, no FK
    escalated_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    escalated_to_user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    escalated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="escalation_history")