from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.constants.enum import EventType, NotificationChannel, NotificationStatus
from src.core.services.email_config_service import EmailConfigService
from src.schemas.notification_schema import (
    AgentCommentRequest,
    AutoClosedRequest,
    CustomerCommentRequest,
    SLABreachedRequest,
    StatusChangedRequest,
    TicketAssignedRequest,
    TicketCreatedRequest,
)
from src.data.models.postgres.notification_log import NotificationLog
from src.data.repositories.notification_log_repository import NotificationLogRepository
from src.data.models.postgres.email_thread import EmailThread, EmailDirection
from src.data.repositories.email_thread_repository import EmailThreadRepository

logger = logging.getLogger(__name__)


# ── Shared HTML chrome helpers ─────────────────────────────────────────────────

_HTML_OPEN = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <style>
    body  {{ font-family: Georgia, serif; background: #f5f5f0; margin: 0; padding: 0; }}
    .wrap {{ max-width: 580px; margin: 40px auto; background: #fff;
             border-radius: 4px; overflow: hidden; border: 1px solid #e5e5e0; }}
    .hdr  {{ background: #1a1a2e; padding: 28px 36px; }}
    .hdr h1 {{ color: #fff; margin: 0; font-size: 18px;
               font-weight: 400; letter-spacing: .5px; }}
    .body {{ padding: 32px 36px; color: #333; line-height: 1.7; font-size: 15px; }}
    .body p {{ margin: 0 0 16px; }}
    .badge {{ display: inline-block; background: #f0f0ff; color: #1a1a2e;
              font-family: monospace; font-weight: 700; font-size: 15px;
              padding: 4px 12px; border-radius: 3px;
              border: 1px solid #c8c8e8; letter-spacing: 1px; }}
    .info-table {{ width: 100%; border-collapse: collapse; margin: 16px 0 20px; }}
    .info-table td {{ padding: 7px 10px; font-size: 14px; vertical-align: top; }}
    .info-table td:first-child {{ color: #888; width: 38%; white-space: nowrap; }}
    .info-table tr {{ border-bottom: 1px solid #f0f0ed; }}
    .info-table tr:last-child {{ border-bottom: none; }}
    .pill {{ display: inline-block; padding: 3px 10px; border-radius: 12px;
             font-size: 12px; font-weight: 700; letter-spacing: .4px; }}
    .pill-open     {{ background: #e6f0ff; color: #1a4fbf; }}
    .pill-progress {{ background: #fff7e0; color: #8a6200; }}
    .pill-resolved {{ background: #e8f7ee; color: #1a7a3e; }}
    .pill-closed   {{ background: #f0f0f0; color: #555; }}
    .pill-sev-critical {{ background: #ffe6e6; color: #a00; }}
    .pill-sev-high     {{ background: #fff0e0; color: #a04000; }}
    .pill-sev-medium   {{ background: #fffbe6; color: #7a5900; }}
    .pill-sev-low      {{ background: #eef9ee; color: #2a6a2a; }}
    .alert-box {{ background: #fff8e6; border-left: 4px solid #e6a800;
                  padding: 14px 18px; border-radius: 0 4px 4px 0;
                  font-size: 14px; margin: 16px 0 20px; color: #5a4000; }}
    .comment-box {{ background: #f8f8fc; border-left: 4px solid #c8c8e8;
                    padding: 14px 18px; border-radius: 0 4px 4px 0;
                    font-size: 14px; margin: 16px 0 20px; color: #444;
                    white-space: pre-wrap; word-break: break-word; }}
    .ftr  {{ padding: 14px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body><div class="wrap">"""

_HTML_CLOSE = "</div></body></html>"

_HDR    = '<div class="hdr"><h1>{title}</h1></div>'
_BOPEN  = '<div class="body">'
_BCLOSE = "</div>"
_FTR    = '<div class="ftr">{text}</div>'


def _severity_pill(severity: str) -> str:
    s = severity.upper()
    css = {
        "CRITICAL": "pill-sev-critical",
        "HIGH":     "pill-sev-high",
        "MEDIUM":   "pill-sev-medium",
        "LOW":      "pill-sev-low",
    }.get(s, "pill-sev-medium")
    return f'<span class="pill {css}">{s}</span>'


def _status_pill(status: str) -> str:
    s = status.upper()
    css = {
        "OPEN":        "pill-open",
        "IN_PROGRESS": "pill-progress",
        "RESOLVED":    "pill-resolved",
        "CLOSED":      "pill-closed",
    }.get(s, "pill-open")
    return f'<span class="pill {css}">{s.replace("_", " ")}</span>'


def _info_table(*rows: tuple[str, str]) -> str:
    inner = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="info-table">{inner}</table>'


# ── Ingest pipeline templates (unchanged) ─────────────────────────────────────

_ACK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <style>
    body  {{ font-family: Georgia, serif; background: #f5f5f0; margin: 0; padding: 0; }}
    .wrap {{ max-width: 560px; margin: 40px auto; background: #fff;
             border-radius: 4px; overflow: hidden; border: 1px solid #e5e5e0; }}
    .hdr  {{ background: #1a1a2e; padding: 28px 36px; }}
    .hdr h1 {{ color: #fff; margin: 0; font-size: 18px;
               font-weight: 400; letter-spacing: .5px; }}
    .body {{ padding: 32px 36px; color: #333; line-height: 1.7; font-size: 15px; }}
    .body p {{ margin: 0 0 16px; }}
    .badge {{ display: inline-block; background: #f0f0ff; color: #1a1a2e;
              font-family: monospace; font-weight: 700; font-size: 16px;
              padding: 5px 14px; border-radius: 3px;
              border: 1px solid #c8c8e8; letter-spacing: 1px; }}
    .ftr  {{ padding: 16px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr"><h1>Support request received</h1></div>
    <div class="body">
      <p>Hi {customer_name},</p>
      <p>Thanks for reaching out. We've logged your request and a member of our team will follow up shortly.</p>
      <p>Your ticket number is <span class="badge">{ticket_number}</span></p>
      <p>Simply reply to this email if you have anything to add and we'll attach it to your ticket automatically.</p>
      <p>— {from_name}</p>
    </div>
    <div class="ftr">This is an automated message. Reply only to update ticket {ticket_number}.</div>
  </div>
</body>
</html>
"""

_ACK_TEXT = (
    "Hi {customer_name},\n\n"
    "Thanks for reaching out. We've logged your request under ticket "
    "{ticket_number}. A member of our team will follow up shortly.\n\n"
    "Simply reply to this email to add more information to your ticket.\n\n"
    "— {from_name}\n"
)

_CONTINUE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <style>
    body  {{ font-family: Georgia, serif; background: #f5f5f0; margin: 0; padding: 0; }}
    .wrap {{ max-width: 560px; margin: 40px auto; background: #fff;
             border-radius: 4px; overflow: hidden; border: 1px solid #e5e5e0; }}
    .hdr  {{ background: #1a1a2e; padding: 28px 36px; }}
    .hdr h1 {{ color: #fff; margin: 0; font-size: 18px;
               font-weight: 400; letter-spacing: .5px; }}
    .body {{ padding: 32px 36px; color: #333; line-height: 1.7; font-size: 15px; }}
    .body p {{ margin: 0 0 16px; }}
    .badge {{ display: inline-block; background: #f0f0ff; color: #1a1a2e;
              font-family: monospace; font-weight: 700; font-size: 16px;
              padding: 5px 14px; border-radius: 3px;
              border: 1px solid #c8c8e8; letter-spacing: 1px; }}
    .btn  {{ display: inline-block; background: #1a1a2e; color: #fff !important;
             text-decoration: none; padding: 13px 30px; border-radius: 4px;
             font-size: 14px; font-weight: 700; letter-spacing: .5px; margin: 8px 0 4px; }}
    .ftr  {{ padding: 16px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr"><h1>We've got your reply — {ticket_number}</h1></div>
    <div class="body">
      <p>Hi {customer_name},</p>
      <p>We've added your message to ticket <span class="badge">{ticket_number}</span>.</p>
      <p>For the best experience — including real-time updates, file attachments, and full conversation history — you can continue the conversation directly in our support portal:</p>
      <p><a class="btn" href="{ticket_url}">View ticket in portal →</a></p>
      <p>— {from_name}</p>
    </div>
    <div class="ftr">Ticket {ticket_number} · <a href="{ticket_url}">{ticket_url}</a></div>
  </div>
</body>
</html>
"""

_CONTINUE_TEXT = (
    "Hi {customer_name},\n\n"
    "We've added your message to ticket {ticket_number}.\n\n"
    "You can view and continue the conversation in our support portal:\n"
    "{ticket_url}\n\n"
    "— {from_name}\n"
)


# ── Deterministic draft builders ───────────────────────────────────────────────

def _draft_ticket_created(ticket_number, ticket_title, from_name):
    subject = f"[{ticket_number}] Support ticket received — we're on it"
    text = (
        f"Hi,\n\n"
        f"We've received your support ticket and it's been logged in our system.\n\n"
        f"  Ticket  : {ticket_number}\n"
        f"  Subject : {ticket_title}\n\n"
        f"A member of our support team will review your request and follow up shortly.\n"
        f"You can reply to this email at any time to add more information.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title="Support ticket received")
        + _BOPEN
        + "<p>Hi,</p>"
        + "<p>We've received your support ticket and it's been logged in our system.</p>"
        + _info_table(
            ("Ticket",  f'<span class="badge">{ticket_number}</span>'),
            ("Subject", ticket_title),
            ("Status",  _status_pill("ACKNOWLEDGED")),
        )
        + "<p>A member of our support team will review your request and follow up shortly. "
        + "You can reply to this email at any time to add more information.</p>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Automated message for ticket {ticket_number}.")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_status_changed(ticket_number, ticket_title, old_status, new_status,
                           severity, agent_name, customer_name, from_name):
    subject = f"[{ticket_number}] Ticket status updated: {new_status.replace('_', ' ').title()}"
    agent_line = f"  Handled by : {agent_name}\n" if agent_name else ""
    ns = new_status.upper()
    if ns == "RESOLVED":
        note_text = (
            "Your ticket has been marked as resolved. If the issue persists or you have "
            "further questions, please reply to this email and we will reopen your ticket.\n\n"
        )
        note_html = (
            "<p>Your ticket has been marked as <strong>resolved</strong>. "
            "If the issue persists or you have further questions, please reply to "
            "this email and we will reopen your ticket.</p>"
        )
    elif ns == "IN_PROGRESS":
        note_text = (
            "Our team is actively working on your ticket. "
            "We will keep you updated as progress is made.\n\n"
        )
        note_html = (
            "<p>Our team is <strong>actively working</strong> on your ticket. "
            "We will keep you updated as progress is made.</p>"
        )
    elif ns == "CLOSED":
        note_text = (
            "Your ticket has been closed. "
            "If you need further assistance, please open a new ticket.\n\n"
        )
        note_html = (
            "<p>Your ticket has been <strong>closed</strong>. "
            "If you need further assistance, please open a new ticket.</p>"
        )
    else:
        note_text = "We will keep you updated on any further changes.\n\n"
        note_html = "<p>We will keep you updated on any further changes.</p>"

    text = (
        f"Hi {customer_name},\n\n"
        f"The status of your support ticket has been updated.\n\n"
        f"  Ticket     : {ticket_number}\n"
        f"  Subject    : {ticket_title}\n"
        f"  Previous   : {old_status.replace('_', ' ').title()}\n"
        f"  New status : {new_status.replace('_', ' ').title()}\n"
        f"  Severity   : {severity}\n"
        + agent_line
        + "\n"
        + note_text
        + f"— {from_name}\n"
    )
    rows = [
        ("Ticket",          f'<span class="badge">{ticket_number}</span>'),
        ("Subject",         ticket_title),
        ("Previous status", _status_pill(old_status)),
        ("New status",      _status_pill(new_status)),
        ("Severity",        _severity_pill(severity)),
    ]
    if agent_name:
        rows.append(("Handled by", agent_name))
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"Ticket status updated — {ticket_number}")
        + _BOPEN
        + f"<p>Hi {customer_name},</p>"
        + "<p>The status of your support ticket has been updated.</p>"
        + _info_table(*rows)
        + note_html
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number}")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_agent_comment(ticket_number, ticket_title, status, severity,
                          agent_name, comment_body, customer_name, from_name):
    subject = f"[{ticket_number}] New reply from our support team"
    text = (
        f"Hi {customer_name},\n\n"
        f"{agent_name} from our support team has posted a reply on your ticket.\n\n"
        f"  Ticket   : {ticket_number}\n"
        f"  Subject  : {ticket_title}\n"
        f"  Status   : {status.replace('_', ' ').title()}\n"
        f"  Severity : {severity}\n\n"
        f"Their message:\n"
        f"──────────────────────────────\n"
        f"{comment_body}\n"
        f"──────────────────────────────\n\n"
        f"You can reply directly to this email to respond, or log in to the portal "
        f"to view the full conversation history.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"New reply on ticket {ticket_number}")
        + _BOPEN
        + f"<p>Hi {customer_name},</p>"
        + f"<p><strong>{agent_name}</strong> from our support team has posted a reply on your ticket.</p>"
        + _info_table(
            ("Ticket",   f'<span class="badge">{ticket_number}</span>'),
            ("Subject",  ticket_title),
            ("Status",   _status_pill(status)),
            ("Severity", _severity_pill(severity)),
            ("Agent",    agent_name),
        )
        + f'<div class="comment-box">{comment_body}</div>'
        + "<p>You can reply directly to this email to respond, or log in to the portal "
        + "to view the full conversation history.</p>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number}")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_customer_comment(ticket_number, ticket_title, customer_name, comment_body, from_name):
    subject = f"[{ticket_number}] Customer replied — action required"
    text = (
        f"Hi,\n\n"
        f"{customer_name} has posted a new reply on ticket [{ticket_number}].\n\n"
        f"  Ticket   : {ticket_number}\n"
        f"  Subject  : {ticket_title}\n"
        f"  Customer : {customer_name}\n\n"
        f"Their message:\n"
        f"──────────────────────────────\n"
        f"{comment_body}\n"
        f"──────────────────────────────\n\n"
        f"Please log in to the portal to review and respond.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"Customer replied — {ticket_number}")
        + _BOPEN
        + "<p>Hi,</p>"
        + f"<p><strong>{customer_name}</strong> has posted a new reply on their ticket.</p>"
        + _info_table(
            ("Ticket",   f'<span class="badge">{ticket_number}</span>'),
            ("Subject",  ticket_title),
            ("Customer", customer_name),
        )
        + f'<div class="comment-box">{comment_body}</div>'
        + "<p>Please log in to the portal to review and respond.</p>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number} — internal agent notification")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_assigned_agent(ticket_number, ticket_title, status, severity,
                           customer_name, agent_name, from_name):
    """Direct agent assignment — a specific agent is assigned to the ticket."""
    subject = f"[{ticket_number}] Ticket assigned "
    text = (
        f"Hi {agent_name},\n\n"
        f"A support ticket has been assigned to you and requires your attention.\n\n"
        f"  Ticket   : {ticket_number}\n"
        f"  Subject  : {ticket_title}\n"
        f"  Customer : {customer_name}\n"
        f"  Status   : {status.replace('_', ' ').title()}\n"
        f"  Severity : {severity}\n\n"
        f"Please log in to the portal to review the ticket details and begin working on it.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"Ticket assigned to you — {ticket_number}")
        + _BOPEN
        + f"<p>Hi {agent_name},</p>"
        + "<p>A support ticket has been assigned to you and requires your attention.</p>"
        + _info_table(
            ("Ticket",      f'<span class="badge">{ticket_number}</span>'),
            ("Subject",     ticket_title),
            ("Customer",    customer_name),
            ("Status",      _status_pill(status)),
            ("Severity",    _severity_pill(severity)),
            ("Assigned to", agent_name),
        )
        + "<p>Please log in to the portal to review the ticket details and begin working on it.</p>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number} — agent assignment notification")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_assigned_lead(ticket_number, ticket_title, status, severity,
                          customer_name, lead_name, from_name):
    """
    Team-lead routing notification — ticket is in the team queue with no
    individual assignee. The lead must triage and assign it.
    """
    subject = f"[{ticket_number}] Ticket routed to your team — review required"
    text = (
        f"Hi {lead_name},\n\n"
        f"A support ticket has been routed to your team queue and is awaiting assignment.\n\n"
        f"  Ticket   : {ticket_number}\n"
        f"  Subject  : {ticket_title}\n"
        f"  Customer : {customer_name}\n"
        f"  Status   : {status.replace('_', ' ').title()}\n"
        f"  Severity : {severity}\n"
        f"  Assignee : Unassigned — team queue\n\n"
        f"No agent has been automatically assigned. Please review the ticket and assign it "
        f"to the appropriate team member, or self-claim it if necessary.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"Ticket routed to your team — {ticket_number}")
        + _BOPEN
        + f"<p>Hi {lead_name},</p>"
        + "<p>A support ticket has been routed to your team queue and is awaiting assignment.</p>"
        + _info_table(
            ("Ticket",      f'<span class="badge">{ticket_number}</span>'),
            ("Subject",     ticket_title),
            ("Customer",    customer_name),
            ("Status",      _status_pill(status)),
            ("Severity",    _severity_pill(severity)),
            ("Assigned to", '<em style="color:#888">Unassigned — team queue</em>'),
        )
        + '<div class="alert-box"><strong>Action required:</strong> No agent has been automatically '
        + "assigned to this ticket. Please review and assign it to the appropriate team member, "
        + "or self-claim if necessary.</div>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number} — team lead notification")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_sla_breached(ticket_number, ticket_title, status, severity,
                         customer_name, breach_type, lead_name, from_name):
    """
    Escalation alert to a team lead when an SLA deadline is missed.
    The ticket has been moved to the lead's team queue; immediate action required.
    """
    breach_label = breach_type.replace("_", " ").title()
    subject = f"[{ticket_number}] URGENT — {breach_label} SLA breached"
    text = (
        f"Hi {lead_name},\n\n"
        f"URGENT: Ticket [{ticket_number}] has breached its {breach_label} SLA "
        f"and escalated.\n\n"
        f"  Ticket      : {ticket_number}\n"
        f"  Subject     : {ticket_title}\n"
        f"  Customer    : {customer_name}\n"
        f"  Status      : {status.replace('_', ' ').title()}\n"
        f"  Severity    : {severity}\n"
        f"  Breach type : {breach_label} SLA\n\n"
        f"The ticket has been moved to your team queue. Please assign it to an available "
        f"agent immediately.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"\u26a0 SLA breach — {ticket_number}")
        + _BOPEN
        + f"<p>Hi {lead_name},</p>"
        + f"<p><strong>URGENT:</strong> Ticket <strong>{ticket_number}</strong> has breached its "
        + f"<strong>{breach_label} SLA</strong> and requires immediate escalation action.</p>"
        + _info_table(
            ("Ticket",      f'<span class="badge">{ticket_number}</span>'),
            ("Subject",     ticket_title),
            ("Customer",    customer_name),
            ("Status",      _status_pill(status)),
            ("Severity",    _severity_pill(severity)),
            ("Breach type", f"<strong>{breach_label} SLA</strong>"),
        )
        + '<div class="alert-box"><strong>Action required:</strong> The ticket has been escalated '
        + "to your team queue. Please assign it to an available agent immediately or escalate further.</div>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number} — SLA escalation alert")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_auto_closed(ticket_number, ticket_title, customer_name, from_name):
    subject = f"[{ticket_number}] Your ticket has been automatically closed"
    text = (
        f"Hi {customer_name},\n\n"
        f"Your support ticket has been automatically closed after being marked as resolved "
        f"with no further activity for an extended period.\n\n"
        f"  Ticket  : {ticket_number}\n"
        f"  Subject : {ticket_title}\n"
        f"  Status  : Closed\n\n"
        f"If your issue has not been fully resolved or you need further assistance, "
        f"please open a new ticket and our team will be happy to help.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title=f"Ticket automatically closed — {ticket_number}")
        + _BOPEN
        + f"<p>Hi {customer_name},</p>"
        + "<p>Your support ticket has been automatically closed after being marked as resolved "
        + "with no further activity for an extended period.</p>"
        + _info_table(
            ("Ticket",  f'<span class="badge">{ticket_number}</span>'),
            ("Subject", ticket_title),
            ("Status",  _status_pill("CLOSED")),
        )
        + "<p>If your issue has not been fully resolved or you need further assistance, "
        + "please open a new ticket and our team will be happy to help.</p>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text=f"Ticket {ticket_number} — auto-close notification")
        + _HTML_CLOSE
    )
    return subject, text, html


def _draft_clarification(original_subject, customer_name, missing_fields, from_name):
    clean_original = re.sub(r"^(re|fwd?):\s*", "", original_subject, flags=re.IGNORECASE).strip()
    subject = f"Re: {clean_original}"
    bullet_text = "\n".join(f"  \u2022 {m}" for m in missing_fields)
    bullet_html = "".join(f"<li>{m}</li>" for m in missing_fields)
    text = (
        f"Hi {customer_name},\n\n"
        f"Thank you for reaching out to our support team.\n\n"
        f"We received your request but need a bit more information before we can "
        f"create a ticket and assign it to the right team.\n\n"
        f"Please reply with the following details:\n"
        f"{bullet_text}\n\n"
        f"Once we have this information we will create your ticket and follow up promptly.\n\n"
        f"— {from_name}\n"
    )
    html = (
        _HTML_OPEN
        + _HDR.format(title="We need a little more information")
        + _BOPEN
        + f"<p>Hi {customer_name},</p>"
        + "<p>Thank you for reaching out to our support team.</p>"
        + "<p>We received your request but need a bit more information before we can "
        + "create a ticket and assign it to the right team. "
        + "Please reply with the following details:</p>"
        + f"<ul style='margin:12px 0 20px 20px;padding:0;color:#444'>{bullet_html}</ul>"
        + "<p>Once we have this information we will create your ticket and follow up promptly.</p>"
        + f"<p>— {from_name}</p>"
        + _BCLOSE
        + _FTR.format(text="Automated message from TicketGenie Support.")
        + _HTML_CLOSE
    )
    return subject, text, html


# ── Service ────────────────────────────────────────────────────────────────────

class EmailNotificationService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = NotificationLogRepository(db)
        self._thread_repo = EmailThreadRepository(db)
        self._config: dict | None = None

    async def _ensure_config(self) -> dict:
        """
        Load and cache SMTP configuration for the lifetime of this service instance.

        Resolution order:
          1. In-memory cache (_config) — avoids repeated DB queries within one
             request/task lifecycle.
          2. Database (EmailConfigService) — used when an active config row exists
             with the required smtp_host and smtp_user fields populated.
          3. Environment variables — final fallback so the service degrades
             gracefully when no DB config is present (e.g. first-run / dev).
        """
        if self._config is not None:
            return self._config

        try:
            service = EmailConfigService(self._db)
            db_config = await service.get_decrypted_config()
            if (
                db_config
                and db_config.get("is_active")
                and db_config.get("smtp_host")
                and db_config.get("smtp_user")
            ):
                logger.info("email_service: using database SMTP configuration")
                self._config = db_config
                return self._config
        except Exception as exc:
            logger.warning("email_service: failed to load database config: %s", exc)

        logger.info("email_service: using environment SMTP configuration")
        s = get_settings()
        self._config = {
            "smtp_host":      s.SMTP_HOST,
            "smtp_port":      s.SMTP_PORT,
            "smtp_user":      s.SMTP_USER,
            "smtp_password":  s.SMTP_PASSWORD,
            "smtp_from_name": getattr(s, "SMTP_FROM_NAME", "Support Team"),
        }
        return self._config

    # ── Lifecycle notifications ────────────────────────────────────────────────

    async def send_ticket_created(
        self, req: TicketCreatedRequest, recipient_email: str
    ) -> None:
        config = await self._ensure_config()
        subject, text, html = _draft_ticket_created(
            req.ticket_number, req.ticket_title,
            config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.customer_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type=EventType.CREATED.value,
        )

    async def send_status_changed(
        self, req: StatusChangedRequest, recipient_email: str, customer_name: str
    ) -> None:
        config = await self._ensure_config()
        subject, text, html = _draft_status_changed(
            req.ticket_number, req.ticket_title,
            req.old_status, req.new_status, req.severity,
            req.agent_name, customer_name,
            config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.customer_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type=EventType.STATUS_CHANGED.value,
        )

    async def send_agent_comment(
        self, req: AgentCommentRequest, recipient_email: str, customer_name: str
    ) -> None:
        config = await self._ensure_config()
        subject, text, html = _draft_agent_comment(
            req.ticket_number, req.ticket_title,
            req.status, req.severity, req.agent_name, req.comment_body,
            customer_name, config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.customer_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type="AGENT_COMMENT",
        )

    async def send_customer_comment(
        self, req: CustomerCommentRequest, recipient_email: str
    ) -> None:
        config = await self._ensure_config()
        subject, text, html = _draft_customer_comment(
            req.ticket_number, req.ticket_title, req.customer_name,
            req.comment_body, config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.assignee_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type="CUSTOMER_COMMENT",
        )

    async def send_ticket_assigned(
        self, req: TicketAssignedRequest, recipient_email: str, agent_name: str
    ) -> None:
        """
        Notification to an individual agent when a ticket is directly assigned to them.
        For team-lead routing fallback notifications use send_ticket_assigned_to_lead.
        """
        config = await self._ensure_config()
        subject, text, html = _draft_assigned_agent(
            req.ticket_number, req.ticket_title,
            req.status, req.severity, req.customer_name, agent_name,
            config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.assignee_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type=EventType.ASSIGNED.value,
        )

    async def send_ticket_assigned_to_lead(
        self, req: TicketAssignedRequest, recipient_email: str, lead_name: str
    ) -> None:
        """
        Lead-specific routing notification when a ticket is placed in the team
        queue with no individual assignee (AI routing fallback scenario).
        The lead must triage and assign it to an available agent.
        """
        config = await self._ensure_config()
        subject, text, html = _draft_assigned_lead(
            req.ticket_number, req.ticket_title,
            req.status, req.severity, req.customer_name, lead_name,
            config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.assignee_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type=EventType.ASSIGNED.value,
        )

    async def send_sla_breached(
        self, req: SLABreachedRequest, recipient_email: str, lead_name: str
    ) -> None:
        """
        Escalation alert to a team lead when an SLA deadline is breached.
        Full ticket context + breach type + amber action-required callout box.
        """
        config = await self._ensure_config()
        subject, text, html = _draft_sla_breached(
            req.ticket_number, req.ticket_title,
            req.status, req.severity, req.customer_name, req.breach_type,
            lead_name, config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.lead_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type=EventType.SLA_BREACHED.value,
        )

    async def send_auto_closed(
        self, req: AutoClosedRequest, recipient_email: str, customer_name: str
    ) -> None:
        config = await self._ensure_config()
        subject, text, html = _draft_auto_closed(
            req.ticket_number, req.ticket_title,
            customer_name, config.get("smtp_from_name", "Support Team"),
        )
        await self._deliver(
            config=config, ticket_id=req.ticket_id,
            recipient_id=req.customer_id, recipient_email=recipient_email,
            subject=subject, body=text, html_body=html,
            event_type="AUTO_CLOSED",
        )

    # ── Email ingest pipeline outbound emails ──────────────────────────────────

    async def send_ticket_ack(
        self,
        *,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        customer_name: str,
        ticket_number: str,
        original_message_id: str,
    ) -> None:
        config = await self._ensure_config()
        from_name = config.get("smtp_from_name", "Support Team")
        html_body = _ACK_HTML.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            from_name=from_name,
        )
        text_body = _ACK_TEXT.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            from_name=from_name,
        )
        await self._deliver(
            config=config,
            ticket_id=ticket_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=f"[{ticket_number}] Support request received",
            body=text_body,
            html_body=html_body,
            event_type="EMAIL_INGEST_ACK",
            in_reply_to=original_message_id,
            references=original_message_id,
        )
        logger.info(
            "email_service: sent ingest ACK to=%s ticket=%s",
            recipient_email, ticket_number,
        )

    async def send_continue_in_ui(
        self,
        *,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        customer_name: str,
        customer_role: str,
        ticket_number: str,
        original_message_id: str,
    ) -> None:
        from src.utils.portal_token import generate_portal_token

        config = await self._ensure_config()
        from_name = config.get("smtp_from_name", "Support Team")

        s = get_settings()
        base_url = getattr(s, "APP_BASE_URL", "http://localhost").rstrip("/")
        ticket_url = f"{base_url}/login"

        html_body = _CONTINUE_HTML.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            ticket_url=ticket_url,
            from_name=from_name,
        )
        text_body = _CONTINUE_TEXT.format(
            customer_name=customer_name,
            ticket_number=ticket_number,
            ticket_url=ticket_url,
            from_name=from_name,
        )
        await self._deliver(
            config=config,
            ticket_id=ticket_id,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            subject=f"[{ticket_number}] Continue your conversation on the support portal by using your credentials",
            body=text_body,
            html_body=html_body,
            event_type="EMAIL_INGEST_CONTINUE_UI",
            in_reply_to=original_message_id,
            references=original_message_id,
        )
        logger.info(
            "email_service: sent continue-in-UI to=%s ticket=%s url=%s",
            recipient_email, ticket_number, ticket_url,
        )

    async def send_clarification_request(
        self,
        *,
        recipient_email: str,
        customer_name: str,
        original_message_id: str,
        original_subject: str,
        missing_fields: list[str],
    ) -> None:
        config = await self._ensure_config()
        from_name = config.get("smtp_from_name", "Support Team")

        subject, text, html = _draft_clarification(
            original_subject, customer_name, missing_fields, from_name,
        )

        outbound_domain = config.get("smtp_user", "support@ticketgenie.ai").split("@")[-1]
        from email.utils import make_msgid as _make_msgid
        outbound_mid = _make_msgid(domain=outbound_domain)

        if config.get("smtp_user"):
            import asyncio as _asyncio
            from functools import partial as _partial
            loop = _asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                _partial(
                    self._smtp_send,
                    config=config,
                    to=recipient_email,
                    subject=subject,
                    body=text,
                    html_body=html,
                    message_id=outbound_mid,
                    in_reply_to=original_message_id,
                    references=original_message_id,
                ),
            )
        else:
            logger.info(
                "email_service [DEV]: clarify to=%s subject=%r\n%s",
                recipient_email, subject, text,
            )
        logger.info(
            "email_service: sent clarification request to=%s subject=%r missing=%s",
            recipient_email, original_subject, missing_fields,
        )

    async def _deliver(
        self,
        config: dict,
        ticket_id: int,
        recipient_id: str,
        recipient_email: str,
        subject: str,
        body: str,
        event_type: str,
        html_body: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        status = NotificationStatus.PENDING

        smtp_domain = config.get("smtp_user", "support@ticketgenie.ai").split("@")[-1]
        outbound_message_id = make_msgid(domain=smtp_domain)

        try:
            if config.get("smtp_user"):
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    partial(
                        self._smtp_send,
                        config=config,
                        to=recipient_email,
                        subject=subject,
                        body=body,
                        html_body=html_body,
                        in_reply_to=in_reply_to,
                        references=references,
                        message_id=outbound_message_id,
                    ),
                )
            else:
                logger.info(
                    "email_service [DEV]: to=%s subject=%r\n%s",
                    recipient_email, subject, body,
                )
            status = NotificationStatus.SENT
        except Exception as exc:
            logger.exception(
                "email_service: failed event=%s to=%s: %s",
                event_type, recipient_email, exc,
            )
            status = NotificationStatus.FAILED

        await self._repo.add(NotificationLog(
            ticket_id=ticket_id,
            recipient_user_id=recipient_id,
            channel=NotificationChannel.EMAIL,
            event_type=event_type,
            status=status,
            sent_at=now if status == NotificationStatus.SENT else None,
        ))

        # Record outbound email so customer replies can be matched back to this ticket
        # via the In-Reply-To header in email_ingestion_service._find_existing_ticket.
        if status == NotificationStatus.SENT:
            try:
                await self._thread_repo.add(EmailThread(
                    ticket_id=ticket_id,
                    message_id=outbound_message_id,
                    in_reply_to=in_reply_to,
                    raw_subject=subject,
                    sender_email=config.get("smtp_user", ""),
                    direction=EmailDirection.OUTBOUND,
                    raw_body_text=body,
                    received_at=now,
                    processed_at=now,
                ))
            except Exception:
                logger.exception(
                    "email_service: failed to record outbound thread row "
                    "ticket_id=%s — email was still sent", ticket_id
                )

    def _smtp_send(
        self,
        *,
        config: dict,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        message_id: str | None = None,
    ) -> None:
        """
        Sync SMTP send — called via run_in_executor so it never blocks the event loop.

        Builds multipart/alternative (plain-text + optional HTML).
        Threading headers (Message-ID, In-Reply-To, References) set when provided.

        Port 465 → implicit SSL (SMTP_SSL).
        Port 587 or any other → STARTTLS.
        """
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        msg["Subject"] = subject
        msg["From"]    = f"{config.get('smtp_from_name', 'Support Team')} <{config['smtp_user']}>"
        msg["To"]      = to

        if message_id:
            msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        smtp_host = config["smtp_host"]
        smtp_port = int(config.get("smtp_port", 587))
        smtp_user = config["smtp_user"]
        smtp_pass = config["smtp_password"]

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
                smtp.login(smtp_user, smtp_pass)
                smtp.sendmail(smtp_user, to, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(smtp_user, smtp_pass)
                smtp.sendmail(smtp_user, to, msg.as_string())

        logger.info("email_service: sent event to=%s subject=%r", to, subject)