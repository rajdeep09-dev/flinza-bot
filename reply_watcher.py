"""
Flinza — Reply Watcher
Polls Gmail via IMAP to detect replies from leads.
Detects auto-replies, deduplicates, generates AI draft, notifies via callback.
"""

import imaplib
import email
import email.utils
import logging
import re
import time
import threading
import hashlib
import html
from email.header import decode_header
from datetime import datetime, timedelta

import database as db
import ai_router

logger = logging.getLogger(__name__)

_watcher_running  = False
_watcher_thread   = None
_last_check_times = {}   # email_addr → datetime of last IMAP check


# ═══════════════════════════════════════════════════════════════
#                     PUBLIC API
# ═══════════════════════════════════════════════════════════════

def start_watcher(notify_callback):
    """Start background IMAP watcher."""
    global _watcher_thread, _watcher_running
    if _watcher_running:
        return "Reply watcher already running"
    _watcher_running = True
    _watcher_thread = threading.Thread(
        target=_watch_loop, args=(notify_callback,), daemon=True
    )
    _watcher_thread.start()
    return "Reply watcher started"


def stop_watcher():
    global _watcher_running
    _watcher_running = False
    return "Reply watcher stopping…"


def is_running() -> bool:
    return _watcher_running


def check_now(notify_callback=None) -> list:
    """Manual one-time check across all accounts. Returns list of new reply dicts."""
    new_replies = []

    def capture(reply_data):
        new_replies.append(reply_data)
        if notify_callback:
            notify_callback(reply_data)

    try:
        _check_all_accounts(capture)
        db.record_reply_check()
    except Exception as e:
        logger.error(f"Manual reply check error: {e}")
    return new_replies


# ═══════════════════════════════════════════════════════════════
#                     WATCH LOOP
# ═══════════════════════════════════════════════════════════════

def _watch_loop(notify_callback):
    global _watcher_running
    while _watcher_running:
        try:
            check_seconds = int(db.get_setting("reply_check_seconds", "45"))
            _check_all_accounts(notify_callback)
            db.record_reply_check()
        except Exception as e:
            logger.error(f"Reply watcher loop error: {e}")

        for _ in range(check_seconds):
            if not _watcher_running:
                break
            time.sleep(1)


# ═══════════════════════════════════════════════════════════════
#                     IMAP CHECKING
# ═══════════════════════════════════════════════════════════════

def _check_all_accounts(notify_callback):
    accounts = db.get_all_accounts()
    for account in accounts:
        if not account["active"]:
            continue
        try:
            _check_account(account, notify_callback)
        except Exception as e:
            logger.warning(f"Failed to check {account['email']}: {e}")


def _check_account(account, notify_callback, max_messages=None):
    email_addr = account["email"]
    password   = account["app_password"]

    conn = db.get_db()
    existing_msg_ids = set(r[0] for r in conn.execute("SELECT message_id FROM replies WHERE message_id IS NOT NULL").fetchall())
    conn.close()

    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993) as mail:
            mail.login(email_addr, password)
            mail.select("inbox")

            status, data = mail.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                return

            msg_ids = data[0].split()
            # Retrieve all messages in the connected master email or up to max_messages
            check_ids = msg_ids if not max_messages else msg_ids[-max_messages:]
            # Reverse so newest emails are processed first
            for msg_id in reversed(check_ids):
                try:
                    # Fast peek at Message-ID to skip already stored messages without downloading full payload
                    status, peek_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                    if status == "OK" and peek_data and peek_data[0]:
                        hdr_chunk = peek_data[0][1].decode("utf-8", errors="replace")
                        m = re.search(r"Message-ID:\s*(<[^>]+>|\S+)", hdr_chunk, re.I)
                        if m and m.group(1).strip() in existing_msg_ids:
                            continue

                    _process_message(mail, msg_id, email_addr, notify_callback)
                except Exception as e:
                    logger.warning(f"Failed to process message {msg_id}: {e}")

            _last_check_times[email_addr] = datetime.now()

    except imaplib.IMAP4.error as e:
        logger.warning(f"IMAP error for {email_addr}: {e}")
    except Exception as e:
        logger.warning(f"Error checking {email_addr}: {e}")


