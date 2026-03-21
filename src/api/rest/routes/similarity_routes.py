"""
Ticket Similarity Search API Routes

Provides endpoints for finding similar tickets using semantic search.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from src.data.clients.postgres_client import get_db_session
from src.core.services.ticket_similarity_service import get_similarity_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tickets/similarity", tags=["similarity"])


# ============================================================================
# Pydantic Models
# ============================================================================

class SolutionComment(BaseModel):
    """Comment from a resolved ticket showing solution."""
    comment_id: int
    comment_text: str
    created_at: str
    created_by_name: Optional[str] = None
    is_internal: bool


class SimilarTicket(BaseModel):
    """Similar ticket with metadata and solutions."""
    ticket_id: int
    ticket_number: str
    title: str
    description: str
    status: str
    severity: str
    priority: str
    product: str
    created_at: Optional[str] = None
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    solution_comments: List[dict] = []


class SimilaritySearchResponse(BaseModel):
    """Response containing similar tickets."""
    similar_tickets: List[SimilarTicket]
    found_count: int
    min_similarity: float


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("", response_model=SimilaritySearchResponse)
async def search_similar_tickets(
    query: str = Query(
        ..., 
        min_length=10,
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
        0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold (0-1)"
    ),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Find tickets similar to the given query text.
    
    This endpoint uses semantic search to find resolved/closed tickets
    that are similar in meaning to the user's query, even if they don't
    use the exact same words.
    
    **Use case:** Show similar resolved tickets when customer creates a new ticket,
    potentially deflecting the ticket if a solution is found.
    
    **Parameters:**
    - **query**: The text to search for (usually ticket title + description)
    - **limit**: Maximum number of results (1-10, default 5)
    - **min_similarity**: Minimum similarity score 0-1 (default 0.5, i.e., 50%)
    
    **Returns:**
    - List of similar tickets with solutions
    - Each ticket includes similarity score and up to 3 solution comments
    """
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
        # Return empty results instead of 500 error - fail gracefully
        return SimilaritySearchResponse(
            similar_tickets=[],
            found_count=0,
            min_similarity=min_similarity
        )


@router.post("/generate-embedding/{ticket_id}")
async def generate_ticket_embedding(
    ticket_id: int,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Generate and store embedding for a specific ticket.
    
    This is useful for:
    - Backfilling embeddings for existing tickets
    - Regenerating embeddings if needed
    - Testing the embedding pipeline
    
    **Note:** New tickets automatically get embeddings on creation,
    so you typically don't need to call this manually.
    """
    try:
        from sqlalchemy import select
        from src.data.models.postgres.ticket import Ticket
        
        # Get ticket
        result = await db.execute(
            select(Ticket).where(Ticket.ticket_id == ticket_id)
        )
        ticket = result.scalar_one_or_none()
        
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Generate embedding
        similarity_service = get_similarity_service()
        text = f"{ticket.title}\n\n{ticket.description}"
        
        success = await similarity_service.generate_and_store_embedding(
            ticket_id=ticket_id,
            text=text,
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
    """
    Health check for similarity service.
    Verifies that embeddings model is loaded and working.
    """
    try:
        similarity_service = get_similarity_service()
        
        # Test embedding generation
        test_embedding = await similarity_service.generate_embedding("test query")
        
        return {
            "status": "healthy",
            "service": "ticket_similarity",
            "embedding_dimension": len(test_embedding),
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "cost": "FREE (local embeddings)"
        }
        
    except Exception as e:
        logger.error(f"Similarity health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "ticket_similarity",
            "error": str(e)
        }