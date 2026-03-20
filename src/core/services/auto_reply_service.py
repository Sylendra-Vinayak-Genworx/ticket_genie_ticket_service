from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_MODEL_NAME = "llama-3.3-70b-versatile"




class TicketContext(BaseModel):
    """All context needed to generate any kind of draft reply."""
    ticket_number: str
    ticket_title: str
    status: str
    severity: str
    customer_name: str
    agent_name: Optional[str] = None
    history: Optional[str] = None       # previous emails / comments for context


class DraftedReply(BaseModel):
    subject: str
    body: str


class ReplyMode(str, Enum):
    NOTIFY_CUSTOMER = "notify_customer"
    CLARIFY_CUSTOMER = "clarify_customer"
    NOTIFY_AGENT = "notify_agent"


# ── System prompt (shared across all modes) ───────────────────────────────────

_SYSTEM_PROMPT = """
You are a professional and empathetic support assistant for a B2C SaaS platform called TicketGenie.
You write clear, concise support emails on behalf of the support team.

Rules:
- Address the recipient by name.
- Always include the ticket number in the subject and opening line.
- Tone: professional, warm, never robotic or overly formal.
- Be specific. Do not make up details not provided to you.
- Do not use filler phrases like "I hope this email finds you well".
- Keep the email short — customers and agents do not read long emails.
- Sign off every email with: "— Support Team, TicketGenie"

Respond in EXACTLY this format and nothing else:
SUBJECT: <subject line>
BODY:
<email body>
""".strip()


# ── Per-mode user prompts ─────────────────────────────────────────────────────

_NOTIFY_CUSTOMER_PROMPT = """
Write a notification email to the customer about an update on their support ticket.

Ticket Number : {ticket_number}
Ticket Title  : {ticket_title}
Status        : {status}
Severity      : {severity}
Customer Name : {customer_name}
Agent Handling: {agent_name}
Update        : {event}
{history_block}
""".strip()

_CLARIFY_CUSTOMER_PROMPT = """
Write a polite email to the customer asking for more information needed to resolve their support request.
Be specific about exactly what you need. Do not ask vague questions.
Do not mention a ticket number or status if they are empty or not yet assigned.

Subject          : {ticket_title}
Customer Name    : {customer_name}
What we need     : {event}
{history_block}
""".strip()

_NOTIFY_AGENT_PROMPT = """
Write a concise internal notification email to a support agent or team lead.
This is a system-generated alert — be direct and action-oriented.

Ticket Number : {ticket_number}
Ticket Title  : {ticket_title}
Status        : {status}
Severity      : {severity}
Customer Name : {customer_name}
Recipient     : {agent_name}
Alert         : {event}
{history_block}
""".strip()

_PROMPT_MAP = {
    ReplyMode.NOTIFY_CUSTOMER: _NOTIFY_CUSTOMER_PROMPT,
    ReplyMode.CLARIFY_CUSTOMER: _CLARIFY_CUSTOMER_PROMPT,
    ReplyMode.NOTIFY_AGENT: _NOTIFY_AGENT_PROMPT,
}


# ── Service ───────────────────────────────────────────────────────────────────

class AIDraftService:
    """Generates AI-drafted email replies via Groq."""

    def __init__(self) -> None:
        self._llm = ChatGroq(
            temperature=0.2,
            model=_MODEL_NAME,
        )

    async def draft(
        self,
        mode: ReplyMode,
        context: TicketContext,
        event: str,
    ) -> DraftedReply:
        """
        Generate a drafted email reply.
        """
        history_block = (
            f"Previous conversation:\n{context.history}"
            if context.history
            else ""
        )

        user_message = _PROMPT_MAP[mode].format(
            ticket_number=context.ticket_number,
            ticket_title=context.ticket_title,
            status=context.status,
            severity=context.severity,
            customer_name=context.customer_name,
            agent_name=context.agent_name or "our team",
            event=event,
            history_block=history_block,
        )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        try:
            response = await self._llm.ainvoke(messages)
            return _parse_response(
                raw=response.content,
                ticket_number=context.ticket_number,
                ticket_title=context.ticket_title,
            )
        except Exception as exc:
            logger.exception(
                "ai_draft: generation failed ticket=%s mode=%s: %s",
                context.ticket_number, mode, exc,
            )
            raise


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_response(raw: str, ticket_number: str, ticket_title: str) -> DraftedReply:
    """
    Parse SUBJECT: / BODY: output into a DraftedReply.
    Falls back to a safe default subject if the model drifts from the format.
    """
    subject = f"Re: [{ticket_number}] {ticket_title}"
    body = raw.strip()

    try:
        lines = raw.strip().splitlines()

        for line in lines:
            if line.upper().startswith("SUBJECT:"):
                subject = line[len("SUBJECT:"):].strip()
                break

        body_start = None
        for i, line in enumerate(lines):
            if line.upper().startswith("BODY:"):
                body_start = i + 1
                break

        if body_start is not None:
            body = "\n".join(lines[body_start:]).strip()

    except Exception:
        logger.warning(
            "ai_draft: could not parse structured response for ticket=%s — using raw output",
            ticket_number,
        )

    return DraftedReply(subject=subject, body=body)



# Lazy singleton — instantiated on first use so importing this module
# never fails when GROQ_API_KEY is absent (e.g. Celery beat never calls AI).
_ai_draft_service_instance = None


def get_ai_draft_service():
    global _ai_draft_service_instance
    if _ai_draft_service_instance is None:
        _ai_draft_service_instance = AIDraftService()
    return _ai_draft_service_instance


class _LazyProxy:
    """Proxy that defers AIDraftService construction until first attribute access."""
    def __getattr__(self, name):
        return getattr(get_ai_draft_service(), name)


ai_draft_service = _LazyProxy()