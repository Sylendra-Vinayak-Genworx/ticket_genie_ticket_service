"""
Celery tasks for ticket embedding generation.
Runs asynchronously when tickets are marked as RESOLVED.
Uses Groq LLM for intelligent solution summarization and data masking.
"""
from __future__ import annotations

import logging

from src.celery_app import celery_app
from src.core.services.ticket_similarity_service import get_similarity_service
from src.core.tasks._loop import run_async
from src.data.clients.postgres_client import AsyncSessionFactory

logger = logging.getLogger(__name__)


async def _summarize_and_mask_solution(comments: list, groq_api_key: str) -> str:
    """
    Use Groq LLM to summarize comments and mask sensitive data.
    
    Args:
        comments: List of comment text strings
        groq_api_key: Groq API key
        
    Returns:
        Summarized and masked solution text
    """
    if not comments:
        return ""
    
    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Initialize Groq LLM
        llm = ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0,
            groq_api_key=groq_api_key
        )
        
        # Combine all comments
        combined_comments = "\n\n---\n\n".join(comments)
        
        # System prompt for summarization and masking
        system_prompt = """You are a support ticket solution summarizer. Your task is to:

1. Read all the comments from a resolved support ticket
2. Create a clear, concise summary of how the issue was resolved
3. Automatically mask all sensitive information:
   - Replace email addresses with [EMAIL]
   - Replace phone numbers with [PHONE]
   - Replace transaction IDs (TXN...) with [TRANSACTION_ID]
   - Replace order IDs (ORD...) with [ORDER_ID]
   - Replace credit card numbers with [CARD_NUMBER]
   - Replace account numbers with [ACCOUNT_NUMBER]
   - Replace any customer names with [CUSTOMER]
   - Replace any specific payment amounts with [AMOUNT]

4. Focus on the solution steps and outcome
5. Keep it concise (3-5 sentences maximum)
6. Write in past tense
7. Be professional and clear

Return ONLY the masked summary, nothing else."""

        user_prompt = f"""Here are the comments from a resolved support ticket. Summarize the solution and mask all sensitive data:

{combined_comments}"""

        # Create messages
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        # Get response from Groq
        response = llm.invoke(messages)
        solution_summary = response.content.strip()
        
        logger.info(f"Generated solution summary (length={len(solution_summary)})")
        return solution_summary
        
    except Exception as e:
        logger.error(f"Failed to summarize/mask with Groq: {e}")
        # Fallback: just concatenate comments without masking
        return "\n\n".join(comments)


async def _generate_and_store_embedding_async(ticket_id: int) -> bool:
    """
    Generate and store embedding for a ticket.
    Fetches ticket, comments, uses Groq to summarize and mask solution.
    
    Args:
        ticket_id: The ticket ID
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from src.config.settings import get_settings
        settings = get_settings()
        
        similarity_service = get_similarity_service()
        
        async with AsyncSessionFactory() as session:
            from sqlalchemy import text, select
            from src.data.models.postgres.ticket import Ticket
            from src.data.models.postgres.ticket_comment import TicketComment
            
            # Fetch ticket
            result = await session.execute(
                select(Ticket).where(Ticket.ticket_id == ticket_id)
            )
            ticket = result.scalar_one_or_none()
            
            if not ticket:
                logger.error(f"embedding_tasks: Ticket {ticket_id} not found")
                return False
            
            # Fetch all non-internal comments (public solution comments)
            result = await session.execute(
                select(TicketComment)
                .where(
                    TicketComment.ticket_id == ticket_id,
                    TicketComment.is_internal == False
                )
                .order_by(TicketComment.created_at.asc())
            )
            comments = result.scalars().all()
            
            # Build solution text using Groq LLM
            solution_text = ""
            if comments:
                comment_texts = [c.body for c in comments if c.body]
                # Use Groq to summarize and mask
                solution_text = await _summarize_and_mask_solution(
                    comment_texts,
                    settings.groq_api_key
                )
            
            # Combine title + description for embedding (no solution in embedding)
            embedding_content = f"{ticket.title}\n\n{ticket.description}"
            
            # Generate and store embedding
            embedding = await similarity_service.generate_embedding(embedding_content)
            from src.data.repositories.ticket_embedding_repository import TicketEmbeddingRepository
            repo = TicketEmbeddingRepository(session)
            await repo.upsert_embedding_with_solution(ticket_id, embedding, solution_text or None)
            
            await session.commit()
            
        logger.info(
            "embedding_tasks: Successfully generated embedding for ticket_id=%s (solution_length=%d)",
            ticket_id, len(solution_text)
        )
        return True
        
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
def generate_ticket_embedding(self, ticket_id: int):
    """
    Celery task to generate and store ticket embedding with AI-summarized solution.
    
    This task is triggered when a ticket is marked as RESOLVED.
    It:
    1. Fetches the ticket and all public comments
    2. Uses Groq LLM to summarize and mask sensitive data from comments
    3. Generates embedding from title + description (NOT solution)
    4. Stores embedding + AI-masked solution text together
    
    Args:
        ticket_id: The ticket ID
        
    Returns:
        dict with success status and ticket_id
    """
    logger.info(
        "embedding_tasks: Starting embedding generation for ticket_id=%s",
        ticket_id
    )
    
    try:
        success = run_async(_generate_and_store_embedding_async(ticket_id))
        
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