def _process_message(mail, msg_id, our_email, notify_callback):
    status, msg_data = mail.fetch(msg_id, "(RFC822)")
    if status != "OK" or not msg_data or not msg_data[0]:
        return

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    message_id   = (msg.get("Message-ID") or "").strip() or None
    from_header  = msg.get("From", "")
    sender_email = _extract_email(from_header)
    to_email     = (msg.get("Delivered-To") or msg.get("X-Forwarded-To") or _extract_email(msg.get("To", "")) or our_email).strip().lower()
    if not sender_email:
        return

    # Skip loopback to self only if from AND to are our own email
    if sender_email.lower() == our_email.lower() and to_email == our_email.lower():
        return

    subject = _decode_header_val(msg.get("Subject", ""))
    body    = _extract_body(msg)

    # Parse real received timestamp from Date header
    received_at = None
    date_hdr = msg.get("Date")
    if date_hdr:
        try:
            dt = email.utils.parsedate_to_datetime(date_hdr)
            received_at = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            received_at = None

    # Check deduplication
    if db.is_duplicate_reply(sender_email, subject, body, message_id):
        return

    # Check if this sender is an actual lead in our CRM/outreach database
    lead = db.get_lead_by_email(sender_email)
    if not lead:
        normalized = _normalize_gmail(sender_email)
        lead = db.get_lead_by_email(normalized)

    # --- SEPARATION OF LEAD REPLIES vs ALL INBOXES ---
    if lead and lead.get("company") != "Direct Inbound":
        # 1. REAL LEAD REPLY -> Link lead_id, classify intent, generate AI draft, advance CRM stage
        import email_toolkit
        intent_data = email_toolkit.classify_reply_intent(subject, body)
        intent_label = intent_data.get("intent", "general_inbound")
        sentiment = intent_data.get("sentiment", "neutral")
        is_unsub = intent_data.get("is_unsubscribe", False)

        lead_id = lead["id"]
        if is_unsub:
            db.handle_unsubscribe(sender_email, reason="lead_reply_unsubscribe")

        ai_draft_subject = None
        ai_draft_body    = None
        if not is_unsub:
            try:
                conversation = db.get_conversation(lead["id"])
                instruction_hint = f"Lead intent is {intent_label}. {intent_data.get('suggested_action', '')}"
                draft = ai_router.generate_reply_draft(
                    lead_info=dict(lead),
                    conversation=conversation,
                    their_reply=body,
                    instruction=instruction_hint
                )
                ai_draft_subject = draft.get("subject")
                ai_draft_body    = draft.get("body")
            except Exception as e:
                logger.error(f"AI draft generation failed: {e}")

        reply_id = db.log_reply(
            lead_id=lead_id,
            from_email=sender_email,
            subject=subject,
            body=body,
            ai_draft_subject=ai_draft_subject,
            ai_draft_body=ai_draft_body,
            message_id=message_id,
            to_email=to_email,
            received_at=received_at
        )

        conn = db.get_db()
        conn.execute("UPDATE replies SET intent=?, sentiment=?, action_taken=? WHERE id=?", (intent_label, sentiment, f"inbound_to_{our_email}", reply_id))
        conn.commit()
        conn.close()

        db.add_conversation_message(lead["id"], "them", f"Subject: {subject}\n\n{body}")
        if not is_unsub:
            db.update_lead_stage(lead["id"], "replied")
        db.cancel_followups(lead["id"])
        db.log_activity("reply_received", f"From: {sender_email} [{intent_label}] | Subj: {subject[:50]}")

        if notify_callback:
            try:
                notify_callback({
                    "reply_id":       reply_id,
                    "lead_id":        lead["id"],
                    "lead_name":      lead["name"],
                    "lead_handle":    lead["handle"],
                    "from_email":     sender_email,
                    "to_email":       to_email,
                    "subject":        subject,
                    "body":           body[:1200],
                    "intent":         intent_label,
                    "sentiment":      sentiment,
                    "is_unsubscribe": is_unsub,
                    "ai_draft_subject": ai_draft_subject,
                    "ai_draft_body":    ai_draft_body[:1200] if ai_draft_body else None,
                })
            except Exception as e:
                logger.warning(f"Failed to fire reply callback: {e}")
    else:
        # 2. GENERAL INCOMING EMAIL in connected master email (alerts, receipts, notifications, inquiries)
        # Store in replies table with lead_id=None so it appears in ALL INBOXES,
        # but NEVER pollutes the CRM leads list or the Leads Inbox!
        reply_id = db.log_reply(
            lead_id=None,
            from_email=sender_email,
            subject=subject,
            body=body,
            ai_draft_subject=None,
            ai_draft_body=None,
            message_id=message_id,
            to_email=to_email,
            received_at=received_at
        )

        conn = db.get_db()
        conn.execute("UPDATE replies SET intent='general_inbound', sentiment='neutral', action_taken=? WHERE id=?", (f"inbound_to_{our_email}", reply_id))
        conn.commit()
        conn.close()
        db.log_activity("inbox_email_received", f"Master {our_email} got email from: {sender_email} | Subj: {subject[:50]}")


