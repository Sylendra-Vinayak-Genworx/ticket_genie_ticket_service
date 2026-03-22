import re
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

_WELCOME_HTML = """\
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
    .cred {{ background: #f0f4ff; border: 1px solid #c8d4f0; border-radius: 4px;
             padding: 16px 20px; font-family: monospace; font-size: 14px;
             margin: 16px 0; line-height: 2; }}
    .btn  {{ display: inline-block; background: #2563eb; color: #fff !important;
             padding: 12px 28px; border-radius: 6px; text-decoration: none;
             font-weight: 600; font-size: 14px; margin: 8px 0; }}
    .ftr  {{ padding: 16px 36px; background: #fafaf8;
             color: #999; font-size: 12px; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr"><h1>Welcome to {from_name}</h1></div>
    <div class="body">
      <p>Hi {customer_name},</p>
      <p>
        We received your support request and automatically created a portal
        account so you can track your ticket and get faster help in the future.
      </p>
      <p>Your login credentials:</p>
      <div class="cred">
        <strong>Email:</strong> {email}<br/>
        <strong>Temporary Password:</strong> {temp_password}
      </div>
      <p>
        <a href="{login_url}" class="btn">Sign in to the portal →</a>
      </p>
      <p>
      
        Your support ticket <strong>{ticket_number}</strong> is already waiting for you there.
      </p>
      <p>— {from_name}</p>
    </div>
    <div class="ftr">
      If you did not send a support email to us, please ignore this message.
    </div>
  </div>
</body>
</html>
"""

_WELCOME_TEXT = (
    "Hi {customer_name},\n\n"
    "We received your support request and created a portal account for you.\n\n"
    "Login credentials:\n"
    "  Email:              {email}\n"
    "  Temporary Password: {temp_password}\n\n"
    "Sign in at: {login_url}\n\n"
    
    "Your ticket {ticket_number} is already waiting for you in the portal.\n\n"
    "— {from_name}\n"
)