from sqlalchemy import Column, Integer, ForeignKey, DateTime
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from src.data.models.postgres.base import Base

class TicketEmbedding(Base):

    __tablename__ = "ticket_embeddings"

    ticket_id = Column(
        Integer,
        ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
        primary_key=True
    )

    embedding = Column(Vector(768), nullable=False)

    created_at = Column(DateTime, server_default=func.now())