"""
schemas/email_schema.py
~~~~~~~~~~~~~~~~~~~~~~~
Internal representation of a parsed inbound email and the LLM-powered
ticket extraction schema.

EmailTicketParseResult
──────────────────────
A Pydantic model that represents the structured output produced by the
Groq LLM after reading a raw email subject + body.  The model enforces:

  • title / description / product          — basic string validators
  • severity                               — must be one of CRITICAL/HIGH/MEDIUM/LOW
  • area_of_concern_name                   — must exactly match one of the area
                                            names passed in from the DB; the
                                            model_validator resolves this to
                                            area_of_concern_id (int | None)
  • area_of_concern_id                     — populated by model_validator after
                                            fuzzy-matching area_of_concern_name
                                            against the provided areas list

The `areas` parameter is injected at construction time via model_config
extra="allow" so Pydantic doesn't strip it, then removed post-validation.

_groq_async / _groq_sync
─────────────────────────
Helpers that call the ChatGroq LLM, parse the JSON response into an
EmailTicketParseResult, and return it to the caller.  Both accept a list
of AreaOfConcern objects from the DB so the prompt and validator use the
exact same names.

Rule-based fallback
───────────────────
_fallback_parse() is used when Groq is unavailable.  It still creates a
valid EmailTicketParseResult (with area_of_concern_id = None).

EmailPayload
────────────
Unchanged — raw inbound email as produced by IMAPPoller.  Pydantic
validators normalise the fields before EmailIngestService sees them.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from src.data.models.postgres.area_of_concern import AreaOfConcern

logger = logging.getLogger(__name__)

_MODEL_NAME = "llama-3.3-70b-versatile"

# ── Severity / urgency mappings ───────────────────────────────────────────────

_SEVERITY_VALS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

# Map LLM urgency words → Severity enum values
_URGENCY_TO_SEVERITY: dict[str, str] = {
    "critical": "CRITICAL",
    "high":     "HIGH",
    "medium":   "MEDIUM",
    "low":      "LOW",
    # tolerate the LLM returning severity values directly
    "CRITICAL": "CRITICAL",
    "HIGH":     "HIGH",
    "MEDIUM":   "MEDIUM",
    "LOW":      "LOW",
}

# ── Prompt template ───────────────────────────────────────────────────────────

_PARSE_SYSTEM = """
You are an email-to-support-ticket parser for a B2B SaaS helpdesk platform.

Given the subject and body of a customer support email, extract structured
ticket fields and return ONLY a valid JSON object — no markdown, no explanation,
no trailing text.

JSON schema:
{{
  "title":                 "<concise ticket title, max 120 chars>",
  "description":           "<full cleaned problem description — preserve technical details, error messages, stack traces>",
  "product":               "<product name if clearly mentioned, otherwise 'General'>",
  "severity":              "<one of: CRITICAL, HIGH, MEDIUM, LOW>",
  "area_of_concern_name":  "<choose the single best match from the list below>"
}}

Areas of concern (you MUST pick one name EXACTLY as written):
{area_names_list}

Rules:
- title:                Remove email prefixes (Re:, Fwd:, [TKT-...]).
- description:          Strip quoted / forwarded content (lines starting with >,
                        "On...wrote:", dashes). Keep all technical detail intact.
- product:              Extract only if clearly stated. Use "General" otherwise.
- severity:             Infer from language:
                          "urgent", "down", "outage", "cannot login"  → CRITICAL
                          "error", "failed", "broken", "not working"  → HIGH
                          neutral / informational                      → MEDIUM
                          "slow", "question", "how to"                → LOW
- area_of_concern_name: You MUST return one of the names from the list above,
                        spelled and cased EXACTLY as shown.  If nothing fits,
                        return the last item in the list.
""".strip()

_PARSE_USER = """
SUBJECT: {subject}

