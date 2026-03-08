from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enum import EventType
from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket
    from src.data.models.postgres.ticket_comment import TicketComment


class TicketEvent(Base):
    """
    Immutable audit trail. Also serves as the ticket timeline —
    filter by event_type = STATUS_CHANGED to get the full transition history.
    """

    __tablename__ = "ticket_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, name="event_type_enum", create_type=True), nullable=False
    )

    field_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    from_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    comment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_comments.comment_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="events")
    comment: Mapped[Optional["TicketComment"]] = relationship(
        "TicketComment", back_populates="events"
    )