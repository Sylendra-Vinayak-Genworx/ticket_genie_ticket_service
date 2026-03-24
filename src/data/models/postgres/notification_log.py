from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enum import NotificationChannel, NotificationStatus
from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.ticket import Ticket


class NotificationLog(Base):
    """
    Tracks every notification dispatched (or queued) for a ticket event.
    recipient_user_id  →  plain String (Auth Service user_id, no FK).
    """

    __tablename__ = "notification_logs"

    notification_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False
    )

    # Cross-service user reference — plain String, no FK
    recipient_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel_enum", create_type=True),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status_enum", create_type=True),
        nullable=False,
        default=NotificationStatus.PENDING,
    )

    # Optional FK to the template used (intra-service)
    template_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("notification_templates.template_id", ondelete="SET NULL"),
        nullable=True,
    )

    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Relationships
    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="notification_logs")