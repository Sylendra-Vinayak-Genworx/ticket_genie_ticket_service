from sqlalchemy import Column, Integer, ForeignKey, DateTime
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from src.data.models.postgres.base import Base

class TicketEmbedding(Base):
    """Represents the vector embedding of a ticket's content, used for similarity search and matching. Each record is associated with a specific ticket via the ticket_id foreign key. The embedding column stores the vector representation of the ticket's title and description, which can be generated using a pre-trained language model. The created_at timestamp records when the embedding was generated, allowing for tracking and potential re-generation if needed."""
    __tablename__ = "ticket_embeddings"

    ticket_id = Column(
        Integer,
        ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
        primary_key=True
    )

    embedding = Column(Vector(768), nullable=False)

    created_at = Column(DateTime, server_default=func.now())