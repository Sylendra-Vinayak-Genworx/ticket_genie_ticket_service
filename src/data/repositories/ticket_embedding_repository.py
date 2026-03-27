"""
TicketEmbeddingRepository
─────────────────────────
Manages the ``ticket_embeddings`` table.

Key design decisions
--------------------
* ``find_similar`` uses a *parameterised* raw SQL query via ``text()``
  so SQLAlchemy will not mistake the string for a table name.
* The embedding is serialised to the pgvector string format
  ``"[x1,x2,…]"`` before binding — pgvector's CAST accepts this.
* A ``min_similarity`` threshold is applied inside the DB so that
  only semantically meaningful candidates are returned to the caller.
* ``upsert_embedding`` prevents duplicate rows on re-indexing.
"""

from __future__ import annotations

import logging

from sqlalchemy import text, Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.ticket_embedding import TicketEmbedding

logger = logging.getLogger(__name__)


def _vec_to_pg(embedding: list[float]) -> str:
    """Serialise a Python float list to pgvector's text literal ``[x,y,…]``."""
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


class TicketEmbeddingRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── WRITE ────────────────────────────────────────────────────────────────

    async def create_embedding(
        self, ticket_id: int, embedding: list[float]
    ) -> TicketEmbedding:
        obj = TicketEmbedding(ticket_id=ticket_id, embedding=embedding)
        self.session.add(obj)
        return obj

    async def upsert_embedding(
        self, ticket_id: int, embedding: list[float]
    ) -> TicketEmbedding:
        """Create or replace the embedding for *ticket_id*."""
        existing = await self.session.get(TicketEmbedding, ticket_id)
        if existing is not None:
            existing.embedding = embedding
            logger.debug("Updated embedding for ticket %s", ticket_id)
            return existing
        return await self.create_embedding(ticket_id, embedding)

    # ── READ ─────────────────────────────────────────────────────────────────

    async def find_similar(
        self,
        embedding: list[float],
        limit: int = 20,
        min_similarity: float = 0.60,
    ) -> list[Row]:
       
        vec_str = _vec_to_pg(embedding)

        stmt = text("""
            SELECT
                t.ticket_id,
                t.assignee_id,
                1 - (te.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE t.status  = 'RESOLVED'
              AND t.assignee_id IS NOT NULL
              AND 1 - (te.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
            ORDER BY te.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)

        result = await self.session.execute(
            stmt,
            {
                "embedding": vec_str,
                "min_similarity": min_similarity,
                "limit": limit,
            },
        )

        rows = result.fetchall()
        logger.debug(
            "find_similar: %d candidates above threshold %.2f",
            len(rows),
            min_similarity,
        )
        return rows

    async def upsert_embedding_with_solution(
        self, ticket_id: int, embedding: list[float], solution_text: str | None = None
    ) -> None:
        """Create or replace the embedding and solution_text for *ticket_id*."""
        vec_str = _vec_to_pg(embedding)
        
        await self.session.execute(
            text("DELETE FROM ticket_embeddings WHERE ticket_id = :ticket_id"),
            {"ticket_id": ticket_id}
        )
        
        if solution_text is not None:
            await self.session.execute(
                text("""
                    INSERT INTO ticket_embeddings (ticket_id, embedding, solution_text)
                    VALUES (:ticket_id, CAST(:embedding AS vector), :solution_text)
                """),
                {
                    "ticket_id": ticket_id,
                    "embedding": vec_str,
                    "solution_text": solution_text
                }
            )
        else:
            await self.session.execute(
                text("""
                    INSERT INTO ticket_embeddings (ticket_id, embedding)
                    VALUES (:ticket_id, CAST(:embedding AS vector))
                """),
                {
                    "ticket_id": ticket_id,
                    "embedding": vec_str,
                }
            )

    async def search_similar_tickets_with_metadata(
        self,
        embedding: list[float],
        limit: int = 5,
        min_similarity: float = 0.3,
    ) -> list[Row]:
        vec_str = _vec_to_pg(embedding)
        
        stmt = text("""
            SELECT
                t.ticket_id,
                t.ticket_number,
                t.title,
                t.description,
                t.status,
                t.severity,
                t.priority,
                t.product,
                t.created_at,
                te.solution_text,
                1 - (te.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM ticket_embeddings te
            JOIN tickets t ON t.ticket_id = te.ticket_id
            WHERE t.status IN ('RESOLVED', 'CLOSED')
              AND te.embedding IS NOT NULL
              AND 1 - (te.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
            ORDER BY te.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)

        result = await self.session.execute(
            stmt,
            {
                "embedding": vec_str,
                "min_similarity": min_similarity,
                "limit": limit,
            }
        )
        return result.fetchall()