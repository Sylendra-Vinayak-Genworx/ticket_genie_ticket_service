from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.sla import SLAPolicy


class BusinessHours(Base):
    """
    A named working-hours schedule used by SLAPolicy to pause/resume SLA clocks.
    """

    __tablename__ = "business_hours"

    business_hours_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")
    monday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tuesday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wednesday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    thursday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    friday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    saturday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sunday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    