"""
schemas/email_schema.py
~~~~~~~~~~~~~~~~~~~~~~~
Internal representation of a parsed inbound email.
Produced by IMAPPoller or the webhook parser before being
handed to EmailIngestService.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EmailPayload(BaseModel):
    message_id: str = Field(..., description="RFC 2822 Message-ID — globally unique per email")
    in_reply_to: Optional[str] = Field(default=None, description="In-Reply-To header value")
    references: list[str] = Field(default_factory=list, description="References header chain")
    subject: str
    sender_email: str
    body_text: Optional[str] = None
    received_at: datetime
    is_auto_reply: bool = False