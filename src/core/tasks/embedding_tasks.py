"""
Celery tasks for ticket embedding generation.
Runs asynchronously when tickets are marked as RESOLVED.
"""
from __future__ import annotations

import logging

from src.celery_app import celery_app
from src.core.services.ticket_similarity_service import get_similarity_service
from src.core.tasks._loop import run_async
from src.data.clients.postgres_client import AsyncSessionFactory

logger = logging.getLogger(__name__)


async def _generate_and_store_embedding_async(ticket_id: int, title: str, description: str) -> bool:
    """
    Generate and store embedding for a ticket.
    
    Args:
        ticket_id: The ticket ID
        title: Ticket title
        description: Ticket description
        
    Returns:
        True if successful, False otherwise
    """
    try:
        similarity_service = get_similarity_service()
        content = f"{title}\n\n{description}"
        
        async with AsyncSessionFactory() as session:
            success = await similarity_service.generate_and_store_embedding(
                ticket_id=ticket_id,
                content=content,
                session=session
            )
            await session.commit()
            
        if success:
            logger.info(
                "embedding_tasks: Successfully generated embedding for ticket_id=%s",
                ticket_id
            )
        else:
            logger.warning(
                "embedding_tasks: Failed to generate embedding for ticket_id=%s",
                ticket_id
            )
            
        return success
        
    except Exception as exc:
        logger.exception(
            "embedding_tasks: Exception while generating embedding for ticket_id=%s: %s",
            ticket_id, exc
        )
        return False


@celery_app.task(
    name="tasks.generate_ticket_embedding",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def generate_ticket_embedding(self, ticket_id: int, title: str, description: str):
    """
    Celery task to generate and store ticket embedding.
    
    This task is triggered when a ticket is marked as RESOLVED.
    It generates an embedding from the ticket's title and description
    and stores it in the ticket_embeddings table for similarity search.
    
    Args:
        ticket_id: The ticket ID
        title: Ticket title
        description: Ticket description
        
    Returns:
        dict with success status and ticket_id
    """
    logger.info(
        "embedding_tasks: Starting embedding generation for ticket_id=%s title='%s'",
        ticket_id, title[:50] + "..." if len(title) > 50 else title
    )
    
    try:
        success = run_async(_generate_and_store_embedding_async(ticket_id, title, description))
        
        if success:
            logger.info(
                "embedding_tasks: Completed embedding generation for ticket_id=%s",
                ticket_id
            )
            return {"success": True, "ticket_id": ticket_id}
        else:
            logger.warning(
                "embedding_tasks: Embedding generation returned False for ticket_id=%s",
                ticket_id
            )
            # Retry on failure
            raise self.retry(exc=Exception("Embedding generation failed"), countdown=60)
            
    except Exception as exc:
        logger.exception(
            "embedding_tasks: Task failed for ticket_id=%s: %s",
            ticket_id, exc
        )
        # Retry up to max_retries (3 times)
        raise self.retry(exc=exc, countdown=60)