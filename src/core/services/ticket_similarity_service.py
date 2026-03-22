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
            logger.info(f"[EMBEDDING] Generated embedding for content length={len(content)}, dimensions={len(embedding)}")
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
            logger.info(f"[SIMILARITY SEARCH] Query: '{query_text}', top_k={top_k}, min_similarity={min_similarity}")
            
            # Generate query embedding
            query_embedding = await self.generate_embedding(query_text)
            logger.info(f"[SIMILARITY SEARCH] Generated query embedding: dimensions={len(query_embedding)}, first 5 values={query_embedding[:5]}")
            
            embedding_str = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"
            logger.info(f"[SIMILARITY SEARCH] Embedding string length: {len(embedding_str)} chars")

            # Fetch similar tickets with solution_text, fallback to top 3 comments if NULL
            sql = text("""
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
                    COALESCE(
                        te.solution_text,
                        (
                            SELECT string_agg(tc.body, E'\\n\\n' ORDER BY tc.created_at DESC)
                            FROM ticket_comments tc
                            WHERE tc.ticket_id = t.ticket_id
                              AND tc.is_internal = false
                            LIMIT 3
                        )
                    ) as solution_text,
                    1 - (te.embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM ticket_embeddings te
                JOIN tickets t ON t.ticket_id = te.ticket_id
                WHERE t.status IN ('RESOLVED', 'CLOSED')
                  AND te.embedding IS NOT NULL
                  AND 1 - (te.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
                ORDER BY te.embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
            """)

            logger.info(f"[SIMILARITY SEARCH] Executing SQL query...")
            result = await session.execute(
                sql,
                {
                    "embedding": embedding_str,
                    "min_similarity": min_similarity,
                    "limit": top_k,
                }
            )

            rows = result.fetchall()
            logger.info(f"[SIMILARITY SEARCH] SQL returned {len(rows)} rows")

            similar_tickets = []
            for row in rows:
                logger.info(f"[SIMILARITY SEARCH] Match: ticket_id={row.ticket_id}, similarity={round(float(row.similarity), 3)}, title='{row.title[:50]}'")
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
                    "solution_text": row.solution_text or ""
                })

            logger.info(f"[SIMILARITY SEARCH] Found {len(similar_tickets)} similar tickets (min_similarity={min_similarity})")
            
            # DEBUG: If no results, check what's in the database
            if len(similar_tickets) == 0:
                logger.warning("[SIMILARITY SEARCH] No results found! Checking database...")
                
                # Check total embeddings
                count_result = await session.execute(text("""
                    SELECT COUNT(*) as total
                    FROM ticket_embeddings te
                    JOIN tickets t ON t.ticket_id = te.ticket_id
                    WHERE t.status IN ('RESOLVED', 'CLOSED')
                      AND te.embedding IS NOT NULL
                """))
                row = count_result.fetchone()
                total = row[0] if row else 0
                logger.warning(f"[SIMILARITY SEARCH] Total RESOLVED/CLOSED tickets with embeddings: {total}")
                
                # Check top 3 matches without threshold
                debug_result = await session.execute(text("""
                    SELECT
                        t.ticket_id,
                        t.ticket_number,
                        t.title,
                        1 - (te.embedding <=> CAST(:embedding AS vector)) AS similarity
                    FROM ticket_embeddings te
                    JOIN tickets t ON t.ticket_id = te.ticket_id
                    WHERE t.status IN ('RESOLVED', 'CLOSED')
                      AND te.embedding IS NOT NULL
                    ORDER BY te.embedding <=> CAST(:embedding AS vector)
                    LIMIT 3
                """), {"embedding": embedding_str})
                
                top_matches = debug_result.fetchall()
                logger.warning(f"[SIMILARITY SEARCH] Top 3 matches (no threshold):")
                for match in top_matches:
                    # Access by index, not by name
                    logger.warning(f"  - ticket_id={match[0]}, ticket_number={match[1]}, title='{match[2][:50]}', similarity={round(float(match[3]), 3)}")
                
                logger.warning(f"[SIMILARITY SEARCH] All similarities are below threshold {min_similarity}!")
            
            return similar_tickets

        except Exception as e:
            logger.error(f"[SIMILARITY SEARCH] Search failed: {e}", exc_info=True)
            return []

    async def generate_and_store_embedding(
        self,
        ticket_id: int,
        content: str,
        session: AsyncSession
    ) -> bool:
        try:
            logger.info(f"[STORE EMBEDDING] Starting for ticket_id={ticket_id}, content_length={len(content)}")
            
            embedding = await self.generate_embedding(content)
            embedding_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            
            logger.info(f"[STORE EMBEDDING] Generated embedding: dimensions={len(embedding)}, first 5 values={embedding[:5]}")

            await session.execute(
                text("DELETE FROM ticket_embeddings WHERE ticket_id = :ticket_id"),
                {"ticket_id": ticket_id}
            )
            
            logger.info(f"[STORE EMBEDDING] Deleted old embedding for ticket_id={ticket_id}")
            
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
            logger.error(f"[STORE EMBEDDING] Failed to generate/store embedding for ticket {ticket_id}: {e}")
            raise


_similarity_service: Optional[TicketSimilarityService] = None


def get_similarity_service() -> TicketSimilarityService:
    global _similarity_service
    if _similarity_service is None:
        from src.config.settings import get_settings
        settings = get_settings()
        _similarity_service = TicketSimilarityService(groq_api_key=settings.groq_api_key)
    return _similarity_service