from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base
from src.data.models.postgres.area_of_concern import AreaOfConcern


class AgentSkill(Base):
    """
    Mapping between agents/leads and areas of concern (skills).
    Used for skill-based routing and agent proficiency tracking.
    """
    __tablename__ = "agent_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "area_id", name="agent_skills_unique"),
    )

    agent_skill_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # References areas_of_concern.area_id, on delete cascade
    area_id: Mapped[int] = mapped_column(
        BigInteger, 
        ForeignKey("areas_of_concern.area_id", ondelete="CASCADE"), 
        index=True, 
        nullable=False
    )
    proficiency_level: Mapped[str] = mapped_column(String(50), default="intermediate")
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationship to area of concern
    area: Mapped["AreaOfConcern"] = relationship("AreaOfConcern")

    def __repr__(self):
        return f"<AgentSkill id={self.agent_skill_id} user_id={self.user_id} area_id={self.area_id} proficiency={self.proficiency_level}>"
