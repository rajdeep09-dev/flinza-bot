"""
Flinza — Followup Scheduler
Background loop that checks every 10 minutes for due followups and sends them.
"""

import time
import json
import threading
import logging

import database as db
import ai_router
import email_sender

logger = logging.getLogger(__name__)

_scheduler_running = False
_scheduler_thread  = None


def start_scheduler(notify_callback=None):
    global _scheduler_thread, _scheduler_running
    if _scheduler_running:
        return "Followup scheduler already running"
    _scheduler_running = True
    _scheduler_thread = threading.Thread(
        target=_run_loop, args=(notify_callback,), daemon=True
    )
    _scheduler_thread.start()
    return "Followup scheduler started"


def stop_scheduler():
    global _scheduler_running
    _scheduler_running = False
    return "Followup scheduler stopping…"


def is_running() -> bool:
    return _scheduler_running


def _run_loop(notify_callback):
    global _scheduler_running
    while _scheduler_running:
        try:
            _check_due_followups(notify_callback)
        except Exception as e:
            logger.error(f"Followup scheduler error: {e}")

        # Check every 10 minutes
        for _ in range(600):
            if not _scheduler_running:
                break
            time.sleep(1)


def _in_smart_hours() -> bool:
    """Returns True if current hour is within sending window and not on weekend."""
    from datetime import datetime
    if db.get_setting("smart_hours_enabled", "0") != "1":
        return True
    now = datetime.now()
    if now.weekday() >= 5 and db.get_setting("skip_weekends", "1") == "1":
        return False
    try:
        start = int(db.get_setting("smart_hours_start", "9"))
        end   = int(db.get_setting("smart_hours_end", "18"))
        return start <= now.hour < end
    except Exception:
        return True


def _check_due_followups(notify_callback):
    due = db.get_due_followups()
    if not due:
        return

    logger.info(f"Found {len(due)} due followups")
    for followup in due:
        try:
            _send_followup(followup, notify_callback)
        except Exception as e:
            logger.warning(f"Followup send error for lead {followup['lead_id']}: {e}")


def _send_followup(row, notify_callback):
    lead_id      = row["lead_id"]
    followup_num = row["followup_number"]

    lead = db.get_lead(lead_id)
    if not lead:
        db.mark_followup_sent(row["id"])
        return

    # Double-check stage
    safe_stages = ("replied", "negotiating", "closed_won", "closed_lost", "blacklisted", "unsubscribed")
    if lead["stage"] in safe_stages or lead["blacklisted"] or lead["unsubscribed"]:
        db.mark_followup_sent(row["id"])
        return

    # Check smart business hours and weekend pause
    if not _in_smart_hours():
        logger.info("Followup cycle skipped: outside business hours or weekend.")
        return

    # Get email history for context
    previous_emails = db.get_emails_for_lead(lead_id)

    # Check if a custom campaign sequence is configured
    seq_steps = db.get_campaign_sequences(campaign_id=1)
    matching_step = None
    for step in seq_steps:
        if step["step_number"] == followup_num + 1:
            matching_step = step
            break

    email_data = None
    if matching_step:
        cond = matching_step.get("condition_type", "always")
        lead_opened = lead.get("stage") in ("opened", "clicked")

        # Evaluate branching logic
        if cond == "if_not_opened" and lead_opened:
            logger.info(f"Skipping sequence step for {lead['email']}: lead already opened email.")
            db.mark_followup_sent(row["id"])
            return
        elif cond == "if_opened_no_reply" and not lead_opened:
            logger.info(f"Skipping sequence step for {lead['email']}: lead has not opened email yet.")
            return

        # A/B Split Test: select Variant A or Variant B
        import random
        use_b = bool(matching_step.get("subject_b") and matching_step.get("body_b") and random.random() < 0.5)
        subject_raw = matching_step["subject_b"] if use_b else matching_step["subject_a"]
        body_raw = matching_step["body_b"] if use_b else matching_step["body_a"]

        # Merge tags replacement
        sender_name = db.get_setting("sender_name", "The Team")
        first_name = (lead.get("name") or "there").split()[0]
        company = lead.get("company") or "your brand"
        niche = lead.get("niche") or "business"

        for k, v in [("{{name}}", first_name), ("{{first_name}}", first_name),
                     ("{{company}}", company), ("{{niche}}", niche),
                     ("{{sender_name}}", sender_name)]:
            subject_raw = subject_raw.replace(k, v)
            body_raw = body_raw.replace(k, v)

        email_data = {
            "subject": subject_raw,
            "body": body_raw,
            "used_fallback": False,
            "variant": "B" if use_b else "A",
        }
    else:
        # Dynamic AI Generation
        email_data = ai_router.generate_followup(dict(lead), previous_emails, followup_num)

    # Send
    result = email_sender.send_with_logging(
        lead_id=lead_id,
        to_email=lead["email"],
        subject=email_data["subject"],
        body=email_data["body"],
        message_type=f"followup_{followup_num}",
    )

    if result.get("success"):
        db.mark_followup_sent(row["id"])
        db.update_lead_stage(lead_id, f"followup_{followup_num}_sent")

        # Schedule next followup if not at max
        followup_days = json.loads(db.get_setting("followup_days", "[3, 2]"))
        max_followups = int(db.get_setting("max_followups", "3"))

        if followup_num < max_followups:
            next_idx = followup_num  # 0-indexed: FU1 uses [0], FU2 uses [1]
            days = followup_days[next_idx] if next_idx < len(followup_days) else followup_days[-1]
            db.schedule_followup(lead_id, days, followup_num + 1)

        db.log_activity("followup_sent", f"FU#{followup_num} to {lead['email']}")

        if notify_callback:
            try:
                notify_callback({
                    "type":           "followup_sent",
                    "lead_name":      lead["name"],
                    "lead_email":     lead["email"],
                    "followup_number": followup_num,
                    "used_fallback":  email_data.get("used_fallback", False),
                })
            except Exception:
                pass
    else:
        logger.warning(f"Followup failed for {lead['email']}: {result.get('error')}")
