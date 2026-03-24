from pydantic import BaseModel
from typing import List, Optional
from pydantic import Field
# ============================================================================
# Pydantic Models
# ============================================================================

class SimilarTicket(BaseModel):
    """Similar ticket with metadata and AI-summarized solution."""
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
    solution_text: str = ""  # AI-summarized solution from comments


class SimilaritySearchResponse(BaseModel):
    """Response containing similar tickets."""
    similar_tickets: List[SimilarTicket]
    found_count: int
    min_similarity: float