# ═══════════════════════════════════════════════════════════════
#                        HELPERS
# ═══════════════════════════════════════════════════════════════

def _extract_email(header_value: str) -> str | None:
    match = re.search(r'[\w._%+\-]+@[\w.\-]+\.\w+', header_value)
    return match.group(0).lower() if match else None


def _extract_name(header_value: str) -> str:
    try:
        from email.utils import parseaddr
        name, addr = parseaddr(header_value)
        return name.strip() or addr.split("@")[0].title()
    except Exception:
        return ""


def _decode_header_val(value: str) -> str:
    if not value:
        return ""
    try:
        parts  = decode_header(value)
        result = ""
        for part, encoding in parts:
            if isinstance(part, bytes):
                result += part.decode(encoding or "utf-8", errors="replace")
            else:
                result += part
        return result
    except Exception:
        return value


def _html_to_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    try:
        text = re.sub(r'(?is)<style.*?>.*?</style>', '', raw_html)
        text = re.sub(r'(?is)<script.*?>.*?</script>', '', text)
        text = re.sub(r'(?is)<head.*?>.*?</head>', '', text)
        text = re.sub(r'(?i)<br\s*/?>', '\n', text)
        text = re.sub(r'(?i)</?(p|div|tr|h\d|li|blockquote)[^>]*>', '\n', text)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html.unescape(text)
        lines = [line.strip() for line in text.splitlines()]
        cleaned = []
        for line in lines:
            if line or (cleaned and cleaned[-1]):
                cleaned.append(line)
        return "\n".join(cleaned).strip()
    except Exception:
        return raw_html


def _extract_body(msg) -> str:
    plain_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and not plain_body:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        plain_body = payload.decode(charset, errors="replace")
                except Exception:
                    pass
            elif ctype == "text/html" and not html_body:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_body = payload.decode(charset, errors="replace")
                except Exception:
                    pass
    else:
        ctype = msg.get_content_type()
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if ctype == "text/html":
                    html_body = decoded
                else:
                    plain_body = decoded
        except Exception:
            raw = str(msg.get_payload())
            if ctype == "text/html":
                html_body = raw
            else:
                plain_body = raw

    if plain_body:
        return _strip_quoted(plain_body).strip()
    elif html_body:
        return _html_to_text(html_body).strip()
    return ""


def _strip_quoted(body: str) -> str:
    lines   = body.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^On .+ wrote:\s*$', stripped):
            break
        if stripped.startswith("From:") and "@" in stripped:
            break
        if stripped in ("--", "— ") or stripped.startswith("-- "):
            break
        cleaned.append(line)
    return "\n".join(cleaned)


def _is_auto_reply(subject: str, body: str) -> bool:
    patterns = [
        "out of office", "automatic reply", "auto reply", "auto-reply",
        "vacation reply", "currently away", "on vacation", "i am out",
        "delivery status", "undeliverable", "mail delivery failed",
        "noreply", "no-reply", "do not reply",
    ]
    subj_l = (subject or "").lower()
    body_l = (body or "").lower()[:300]
    return any(p in subj_l or p in body_l for p in patterns)


def _normalize_gmail(addr: str) -> str:
    local, _, domain = addr.partition("@")
    if domain.lower() in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "").lower().split("+")[0]
    return f"{local}@{domain.lower()}"
