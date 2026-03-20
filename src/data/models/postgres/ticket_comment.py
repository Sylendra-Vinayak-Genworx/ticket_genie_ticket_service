from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket
    from src.data.models.postgres.ticket_event import TicketEvent
    from src.data.models.postgres.ticket_attachment import TicketAttachment


class TicketComment(Base):
    """
    Comments / replies on a ticket.
    
    Special flags:
      triggers_hold   — if True, posting this comment transitions ticket → ON_HOLD
                        and pauses the resolution SLA timer.
      triggers_resume — if True, posting this comment transitions ticket → IN_PROGRESS
                        and resumes the resolution SLA timer.
    """

    __tablename__ = "ticket_comments"

    comment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False
    )

    author_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    author_role: Mapped[str] = mapped_column(String(50), nullable=False)

    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_mandatory_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


    triggers_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggers_resume: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="comments")
    events: Mapped[list["TicketEvent"]] = relationship("TicketEvent", back_populates="comment")
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        "TicketAttachment", back_populates="comment", cascade="all, delete-orphan"
    )