BODY:
{body}
""".strip()

# Fallback regex cleaner used when Groq is unavailable
_QUOTED_LINE_RE = re.compile(
    r"^(>.*|On .+wrote:|_{10,}|-----Original Message-----).*$",
    re.MULTILINE | re.DOTALL,
)


# ── EmailTicketParseResult ────────────────────────────────────────────────────

class EmailTicketParseResult(BaseModel):
    """
    Structured ticket fields extracted from an inbound email by the Groq LLM.

    All fields are Pydantic-validated.  The key constraint is that
    `area_of_concern_name` must match one of the area names supplied at
    construction time — the `model_validator` then resolves
    `area_of_concern_id` from the same list.

    Usage
    -----
    result = EmailTicketParseResult(
        title="...",
        description="...",
        product="...",
        severity="HIGH",
        area_of_concern_name="Payment Issues",
        _areas=db_areas,          # list[AreaOfConcern] injected privately
    )
    result.area_of_concern_id  # → int | None
    """

    title:                str = Field(..., max_length=120)
    description:          str
    product:              str = Field(default="General", max_length=100)
    severity:             str = Field(default="MEDIUM")
    area_of_concern_name: str = Field(default="other")
    area_of_concern_id:   Optional[int] = Field(default=None, exclude=True)

    # Private — injected by callers, stripped before serialisation
    model_config = {"extra": "allow"}

    # ── Field validators ──────────────────────────────────────────────────

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v[:120]

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("description must not be empty")
        return v

    @field_validator("product")
    @classmethod
    def validate_product(cls, v: str) -> str:
        v = v.strip()
        return v[:100] if v else "General"

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """Accept both LLM severity words and urgency synonyms."""
        mapped = _URGENCY_TO_SEVERITY.get(v.strip(), None) or _URGENCY_TO_SEVERITY.get(v.strip().upper(), None)
        if mapped:
            return mapped
        # If none of the above, default to MEDIUM
        logger.warning("email_parse: unknown severity value %r — defaulting to MEDIUM", v)
        return "MEDIUM"

    # ── Model validator: resolve area_of_concern_id ───────────────────────

    @model_validator(mode="after")
    def resolve_area_id(self) -> "EmailTicketParseResult":
        """
        Match `area_of_concern_name` against the list of AreaOfConcern objects
        injected via the `_areas` extra field.

        Matching strategy (in order):
          1. Exact case-insensitive match on area.name
          2. area.name is a substring of area_of_concern_name
          3. area_of_concern_name is a substring of area.name

        Sets `area_of_concern_id` and also normalises `area_of_concern_name`
        to the canonical DB spelling.

        If no areas were injected or no match found, `area_of_concern_id`
        stays None (the ticket is still created; area is simply unset).
        """
        areas: list[Any] = getattr(self, "_areas", None) or []
        if not areas:
            return self

        hint = self.area_of_concern_name.lower().strip()

        # 1. Exact match
        for area in areas:
            if area.name.lower() == hint:
                self.area_of_concern_id   = area.area_id
                self.area_of_concern_name = area.name
                return self

        # 2. hint is contained in area name or vice-versa
        for area in areas:
            aname = area.name.lower()
            if hint in aname or aname in hint:
                self.area_of_concern_id   = area.area_id
                self.area_of_concern_name = area.name
                logger.debug(
                    "email_parse: area fuzzy-matched hint=%r → area_id=%s name=%r",
                    hint, area.area_id, area.name,
                )
                return self

        logger.warning(
            "email_parse: area_of_concern_name %r did not match any DB area — leaving unset",
            self.area_of_concern_name,
        )
        return self


# ── Groq helpers ──────────────────────────────────────────────────────────────

def _build_prompt_system(areas: "list[AreaOfConcern]") -> str:
    """Inject the live area names into the system prompt."""
    if areas:
        names = "\n".join(f"  - {a.name}" for a in areas)
    else:
        names = "  - General"
    return _PARSE_SYSTEM.format(area_names_list=names)


def _parse_llm_response(
    raw: str,
    subject: str,
    body: str,
    areas: "list[AreaOfConcern]",
) -> EmailTicketParseResult:
    """Parse raw LLM JSON into a validated EmailTicketParseResult."""
    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)

    result = EmailTicketParseResult(
        title=data.get("title", subject)[:120],
        description=data.get("description", body or subject),
        product=data.get("product", "General"),
        severity=data.get("severity", "MEDIUM"),
        area_of_concern_name=data.get("area_of_concern_name", areas[0].name if areas else "other"),
        _areas=areas,
    )
    return result


def _groq_sync(
    subject: str,
    body: str,
    areas: "list[AreaOfConcern] | None" = None,
) -> EmailTicketParseResult:
    """
    Synchronous Groq call — used by Celery workers (no running event loop).
    Accepts the live areas list so the LLM prompt names match DB names exactly.
    """
    from src.config.settings import get_settings  # avoid circular at module level

    areas = areas or []
    settings = get_settings()
    llm = ChatGroq(
        model=_MODEL_NAME,
        temperature=0,
        api_key=settings.groq_api_key or None,
    )
    messages = [
        SystemMessage(content=_build_prompt_system(areas)),
        HumanMessage(content=_PARSE_USER.format(subject=subject, body=body or "")),
    ]
    try:
        response = llm.invoke(messages)
        return _parse_llm_response(response.content, subject, body, areas)
    except Exception as exc:
        logger.warning("email_parse: groq sync failed — using fallback: %s", exc)
        return _fallback_parse(subject, body, areas)


async def _groq_async(
    subject: str,
    body: str,
    areas: "list[AreaOfConcern] | None" = None,
) -> EmailTicketParseResult:
    """
    Async Groq call — used by EmailIngestService (already in an async context).
    Accepts the live areas list so the LLM prompt names match DB names exactly,
    and the Pydantic model_validator can resolve area_of_concern_id in one step.
    """
    from src.config.settings import get_settings  # avoid circular at module level

    areas = areas or []
    settings = get_settings()
    llm = ChatGroq(
        model=_MODEL_NAME,
        temperature=0,
        api_key=settings.groq_api_key or None,
    )
    messages = [
        SystemMessage(content=_build_prompt_system(areas)),
        HumanMessage(content=_PARSE_USER.format(subject=subject, body=body or "")),
    ]
    try:
        response = await llm.ainvoke(messages)
        return _parse_llm_response(response.content, subject, body, areas)
    except Exception as exc:
        logger.warning("email_parse: groq async failed — using fallback: %s", exc)
        return _fallback_parse(subject, body, areas)


def _fallback_parse(
    subject: str,
    body: str,
    areas: "list[AreaOfConcern] | None" = None,
) -> EmailTicketParseResult:
    """
    Stateless rule-based fallback used when Groq is unavailable or returns
    invalid JSON.

    Deliberately does NOT derive severity from keywords here — that
    responsibility belongs to ClassificationService (which queries the live
    keyword_rules table).  The caller (EmailIngestService._create_new_ticket)
    always runs ClassificationService.classify() after this returns and
    overwrites the severity field, so "MEDIUM" is just a safe neutral
    placeholder.

    Only handles:
      • Stripping quoted / forwarded text from the body
      • Simple text-scan to guess area_of_concern_name from area names
    """
    areas = areas or []
    clean_body = _QUOTED_LINE_RE.sub("", body or "").strip() or body or subject

    # Text-scan area match — exact DB name substring match against subject+body
    combined  = (subject + " " + clean_body).lower()
    area_name = areas[0].name if areas else "other"
    for area in areas:
        if area.name.lower() in combined:
            area_name = area.name
            break

    return EmailTicketParseResult(
        title=subject[:120],
        description=clean_body,
        product="General",
        severity="MEDIUM",          # overwritten by ClassificationService in the service layer
        area_of_concern_name=area_name,
        _areas=areas,
    )


# ── Inbound email payload (produced by IMAP poller) ──────────────────────────

class EmailPayload(BaseModel):
    """
    Raw inbound email as produced by IMAPPoller.
    Pydantic validators normalise fields before EmailIngestService sees them.
    """
    message_id:    str           = Field(..., description="RFC 2822 Message-ID — globally unique per email")
    in_reply_to:   Optional[str] = Field(default=None)
    references:    list[str]     = Field(default_factory=list)
    subject:       str
    sender_email:  str
    body_text:     Optional[str] = None
    received_at:   datetime
    is_auto_reply: bool          = False

    @field_validator("message_id")
    @classmethod
    def normalise_message_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message_id must not be empty")
        if not v.startswith("<"):
            v = f"<{v}"
        if not v.endswith(">"):
            v = f"{v}>"
        return v

    @field_validator("sender_email")
    @classmethod
    def normalise_sender_email(cls, v: str) -> str:
        v = v.strip().lower()
        m = re.search(r"<([^>]+)>", v)
        if m:
            v = m.group(1).strip()
        if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError(f"sender_email is not a valid email address: {v!r}")
        return v

    @field_validator("subject")
    @classmethod
    def normalise_subject(cls, v: str) -> str:
        return v.strip() or "(no subject)"

    @field_validator("references", mode="before")
    @classmethod
    def parse_references(cls, v) -> list[str]:
        if isinstance(v, str):
            return [r.strip() for r in v.split() if r.strip()]
        return list(v) if v else []

    @field_validator("body_text")
    @classmethod
    def strip_body(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None


# ── Backward-compatibility alias ──────────────────────────────────────────────
# Some older callers import ParsedEmailContent — alias to the new class so
# nothing breaks during a rolling deploy.
ParsedEmailContent = EmailTicketParseResult