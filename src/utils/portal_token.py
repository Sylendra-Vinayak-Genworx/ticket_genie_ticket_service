"""
utils/portal_token.py
~~~~~~~~~~~~~~~~~~~~~
Generates a signed JWT for one-click portal login from an email link.

The token is appended as ``?token=…`` to the ticket URL so the existing
JWT middleware authenticates the user automatically — no password needed.

Claims
------
  sub       – user UUID (required by JWT middleware)
  role      – user role  (required by JWT middleware)
  ticket_id – scoped ticket (informational / audit)
  email     – customer email (informational / audit)
  purpose   – "portal_link" (distinguishes from regular session tokens)
  exp       – 15 minutes from issue time

Signed with the same ``secret_key`` / ``algorithm`` used by the rest of
the system so the JWT middleware can decode it without any changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt

from src.config.settings import get_settings

_PORTAL_TOKEN_EXPIRY_MINUTES = 15


def generate_portal_token(
    *,
    user_id: str,
    email: str,
    role: str,
    ticket_id: int,
) -> str:
    """Return a short-lived signed JWT for portal auto-login."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "ticket_id": ticket_id,
        "email": email,
        "purpose": "portal_link",
        "exp": now + timedelta(minutes=_PORTAL_TOKEN_EXPIRY_MINUTES),
        "iat": now,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
