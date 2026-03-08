from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.customer_tier import CustomerTier


class AgentProfile(Base):
  
    __tablename__ = "agent_profiles"

    agent_profile_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)

    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    customer_tier_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("customer_tiers.tier_id", ondelete="SET NULL"),
        nullable=True,
    )

    max_open_tickets: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    customer_tier: Mapped[Optional["CustomerTier"]] = relationship(
        "CustomerTier", back_populates="agent_profiles"
    )