from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from typing import Generator

from src.schemas.email_schema import EmailPayload, EmailAttachment

logger = logging.getLogger(__name__)


def _decode(raw: str | None) -> str:
    """Decode a possibly RFC 2047-encoded header value to plain string."""
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return " ".join(out).strip()


def _bare_address(header_val: str) -> str:
    """Extract bare email address from 'Name <addr>' or plain 'addr'."""
    m = re.search(r"<([^>]+)>", header_val)
    return m.group(1).strip().lower() if m else header_val.strip().lower()


def _is_auto_reply(msg: email.message.Message) -> bool:
    """Return True if standard auto-reply headers are set."""
    auto_submitted = msg.get("Auto-Submitted", "no").lower()
    if auto_submitted != "no":
        return True
    if msg.get("X-Autoreply", "").strip():
        return True
    return False


def _plain_text(msg: email.message.Message) -> str | None:
    """Return the first text/plain part of the message with normalised line endings."""
    raw_bytes = None
    charset = "utf-8"

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                raw_bytes = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                break
    else:
        if msg.get_content_type() == "text/plain":
            raw_bytes = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"

    if not raw_bytes:
        return None

    text = raw_bytes.decode(charset, errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_references(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [r.strip() for r in raw.split() if r.strip()]


def _normalise_message_id(raw: str) -> str:
    """
    Wrap in angle brackets if missing, then lowercase the whole thing.
    Message-IDs are case-insensitive in practice — many mail servers
    mangle the case on replies, which breaks thread matching without this.
    """
    mid = raw.strip()
    if not mid.startswith("<"):
        mid = f"<{mid}"
    if not mid.endswith(">"):
        mid = f"{mid}>"
    return mid.lower()


# ── Attachment extractor ──────────────────────────────────────────────────────

_ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf", "text/plain", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB


def _extract_attachments(msg: email.message.Message) -> list[EmailAttachment]:
    """
    Walk the MIME tree and return all non-inline file attachments that are
    within the allowed content-type list and under the size limit.
    """
    attachments: list[EmailAttachment] = []
    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        content_disposition = part.get_content_disposition() or ""
        # Only grab parts explicitly marked as attachments (skip inline images
        # embedded in the HTML body, plain-text parts, etc.)
        if "attachment" not in content_disposition.lower():
            continue

        content_type = part.get_content_type().lower()
        if content_type not in _ALLOWED_ATTACHMENT_TYPES:
            logger.debug(
                "imap_poller: skipping attachment with disallowed type=%s", content_type
            )
            continue

        raw = part.get_payload(decode=True)
        if not raw:
            continue
        if len(raw) > _MAX_ATTACHMENT_BYTES:
            logger.warning(
                "imap_poller: attachment exceeds 10 MB limit (%d bytes) — skipping",
                len(raw),
            )
            continue

        # Decode filename
        raw_filename = part.get_filename() or ""
        filename = _decode(raw_filename).strip() or f"attachment.{content_type.split('/')[-1]}"

        attachments.append(EmailAttachment(
            filename=filename,
            content_type=content_type,
            data=raw,
        ))
        logger.debug("imap_poller: found attachment filename=%r type=%s size=%d", filename, content_type, len(raw))

    return attachments


# ── Poller ─────────────────────────────────────────────────────────────────────

class IMAPPoller:
    """
    Thin IMAP4_SSL wrapper. One connection per poll cycle.

    All configuration is passed explicitly via the constructor so this class
    has no dependency on settings or the database — the caller (email_tasks.py)
    is responsible for loading config from DB or env and passing it in.
    This makes the poller fully synchronous and Celery-friendly.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        mailbox: str = "INBOX",
    ) -> None:
        """
          init  .
        
        Args:
            host (str): Input parameter.
            port (int): Input parameter.
            user (str): Input parameter.
            password (str): Input parameter.
            mailbox (str): Input parameter.
        """
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._mailbox = mailbox

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self._host, self._port)
        conn.login(self._user, self._password)
        conn.select(self._mailbox)
        return conn

    def fetch_unseen(self) -> Generator[EmailPayload, None, None]:
        """
        Yield one EmailPayload per UNSEEN message.
        Marks each message SEEN before yielding.
        Skips auto-replies silently.

        All message_id / in_reply_to / references values are normalised to
        lowercase so that thread matching in EmailThreadRepository is
        case-insensitive.
        """
        conn = self._connect()
        try:
            _, data = conn.uid("search", None, "UNSEEN")
            uids: list[bytes] = data[0].split() if data and data[0] else []

            if not uids:
                logger.debug("imap_poller: mailbox is clean — no unseen messages")
                return

            logger.info("imap_poller: %d unseen message(s) to process", len(uids))

            for uid in uids:
                try:
                    _, msg_data = conn.uid("fetch", uid, "(RFC822)")
                    raw_bytes = msg_data[0][1]
                    msg: email.message.Message = email.message_from_bytes(
                        raw_bytes, policy=email.policy.default
                    )

                    # Mark SEEN now — prevents double-processing on worker restart
                    conn.uid("store", uid, "+FLAGS", "\\Seen")

                    if _is_auto_reply(msg):
                        logger.debug("imap_poller: uid=%s skipped (auto-reply)", uid)
                        continue

                    # ── Message-ID ─────────────────────────────────────────
                    raw_message_id = _decode(msg.get("Message-ID", "")).strip("<>").strip()
                    if not raw_message_id:
                        raw_message_id = (
                            f"synthetic-{uid.decode()}-{int(datetime.now().timestamp())}"
                        )
                        logger.warning(
                            "imap_poller: uid=%s has no Message-ID — using synthetic: %s",
                            uid, raw_message_id,
                        )

                    message_id = _normalise_message_id(raw_message_id)

                    # ── In-Reply-To ────────────────────────────────────────
                    in_reply_to_raw = _decode(msg.get("In-Reply-To", "")).strip()
                    in_reply_to = (
                        _normalise_message_id(in_reply_to_raw)
                        if in_reply_to_raw else None
                    )

                    # ── References ─────────────────────────────────────────
                    references = [
                        _normalise_message_id(r)
                        for r in _parse_references(msg.get("References"))
                    ]

                    # ── Attachments ────────────────────────────────────
                    attachments = _extract_attachments(msg)
                    if attachments:
                        logger.info(
                            "imap_poller: uid=%s has %d attachment(s)",
                            uid, len(attachments),
                        )

                    yield EmailPayload(
                        message_id=message_id,
                        in_reply_to=in_reply_to,
                        references=references,
                        subject=_decode(msg.get("Subject", "(no subject)")),
                        sender_email=_bare_address(_decode(msg.get("From", ""))),
                        body_text=_plain_text(msg),
                        received_at=datetime.now(timezone.utc),
                        is_auto_reply=False,
                        attachments=attachments,
                    )

                except Exception as exc:
                    logger.exception("imap_poller: failed to parse uid=%s: %s", uid, exc)

        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass