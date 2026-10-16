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


def _in_smart_hours(lead: dict = None) -> bool:
    """
    Returns True if current time is within configured sending window.
    Supports country-specific timetables (US, UK, UAE, AU, CA, IN, etc.) via ZoneInfo.
    """
    if db.get_setting("smart_hours_enabled", "0") != "1":
        return True

    # 1. Country-specific business hours check
    if lead:
        try:
            import json
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tz

            c_code = (lead.get("country") or "").strip().upper()
            email_addr = (lead.get("email") or "").lower()
            if not c_code and "@" in email_addr:
                tld = email_addr.split("@")[-1].rsplit(".", 1)[-1]
                tld_map = {"uk": "UK", "in": "IN", "ae": "UAE", "au": "AU", "ca": "CA", "us": "US"}
                c_code = tld_map.get(tld, "")

            raw_hours = db.get_setting("sending_hours", "")
            if raw_hours:
                hours_cfg = json.loads(raw_hours)
                rule = hours_cfg.get(c_code) or hours_cfg.get("default")
                if rule and rule.get("enabled", True):
                    tz = ZoneInfo(rule.get("timezone", "UTC"))
                    now_local = datetime.now(_tz.utc).astimezone(tz)
                    cur_str = now_local.strftime("%H:%M")
                    start_str = rule.get("start", "09:00")
                    end_str = rule.get("end", "18:00")
                    if now_local.weekday() >= 5 and db.get_setting("skip_weekends", "0") == "1":
                        return False
                    return start_str <= cur_str < end_str
        except Exception as e_tz:
            logger.debug(f"Country timezone check fallback: {e_tz}")

    # 2. General server hour window fallback
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

            to_email  = email_row["to_email"]
            subject   = email_row["subject"]
            body      = email_row["body"]
            email_id  = email_row["id"]
            lead_id   = email_row["lead_id"]
            msg_type  = email_row["message_type"]

            lead = db.get_lead(lead_id) if lead_id else db.get_lead_by_email(to_email)
            if not _in_smart_hours(lead):
                # Outside business hours for this lead's country, skip to next lead
                continue

            remaining = db.total_remaining_today()
            if remaining <= 0:
                _notify(status_callback, f"🚫 Daily limit hit. {len(queued)} still in queue.")
                break

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

            # Guarantee required fields are present and valid
            from_addr = account.get("from_email") or account.get("email")
            account["from_email"] = from_addr
            account["email"] = from_addr
            account["id"] = account.get("id") or from_addr
            account["smtp_user"] = account.get("smtp_user") or from_addr
            account["smtp_pass"] = account.get("smtp_pass") or account.get("app_password")
            account["smtp_host"] = account.get("smtp_host") or "mail.spacemail.com"
            account["smtp_port"] = account.get("smtp_port") or 587
            account["provider"] = account.get("provider") or "spacemail"

            # Current active rotating IP node info
            node_tag = ""
            try:
                import ip_rotator
                cur_node = ip_rotator.peek_active_node()
                if cur_node:
                    node_tag = f" 📱 [{cur_node.get('name')}: {cur_node.get('ip_address')}]"
            except Exception:
                pass

            _notify(status_callback, f"📤 Sending to {to_email} via {from_addr}{node_tag}…")

            result = email_sender.send_email_now(to_email, subject, body, account)

            if result["success"]:
                db.mark_email_sent(email_id, result.get("message_id"), from_addr)
                lead_name = ""
                lead_company = ""
                if lead_id:
                    db.add_conversation_message(lead_id, "us", f"[{msg_type.upper()}] Subject: {subject}\n\n{body}")
                    # Update lead stage if still 'new'
                    lead = db.get_lead(lead_id)
                    if lead:
                        lead_name = lead.get("name") or ""
                        lead_company = lead.get("company") or ""
                        if lead["stage"] == "new":
                            db.update_lead_stage(lead_id, "contacted")
                    # Schedule first followup if opener
                    if msg_type == "opener":
                        db.schedule_first_followup(lead_id)
                db.log_activity("sent", f"To: {to_email} | From: {account['from_email']}{node_tag}")
                _notify(status_callback, f"✅ Sent → {to_email}{node_tag}")
                email_sender.notify_telegram_outbound(
                    to_email=to_email,
                    from_addr=from_addr,
                    subject=subject,
                    lead_name=lead_name,
                    company=lead_company,
                    msg_type="Campaign"
                )
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
