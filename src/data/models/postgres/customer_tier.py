from typing import TYPE_CHECKING, Optional

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.sla import SLA
    from src.data.models.postgres.agent_profile import AgentProfile


class CustomerTier(Base):
    """
    Defines SLA tier buckets (ENTERPRISE / STANDARD / BASIC).
    user_id stored on AgentProfile/Ticket is a plain integer — no FK to Auth Service.
    """

    __tablename__ = "customer_tiers"

    tier_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    slas: Mapped[list["SLA"]] = relationship("SLA", back_populates="customer_tier")
    agent_profiles: Mapped[list["AgentProfile"]] = relationship(
        "AgentProfile", back_populates="customer_tier"
    )