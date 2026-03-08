from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.postgres.base import Base


class AreaOfConcern(Base):
    """
    Lookup table for valid ticket areas of concern.
    Decouples the area taxonomy from the tickets table and enables
    richer metadata (display name, active flag) without ticket-side changes.
    """

    __tablename__ = "areas_of_concern"

    area_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name:Mapped[str] = mapped_column(String,unique=True)
    def __repr__(self) -> str:  # pragma: no cover
        return f"<AreaOfConcern area_code={self.area_code!r}>"