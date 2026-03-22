from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from src.data.clients.postgres_client import get_db
from src.core.services.ticket_similarity_service import get_similarity_service
from src.schemas.similarity_schema import SimilaritySearchResponse, SimilarTicket
from src.data.repositories.ticket_repository import TicketRepository
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tickets/similarity", tags=["similarity"])




"""Endpoint to search for similar tickets based on a query string. Returns a list of similar tickets with their similarity scores. Supports filtering by minimum similarity threshold and limiting the number of results. Only searches resolved/closed tickets to find relevant past issues."""
@router.get("", response_model=SimilaritySearchResponse)
async def search_similar_tickets(
    query: str = Query(
        ...,
        min_length=3,
        max_length=2000,
        description="Search query text (ticket title + description)"
    ),
    limit: int = Query(
        5,
        ge=1,
        le=10,
        description="Maximum number of results to return"
    ),
    min_similarity: float = Query(
        0.3,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold (0-1)"
    ),
    db: AsyncSession = Depends(get_db)
):
    try:
        similarity_service = get_similarity_service()

        similar_tickets = await similarity_service.find_similar_tickets(
            query_text=query,
            session=db,
            top_k=limit,
            min_similarity=min_similarity,
            status_filter=["RESOLVED", "CLOSED"]
        )

        return SimilaritySearchResponse(
            similar_tickets=similar_tickets,
            found_count=len(similar_tickets),
            min_similarity=min_similarity
        )

    except Exception as e:
        logger.error(f"Similarity search endpoint failed: {e}", exc_info=True)
        return SimilaritySearchResponse(
            similar_tickets=[],
            found_count=0,
            min_similarity=min_similarity
        )

"""Endpoint to generate and store an embedding for a specific ticket by ID. This can be used to backfill embeddings for existing tickets or generate embeddings for new tickets. Only generates embeddings for the ticket's title and description, and stores them in the database for later similarity searches."""
@router.post("/generate-embedding/{ticket_id}")
async def generate_ticket_embedding(
    ticket_id: int,
    db: AsyncSession = Depends(get_db)
):
    try:
        from sqlalchemy import select
        from src.data.models.postgres.ticket import Ticket

        ticket = await TicketRepository(db).get_by_id(ticket_id)

        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")

        similarity_service = get_similarity_service()
        content = f"{ticket.title}\n\n{ticket.description}"

        success = await similarity_service.generate_and_store_embedding(
            ticket_id=ticket_id,
            content=content,
            session=db
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate embedding"
            )

        await db.commit()

        return {
            "message": "Embedding generated successfully",
            "ticket_id": ticket_id,
            "ticket_number": ticket.ticket_number
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Generate embedding endpoint failed: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate embedding: {str(e)}"
        )


@router.get("/health")
async def similarity_health_check():
    try:
        similarity_service = get_similarity_service()
        test_embedding = await similarity_service.generate_embedding("test query")

        return {
            "status": "healthy",
            "service": "ticket_similarity",
            "embedding_dimension": len(test_embedding),
            "model": "sentence-transformers/all-mpnet-base-v2",
            "cost": "FREE (local embeddings)"
        }

    except Exception as e:
        logger.error(f"Similarity health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "ticket_similarity",
            "error": str(e)
        }