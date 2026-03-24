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
        self._get_embeddings() 

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
            from src.data.repositories.ticket_embedding_repository import TicketEmbeddingRepository
            repo = TicketEmbeddingRepository(session)
            
            logger.info(f"[SIMILARITY SEARCH] Executing DB search via repository...")
            rows = await repo.search_similar_tickets_with_metadata(
                embedding=query_embedding,
                limit=top_k,
                min_similarity=min_similarity
            )

            logger.info(f"[SIMILARITY SEARCH] DB returned {len(rows)} rows")

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
            logger.info(f"[STORE EMBEDDING] Generated embedding: dimensions={len(embedding)}, first 5 values={embedding[:5]}")

            from src.data.repositories.ticket_embedding_repository import TicketEmbeddingRepository
            repo = TicketEmbeddingRepository(session)
            await repo.upsert_embedding_with_solution(ticket_id, embedding)

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