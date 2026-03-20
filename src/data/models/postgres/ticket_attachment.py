from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket
    from src.data.models.postgres.ticket_comment import TicketComment


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    attachment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False
    )
    # Nullable — ticket-level attachments (uploaded at creation) have no comment_id;
    # comment attachments set this to link back to the originating comment.
    comment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_comments.comment_id", ondelete="SET NULL"), nullable=True, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    uploaded_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="attachments")
    comment: Mapped[Optional["TicketComment"]] = relationship("TicketComment", back_populates="attachments")