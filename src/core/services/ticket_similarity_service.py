"""
Ticket Similarity Search Service
Using LangChain + HuggingFace Embeddings (FREE, Local)
"""
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)


class TicketSimilarityService:

    def __init__(self, groq_api_key: str = ""):
        self._embeddings = None

    def _get_embeddings(self):
        if self._embeddings is None:
            try:
                from langchain_community.embeddings import HuggingFaceEmbeddings
                self._embeddings = HuggingFaceEmbeddings(
                    model_name="sentence-transformers/all-mpnet-base-v2",
                    model_kwargs={'device': 'cpu'},
                    encode_kwargs={'normalize_embeddings': True}
                )
                logger.info("✓ Initialized sentence-transformers embeddings (768 dimensions)")
            except Exception as e:
                logger.error(f"Failed to initialize embeddings: {e}")
                raise
        return self._embeddings

    async def generate_embedding(self, content: str) -> List[float]:
        try:
            embeddings = self._get_embeddings()
            import asyncio
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(None, embeddings.embed_query, content)
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise

    async def find_similar_tickets(
        self,
        query_text: str,
        session: AsyncSession,
        top_k: int = 5,
        min_similarity: float = 0.3,
        status_filter: Optional[List[str]] = None
    ) -> List[dict]:
        if status_filter is None:
            status_filter = ["RESOLVED", "CLOSED"]

        try:
            query_embedding = await self.generate_embedding(query_text)
            embedding_str = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

            # NOTE: "similar" is a reserved word in PostgreSQL — use "sim_results" as CTE name
            sql = text("""
                WITH sim_results AS (
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
                        1 - (te.embedding <=> CAST(:embedding AS vector)) AS similarity
                    FROM ticket_embeddings te
                    JOIN tickets t ON t.ticket_id = te.ticket_id
                    WHERE t.status IN ('RESOLVED', 'CLOSED')
                      AND te.embedding IS NOT NULL
                      AND 1 - (te.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
                    ORDER BY te.embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                )
                SELECT
                    s.*,
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'comment_id', tc.comment_id,
                                    'comment_text', tc.body,
                                    'created_at', tc.created_at,
                                    'is_internal', tc.is_internal
                                ) ORDER BY tc.created_at DESC
                            )
                            FROM ticket_comments tc
                            WHERE tc.ticket_id = s.ticket_id
                              AND tc.is_internal = false
                            LIMIT 3
                        ),
                        '[]'::json
                    ) as solution_comments
                FROM sim_results s
            """)

            result = await session.execute(
                sql,
                {
                    "embedding": embedding_str,
                    "min_similarity": min_similarity,
                    "limit": top_k,
                }
            )

            similar_tickets = []
            for row in result.fetchall():
                similar_tickets.append({
                    "ticket_id": row.ticket_id,
                    "ticket_number": row.ticket_number,
                    "title": row.title,
                    "description": row.description[:300] + "..." if len(row.description) > 300 else row.description,
                    "status": row.status,
                    "severity": row.severity,
                    "priority": row.priority,
                    "product": row.product,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "similarity_score": round(float(row.similarity), 3),
                    "solution_comments": row.solution_comments or []
                })

            logger.info(f"Found {len(similar_tickets)} similar tickets (min_similarity={min_similarity})")
            return similar_tickets

        except Exception as e:
            logger.error(f"Similarity search failed: {e}", exc_info=True)
            return []

    async def generate_and_store_embedding(
        self,
        ticket_id: int,
        content: str,
        session: AsyncSession
    ) -> bool:
        try:
            embedding = await self.generate_embedding(content)
            embedding_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"

            await session.execute(
                text("DELETE FROM ticket_embeddings WHERE ticket_id = :ticket_id"),
                {"ticket_id": ticket_id}
            )
            await session.execute(
                text("""
                    INSERT INTO ticket_embeddings (ticket_id, embedding)
                    VALUES (:ticket_id, CAST(:embedding AS vector))
                """),
                {"ticket_id": ticket_id, "embedding": embedding_str}
            )

            logger.info(f"✓ Stored embedding for ticket {ticket_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to generate/store embedding for ticket {ticket_id}: {e}")
            raise


_similarity_service: Optional[TicketSimilarityService] = None


def get_similarity_service() -> TicketSimilarityService:
    global _similarity_service
    if _similarity_service is None:
        from src.config.settings import get_settings
        settings = get_settings()
        _similarity_service = TicketSimilarityService(groq_api_key=settings.groq_api_key)
    return _similarity_service