"""
Flinza — Email Queue Processor
Background thread that drains queued emails with random intervals.
Smart-hours support: only sends during configured business hours.
"""

import time
import random
import threading
import logging
from datetime import datetime

import database as db
import email_sender

logger = logging.getLogger(__name__)

_queue_running  = False
_queue_thread   = None
_queue_paused   = False
_last_status    = "idle"


def start_queue(status_callback=None):
    """Start background queue processor."""
    global _queue_thread, _queue_running, _queue_paused
    if _queue_running:
        return "Queue already running"
    _queue_paused  = False
    _queue_running = True
    _queue_thread  = threading.Thread(
        target=_process_loop, args=(status_callback,), daemon=True
    )
    _queue_thread.start()
    return "Queue processor started"


def stop_queue():
    global _queue_running
    _queue_running = False
    return "Queue stopping…"


def pause_queue():
    global _queue_paused
    _queue_paused = True
    return "Queue paused"


def resume_queue():
    global _queue_paused
    _queue_paused = False
    return "Queue resumed"


def is_running() -> bool:
    return _queue_running


def is_paused() -> bool:
    return _queue_paused


def get_status() -> str:
    return _last_status


def _notify(callback, msg: str):
    global _last_status
    _last_status = msg
    logger.info(f"Queue: {msg}")
    if callback:
        try:
            callback(msg)
        except Exception:
            pass


def _in_smart_hours() -> bool:
    """Returns True if current hour is within configured sending window."""
    if db.get_setting("smart_hours_enabled", "0") != "1":
        return True
    now_hour = datetime.now().hour
    try:
        start = int(db.get_setting("smart_hours_start", "9"))
        end   = int(db.get_setting("smart_hours_end", "18"))
        return start <= now_hour < end
    except Exception:
        return True


def _process_loop(status_callback=None):
    global _queue_running, _queue_paused

    _notify(status_callback, "Queue processor started")

    min_interval = int(db.get_setting("min_interval_seconds", "120"))
    max_interval = int(db.get_setting("max_interval_seconds", "420"))

    while _queue_running:
        # Re-read interval settings in case they were changed
        try:
            min_interval = int(db.get_setting("min_interval_seconds", "120"))
            max_interval = int(db.get_setting("max_interval_seconds", "420"))
        except Exception:
            pass

        # Respect smart-hours window
        if not _in_smart_hours():
            _notify(status_callback, "⏰ Outside smart-hours window — waiting…")
            _sleep_interruptible(300)
            continue

        # Respect pause
        if _queue_paused:
            _sleep_interruptible(10)
            continue

        # Get queued emails
        queued = db.get_queued_emails(limit=200)
        if not queued:
            _notify(status_callback, "✅ Queue empty — all done!")
            break

        # Check remaining capacity
        remaining = db.total_remaining_today()
        if remaining <= 0:
            _notify(status_callback, "🚫 All accounts at daily limit — will resume tomorrow.")
            break

        _notify(status_callback, f"📬 {len(queued)} emails queued | {remaining} capacity remaining today")

        for email_row in queued:
            if not _queue_running or _queue_paused:
                break

            if not _in_smart_hours():
                _notify(status_callback, "⏰ Outside smart-hours — pausing until window opens")
                break

            remaining = db.total_remaining_today()
            if remaining <= 0:
                _notify(status_callback, f"🚫 Daily limit hit. {len(queued)} still in queue.")
                break

            to_email  = email_row["to_email"]
            subject   = email_row["subject"]
            body      = email_row["body"]
            email_id  = email_row["id"]
            lead_id   = email_row["lead_id"]
            msg_type  = email_row["message_type"]

            preferred_from = email_row.get("from_account")
            account = None
            if preferred_from:
                all_accts = db.get_all_accounts()
                for a in all_accts:
                    if a.get("email") == preferred_from or a.get("from_email") == preferred_from:
                        if (a.get("sent_today") or 0) < (a.get("daily_limit") or 50):
                            account = dict(a)
                            break
            if not account:
                account = db.get_next_available_account()

            if not account:
                _notify(status_callback, "No accounts available — pausing")
                break

            # Current active rotating IP node info
            node_tag = ""
            try:
                import ip_rotator
                cur_node = ip_rotator.peek_active_node()
                if cur_node:
                    node_tag = f" 📱 [{cur_node.get('name')}: {cur_node.get('ip_address')}]"
            except Exception:
                pass

            _notify(status_callback, f"📤 Sending to {to_email} via {account['from_email']}{node_tag}…")

            result = email_sender.send_email_now(to_email, subject, body, account)

            if result["success"]:
                db.mark_email_sent(email_id, result.get("message_id"), account["from_email"])
                if lead_id:
                    db.add_conversation_message(lead_id, "us", f"[{msg_type.upper()}] Subject: {subject}\n\n{body}")
                    # Update lead stage if still 'new'
                    lead = db.get_lead(lead_id)
                    if lead and lead["stage"] == "new":
                        db.update_lead_stage(lead_id, "contacted")
                    # Schedule first followup if opener
                    if msg_type == "opener":
                        db.schedule_first_followup(lead_id)
                db.log_activity("sent", f"To: {to_email} | From: {account['from_email']}{node_tag}")
                _notify(status_callback, f"✅ Sent → {to_email}{node_tag}")
            else:
                db.mark_email_failed(email_id, result.get("error"))
                _notify(status_callback, f"❌ Failed → {to_email}: {result.get('error')}")

            # Random delay between sends
            delay = random.randint(min_interval, max_interval)
            _notify(status_callback, f"⏳ Waiting {delay}s before next send…")
            _sleep_interruptible(delay)

    _queue_running = False
    _notify(status_callback, "Queue processor stopped")


def _sleep_interruptible(seconds: int):
    """Sleep in 1-second chunks so we can stop/pause cleanly."""
    for _ in range(seconds):
        if not _queue_running:
            break
        time.sleep(1)
