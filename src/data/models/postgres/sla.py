from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean, DateTime, Enum as SAEnum,
    ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enum import Priority, Severity
from src.data.models.postgres.base import Base

if TYPE_CHECKING:
    from src.data.models.postgres.customer_tier import CustomerTier
    from src.data.models.postgres.ticket import Ticket


class SLA(Base):
    """
    An SLA contract tied to a CustomerTier.
    One active SLA per tier at a time.
    """

    __tablename__ = "slas"

    sla_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_tier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customer_tiers.tier_id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    customer_tier: Mapped["CustomerTier"] = relationship("CustomerTier", back_populates="slas")
    rules: Mapped[list["SLARule"]] = relationship(
        "SLARule", back_populates="sla", cascade="all, delete-orphan"
    )
    policies: Mapped[list["SLAPolicy"]] = relationship(
        "SLAPolicy", back_populates="sla", cascade="all, delete-orphan"
    )


class SLARule(Base):
    """
    Time targets per (severity × priority) combination for a given SLA.
    """

    __tablename__ = "sla_rules"

    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sla_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("slas.sla_id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity_enum", create_type=True), nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, name="priority_enum", create_type=True), nullable=False
    )
    response_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("sla_id", "severity", "priority", name="uq_sla_severity_priority"),
    )

    # Relationships
    sla: Mapped["SLA"] = relationship("SLA", back_populates="rules")


class SLAPolicy(Base):
    """
    High-level SLA policy metadata (e.g. 'Business Hours only', 'Calendar 24x7').
    Extends SLA with operational scheduling rules.
    """

    __tablename__ = "sla_policies"

    policy_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sla_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("slas.sla_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # true = SLA clock runs only during business hours; false = 24×7
    business_hours_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Optional link to a BusinessHours schedule
    business_hours_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("business_hours.business_hours_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    sla: Mapped["SLA"] = relationship("SLA", back_populates="policies")