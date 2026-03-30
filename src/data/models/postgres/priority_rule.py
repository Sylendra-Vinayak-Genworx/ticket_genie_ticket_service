from sqlalchemy import String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.constants.enum import Priority, Severity
from src.data.models.postgres.base import Base


class PriorityRule(Base):
    """
    DB-driven lookup table: (severity, tier_name) → priority.

    tier_name is a plain string (no FK) so that rules can be created
    for tier names that may not yet exist in customer_tiers.
    Enums reuse existing DB types — create_type=False prevents recreation.
    """

    __tablename__ = "priority_rules"
    __table_args__ = (
        UniqueConstraint("severity", "tier_name", name="uq_priority_severity_tier"),
    )

    rule_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity_enum", create_type=False),
        nullable=False,
    )
    tier_name: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, name="priority_enum", create_type=False),
        nullable=False,
    )
