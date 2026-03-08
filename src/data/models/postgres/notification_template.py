from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enum import NotificationChannel
from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.notification_log import NotificationLog


class NotificationTemplate(Base):
    """
    Reusable email / in-app message templates.
    Supports Jinja2-style placeholders e.g. {{ ticket_number }}, {{ assignee_name }}.
    """

    __tablename__ = "notification_templates"

    template_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel_enum", create_type=True),
        nullable=False,
    )

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)   # plain-text fallback
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        "NotificationLog"
    )