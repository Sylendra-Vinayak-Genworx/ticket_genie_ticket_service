from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.constants.enum import Severity,MatchField
from src.data.models.postgres.base import Base


class KeywordRule(Base):
    """
    Auto-classification rules: if `keyword` is found in `match_field`
    of an incoming ticket, assign `target_severity`.
    """

    __tablename__ = "keyword_rules"

    keyword_rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    match_field: Mapped[MatchField] = mapped_column(
        SAEnum(MatchField, name="match_field_enum", create_type=True), nullable=False
    )
    target_severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity_enum", create_type=True), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )