"""
Flinza — Reply Watcher
Polls Gmail via IMAP to detect replies from leads.
Detects auto-replies, deduplicates, generates AI draft, notifies via callback.
"""

import imaplib
import email
import logging
import re
import time
import threading
import hashlib
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
            check_minutes = int(db.get_setting("reply_check_minutes", "5"))
            _check_all_accounts(notify_callback)
            db.record_reply_check()
        except Exception as e:
            logger.error(f"Reply watcher loop error: {e}")

        sleep_total = check_minutes * 60
        for _ in range(sleep_total):
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


def _check_account(account, notify_callback):
    email_addr = account["email"]
    password   = account["app_password"]

    last_check = _last_check_times.get(email_addr)
    if not last_check:
        last_check = datetime.now() - timedelta(hours=1)

    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993) as mail:
            mail.login(email_addr, password)
            mail.select("inbox")

            since_date = last_check.strftime("%d-%b-%Y")
            status, data = mail.search(None, f'(SINCE "{since_date}")')
            if status != "OK":
                return

            msg_ids = data[0].split()
            for msg_id in msg_ids[-50:]:  # last 50 max
                try:
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
    if status != "OK":
        return

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    from_header   = msg.get("From", "")
    sender_email  = _extract_email(from_header)
    to_email      = _extract_email(msg.get("To", ""))
    if not sender_email:
        return

    # Skip messages we sent
    accounts = [a["email"].lower() for a in db.get_all_accounts()]
    aliases  = [a["alias"].lower() for a in db.get_all_aliases()]
    if sender_email.lower() in accounts or sender_email.lower() in aliases:
        return

    # Check if this sender is a lead we've emailed
    lead = db.get_lead_by_email(sender_email)
    if not lead:
        normalized = _normalize_gmail(sender_email)
        lead = db.get_lead_by_email(normalized)
    if not lead:
        return  # Not a tracked lead

    subject = _decode_header_val(msg.get("Subject", ""))
    body    = _extract_body(msg)

    # Skip auto-replies
    if _is_auto_reply(subject, body):
        logger.info(f"Skipping auto-reply from {sender_email}")
        return

    # Dedup
    if db.reply_already_logged(lead["id"], subject, body):
        return

    # Classify intent & check for unsubscribe
    import email_toolkit
    intent_data = email_toolkit.classify_reply_intent(subject, body)
    intent_label = intent_data.get("intent", "general_reply")
    sentiment = intent_data.get("sentiment", "neutral")

    # If lead asked to unsubscribe — auto-blacklist & cancel
    is_unsub = intent_data.get("is_unsubscribe", False)
    if is_unsub:
        db.handle_unsubscribe(sender_email, reason="lead_reply_unsubscribe")
        logger.info(f"Auto-unsubscribed and blacklisted {sender_email} based on reply text.")

    # Generate AI reply draft (unless they asked to unsubscribe)
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

    # Log reply
    reply_id = db.log_reply(
        lead["id"], sender_email, subject, body,
        ai_draft_subject=ai_draft_subject,
        ai_draft_body=ai_draft_body,
    )

    # Update intent & sentiment in replies table
    conn = db.get_db()
    conn.execute("UPDATE replies SET intent=?, sentiment=? WHERE id=?", (intent_label, sentiment, reply_id))
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


# ═══════════════════════════════════════════════════════════════
#                        HELPERS
# ═══════════════════════════════════════════════════════════════

def _extract_email(header_value: str) -> str | None:
    match = re.search(r'[\w._%+\-]+@[\w.\-]+\.\w+', header_value)
    return match.group(0).lower() if match else None


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


def _extract_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())

    return _strip_quoted(body).strip()


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
