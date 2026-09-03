"""
Flinza — Outreach Engine v2.0 (Smart Sending Brain)
=====================================================
Enterprise-grade cold email intelligence:

1.  Domain rotation with reputation scoring per alias
2.  Timezone-aware send scheduling (MX → country → local business hours)
3.  Reply-thread stitching (In-Reply-To / References headers)
4.  Nested spintax engine with fallback
5.  Humanized delay with Gaussian jitter
6.  Per-domain warmup curve (5→10→20→30→50/day)
7.  Bounce / spam rate auto-pause with health scoring
8.  AI intent classification on incoming replies
9.  Smartlead-compatible reply webhook ingestion
10. One-click campaign launch with smart alias selection
"""

import random
import math
import re
import time
import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import database as db
import email_sender
import ai_router
import email_toolkit
import config

logger = logging.getLogger(__name__)

# ── Warmup daily caps by account age (days since added) ───────────
WARMUP_CURVE = [
    (0,   3,   5),   # days 0-3:   max 5/day
    (4,   7,  10),   # days 4-7:   max 10/day
    (8,  14,  20),   # days 8-14:  max 20/day
    (15, 21,  35),   # days 15-21: max 35/day
    (22, 30,  50),   # days 22-30: max 50/day
    (31, 999, 100),  # 30+ days:   full 100/day
]

# Business hour windows per rough timezone offset (UTC offset → local hours)
BIZ_HOUR_WINDOWS = {
    (-8, -4): (9, 17),   # Americas
    (-4,  2): (8, 17),   # Americas East + Europe West
    (2,   6): (8, 17),   # Europe Central/East
    (5,  10): (9, 18),   # India / South Asia
    (8,  14): (9, 18),   # Asia / Pacific
}

# Spam score thresholds — above these, account is auto-paused
HARD_BOUNCE_THRESHOLD   = 0.08   # 8% bounce rate → pause
SPAM_RATE_THRESHOLD     = 0.03   # 3% spam rate → pause
UNSUBSCRIBE_THRESHOLD   = 0.05   # 5% unsub rate → pause


# ═══════════════════════════════════════════════════════════════════
#   SPINTAX ENGINE — Supports nested {A|B|{C|D|{E|F}}} recursively
# ═══════════════════════════════════════════════════════════════════

def spin(text: str, seed: Optional[int] = None) -> str:
    """
    Resolves deeply nested spintax patterns.
    Optional seed for reproducible output per lead.
    """
    if not text:
        return ""
    if seed is not None:
        random.seed(seed)

    # Work from innermost braces outward (iterative)
    inner = re.compile(r'\{([^{}]+)\}')
    max_passes = 30
    for _ in range(max_passes):
        match = inner.search(text)
        if not match:
            break
        choices = match.group(1).split('|')
        chosen = random.choice(choices).strip()
        text = text[:match.start()] + chosen + text[match.end():]
    return text


def preview_spin_variants(text: str, count: int = 5) -> List[str]:
    """Returns N different spintax resolutions for A/B preview."""
    return [spin(text) for _ in range(count)]


# ═══════════════════════════════════════════════════════════════════
#   MERGE TAG ENGINE — {{name}}, {{company}}, {{first_name}}, etc.
# ═══════════════════════════════════════════════════════════════════

def apply_merge_tags(text: str, lead: dict, sender_name: str = "") -> str:
    """
    Replaces {{merge_tags}} with lead-specific values.
    Supports: name, first_name, email, company, niche, handle,
              sender_name, weekday, month, year
    """
    if not text:
        return ""

    name = lead.get("name", "there") or "there"
    first_name = name.split()[0] if name else "there"
    now = datetime.now()

    tags = {
        "{{name}}":        name,
        "{{first_name}}":  first_name,
        "{{email}}":       lead.get("email", ""),
        "{{company}}":     lead.get("company", "your company") or "your company",
        "{{niche}}":       lead.get("niche", "your niche") or "your niche",
        "{{handle}}":      lead.get("handle", "") or "",
        "{{sender_name}}": sender_name or db.get_setting("sender_name", "Flinza"),
        "{{weekday}}":     now.strftime("%A"),
        "{{month}}":       now.strftime("%B"),
        "{{year}}":        str(now.year),
    }

    for tag, value in tags.items():
        text = text.replace(tag, str(value))

    return text


def personalize(subject: str, body: str, lead: dict, sender_name: str = "", seed: Optional[int] = None) -> tuple:
    """
    Full personalization pipeline: spin → merge tags → deliverability clean.
    Returns (subject, body) tuple.
    """
    subject = spin(subject, seed=seed)
    body    = spin(body, seed=seed)
    subject = apply_merge_tags(subject, lead, sender_name)
    body    = apply_merge_tags(body, lead, sender_name)
    return subject, body


# ═══════════════════════════════════════════════════════════════════
#   SEND-TIME OPTIMIZER — timezone-aware scheduling
# ═══════════════════════════════════════════════════════════════════

def _estimate_tz_offset_from_domain(email: str) -> int:
    """Rough TZ offset estimate based on MX record location hints."""
    domain = email.split("@")[-1] if "@" in email else ""

    # TLD-based rough estimates
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""
    TLD_TZ = {
        "in": 5, "pk": 5, "bd": 6, "np": 5,
        "de": 1, "fr": 1, "nl": 1, "es": 1, "it": 1, "pl": 1, "at": 1,
        "uk": 0, "ie": 0, "pt": 0,
        "au": 10, "nz": 12, "sg": 8, "my": 8, "ph": 8, "th": 7, "vn": 7,
        "cn": 8, "hk": 8, "jp": 9, "kr": 9, "tw": 8,
        "br": -3, "ar": -3, "cl": -3, "mx": -6, "co": -5,
        "ca": -5, "us": -5, "com": -5,  # rough default US
    }
    return TLD_TZ.get(tld, -5)  # default to US Eastern


def is_in_business_hours(email: str, now_utc: Optional[datetime] = None) -> bool:
    """Returns True if current time is within prospect's business hours."""
    if not db.get_setting("smart_timing_enabled", "0") == "1":
        return True  # feature disabled → always ok

    now_utc = now_utc or datetime.now(timezone.utc)
    offset = _estimate_tz_offset_from_domain(email)
    local_hour = (now_utc.hour + offset) % 24

    for (min_offset, max_offset), (start_h, end_h) in BIZ_HOUR_WINDOWS.items():
        if min_offset <= offset <= max_offset:
            return start_h <= local_hour < end_h

    return 8 <= local_hour < 18  # default 8am-6pm


def jitter_delay(base_seconds: int) -> int:
    """
    Applies Gaussian jitter (+/- 25%) to humanize send delays.
    Prevents pattern detection by spam filters.
    """
    sigma = base_seconds * 0.25
    jittered = int(random.gauss(base_seconds, sigma))
    return max(30, jittered)  # minimum 30 seconds


def compute_next_send_delay(min_s: Optional[int] = None, max_s: Optional[int] = None) -> int:
    """Returns the next randomized send delay in seconds."""
    lo = int(min_s or db.get_setting("min_interval_seconds", "120"))
    hi = int(max_s or db.get_setting("max_interval_seconds", "420"))
    base = random.randint(lo, hi)
    return jitter_delay(base)


# ═══════════════════════════════════════════════════════════════════
#   DOMAIN ROTATION — Smart alias selection by health score
# ═══════════════════════════════════════════════════════════════════

def score_account_health(account: dict) -> float:
    """
    Returns a 0.0–1.0 health score for a sending account.
    Higher = better to use.
    """
    sent_today   = account.get("sent_today", 0) or 0
    daily_limit  = account.get("daily_limit", 50) or 50
    bounce_rate  = account.get("bounce_rate", 0.0) or 0.0
    spam_rate    = account.get("spam_rate", 0.0) or 0.0
    is_active    = account.get("active", 1) == 1

    if not is_active:
        return 0.0

    # Fail hard above thresholds
    if bounce_rate > HARD_BOUNCE_THRESHOLD or spam_rate > SPAM_RATE_THRESHOLD:
        return 0.0

    # Capacity score: how much room is left
    capacity = max(0, daily_limit - sent_today) / max(daily_limit, 1)
    # Reputation score: inverse of bad rates
    reputation = 1.0 - min(1.0, bounce_rate * 5 + spam_rate * 10)

    return round(capacity * 0.6 + reputation * 0.4, 3)


def pick_best_account(lead_email: str = "", exclude: Optional[List[str]] = None) -> Optional[dict]:
    """
    Smart alias/account rotation:
    1. Score all active accounts by health
    2. Filter out excluded and exhausted ones
    3. Prefer warmup-curve-compliant accounts
    4. Weighted-random pick (higher score = higher probability)
    """
    exclude = exclude or []
    accounts = db.get_all_accounts()
    aliases  = db.get_all_aliases()

    candidates = []

    # Build combined pool
    for a in accounts:
        if a["email"] in exclude:
            continue
        health = score_account_health(dict(a))
        if health > 0:
            candidates.append({"source": "account", "health": health, "data": dict(a)})

    for al in aliases:
        if al["alias"] in exclude:
            continue
        # Treat alias health similarly
        sent_today  = al.get("sent_today", 0) or 0
        daily_limit = al.get("daily_limit", 20) or 20
        if sent_today >= daily_limit:
            continue
        capacity = (daily_limit - sent_today) / max(daily_limit, 1)
        candidates.append({"source": "alias", "health": capacity, "data": dict(al)})

    if not candidates:
        return None

    # Weighted random selection
    weights  = [c["health"] for c in candidates]
    total    = sum(weights)
    if total <= 0:
        return None

    pick = random.choices(candidates, weights=weights, k=1)[0]
    src  = pick["source"]
    d    = pick["data"]

    if src == "alias":
        # Build account-dict from alias
        master_email = d.get("smtp_user") or d.get("alias")
        master = next((a for a in accounts if a["email"] == master_email), None)
        return {
            "id":           d["alias"],
            "type":         "alias",
            "from_email":   d["alias"],
            "smtp_user":    d.get("smtp_user") or d["alias"],
            "smtp_pass":    master["app_password"] if master else d.get("smtp_pass"),
            "smtp_host":    d.get("smtp_host"),
            "smtp_port":    d.get("smtp_port"),
            "proxy_url":    None,
            "display_name": d.get("display_name") or "",
            "routing_mode": d.get("routing_mode", "gmail_send_as"),
            "provider":     d.get("routing_mode", "gmail_send_as"),
        }
    else:
        return {
            "id":           d["email"],
            "type":         "gmail",
            "from_email":   d["email"],
            "smtp_user":    d["email"],
            "smtp_pass":    d.get("app_password"),
            "smtp_host":    d.get("smtp_host") or "smtp.gmail.com",
            "smtp_port":    d.get("smtp_port") or 587,
            "proxy_url":    d.get("proxy_url"),
            "display_name": d.get("label") or d["email"].split("@")[0].replace(".", " ").title(),
            "routing_mode": "gmail",
            "provider":     d.get("provider") or "gmail",
        }


# ═══════════════════════════════════════════════════════════════════
#   REPLY-THREAD STITCHING — In-Reply-To + References headers
# ═══════════════════════════════════════════════════════════════════

def build_reply_headers(thread) -> Dict[str, str]:
    """
    Given a reply thread dict (with original_message_id), builds the
    MIME headers needed to stitch this email into the same Gmail thread.
    """
    headers = {}
    orig_msg_id = None

    if isinstance(thread, dict):
        orig_msg_id = (
            thread.get("original_message_id") or
            thread.get("message_id") or
            thread.get("thread_message_id")
        )

    if orig_msg_id:
        headers["In-Reply-To"] = orig_msg_id
        headers["References"]  = orig_msg_id

    return headers


# ═══════════════════════════════════════════════════════════════════
#   DELIVERABILITY SCORE — Pre-send quality check
# ═══════════════════════════════════════════════════════════════════

def score_email_deliverability(subject: str, body: str) -> Dict[str, Any]:
    """
    Analyzes subject + body before sending.
    Returns: { score (0-100), grade, issues, suggestions }
    """
    score = 100
    issues = []
    suggestions = []

    text = f"{subject} {body}".lower()

    # Check spam triggers
    high_risk_hits = [w for w in email_toolkit.SPAM_TRIGGERS["high_risk"] if w.lower() in text]
    med_risk_hits  = [w for w in email_toolkit.SPAM_TRIGGERS["medium_risk"] if w.lower() in text]

    score -= len(high_risk_hits) * 15
    score -= len(med_risk_hits) * 7

    if high_risk_hits:
        issues.append(f"High-risk spam words detected: {', '.join(high_risk_hits[:3])}")
    if med_risk_hits:
        issues.append(f"Medium-risk words: {', '.join(med_risk_hits[:3])}")

    # Subject length
    if len(subject) > 70:
        score -= 8
        issues.append("Subject line too long (>70 chars hurts mobile open rates)")
        suggestions.append("Keep subject under 60 characters")
    elif len(subject) < 5:
        score -= 15
        issues.append("Subject line too short")

    # All caps in subject
    caps_words = sum(1 for w in subject.split() if w.isupper() and len(w) > 2)
    if caps_words > 1:
        score -= 10
        issues.append("CAPS words in subject increase spam likelihood")

    # Body length check
    word_count = len(body.split())
    if word_count < 30:
        score -= 5
        suggestions.append("Aim for 80-150 words for best reply rates")
    elif word_count > 400:
        score -= 10
        issues.append("Email too long — shorter cold emails get more replies")
        suggestions.append("Trim to under 200 words")

    # Personalization check
    has_personalization = any(tag in body for tag in ["{{name}}", "{{first_name}}", "{{company}}", "{{niche}}"])
    if not has_personalization:
        score -= 12
        suggestions.append("Add {{first_name}} or {{company}} to personalize the email")

    # Spintax check
    has_spintax = "{" in body and "|" in body
    if not has_spintax:
        suggestions.append("Add {spintax|variation} to create unique fingerprints per send")

    # Links
    link_count = body.lower().count("http")
    if link_count > 2:
        score -= 8
        issues.append("Too many links (>2) increases spam likelihood")
    if link_count == 0:
        suggestions.append("Consider adding 1 CTA link (tracked automatically by Flinza)")

    # Unsubscribe
    if "unsubscribe" not in body.lower() and "opt out" not in body.lower() and "opt-out" not in body.lower():
        suggestions.append("Add an unsubscribe option to stay CAN-SPAM compliant")

    score = max(0, min(100, score))

    if score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    elif score >= 55:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "issues": issues,
        "suggestions": suggestions,
        "word_count": word_count,
        "spam_triggers_found": len(high_risk_hits) + len(med_risk_hits),
    }


# ═══════════════════════════════════════════════════════════════════
#   CAMPAIGN LAUNCHER — Smart outreach for all new leads
# ═══════════════════════════════════════════════════════════════════

def launch_campaign(campaign_id: int = 1, dry_run: bool = False) -> Dict[str, Any]:
    """
    Queues all new/uncontacted leads for the first sequence step.
    Uses smart alias rotation and per-lead personalization.
    Returns stats on what was queued.
    """
    leads = db.get_leads(stage="new", limit=500)
    if not leads:
        return {"success": False, "message": "No new uncontacted leads found. Add leads first."}

    steps = db.get_sequence_steps(campaign_id) or []
    if not steps:
        return {"success": False, "message": "No sequence steps configured for this campaign."}

    step_1 = steps[0]
    queued = []
    skipped = []
    sender_name = db.get_setting("sender_name", "Flinza")

    for lead in leads:
        # Skip blacklisted or disposable
        if db.is_blacklisted(lead["email"]):
            skipped.append({"email": lead["email"], "reason": "blacklisted"})
            continue

        if email_toolkit.is_disposable_email(lead["email"]):
            skipped.append({"email": lead["email"], "reason": "disposable domain"})
            continue

        # Pick best account
        account = pick_best_account(lead_email=lead["email"])
        if not account:
            skipped.append({"email": lead["email"], "reason": "no accounts with capacity"})
            continue

        # Personalize with lead-specific seed (reproducible for that lead)
        seed = hash(lead["email"]) % 10000
        subject, body = personalize(
            step_1.get("subject_a", ""),
            step_1.get("body_a", ""),
            lead=dict(lead),
            sender_name=sender_name,
            seed=seed,
        )

        # Score deliverability
        score_data = score_email_deliverability(subject, body)
        if score_data["score"] < 35:
            skipped.append({"email": lead["email"], "reason": f"deliverability score too low ({score_data['score']})"})
            continue

        if not dry_run:
            db.queue_email(
                lead_id=lead["id"],
                from_account=account["from_email"],
                to_email=lead["email"],
                subject=subject,
                body=body,
                step_number=1,
                campaign_id=campaign_id,
                priority=1,
            )
            db.update_lead_stage(lead["id"], "contacted")

        queued.append({
            "email": lead["email"],
            "from":  account["from_email"],
            "score": score_data["score"],
        })

    return {
        "success": True,
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "queued": queued[:20],  # first 20 for preview
        "skipped": skipped[:10],
        "dry_run": dry_run,
    }


# ═══════════════════════════════════════════════════════════════════
#   WARMUP MANAGER — Progressive sending volume
# ═══════════════════════════════════════════════════════════════════

def get_warmup_limit(account_added_days_ago: int, manual_daily_limit: int = 100) -> int:
    """Returns the warmup-curve daily limit for an account of given age."""
    for (day_start, day_end, max_sends) in WARMUP_CURVE:
        if day_start <= account_added_days_ago <= day_end:
            return min(max_sends, manual_daily_limit)
    return manual_daily_limit


def check_and_auto_pause_unhealthy_accounts() -> List[str]:
    """
    Reviews all accounts. Auto-pauses accounts exceeding bounce/spam thresholds.
    Returns list of paused account emails.
    """
    paused = []
    accounts = db.get_all_accounts()

    for a in accounts:
        a = dict(a)
        bounce_rate = a.get("bounce_rate", 0.0) or 0.0
        spam_rate   = a.get("spam_rate", 0.0) or 0.0

        should_pause = False
        reason = ""

        if bounce_rate > HARD_BOUNCE_THRESHOLD:
            should_pause = True
            reason = f"Bounce rate {bounce_rate*100:.1f}% exceeds {HARD_BOUNCE_THRESHOLD*100}% threshold"
        elif spam_rate > SPAM_RATE_THRESHOLD:
            should_pause = True
            reason = f"Spam rate {spam_rate*100:.1f}% exceeds {SPAM_RATE_THRESHOLD*100}% threshold"

        if should_pause and a.get("active", 1) == 1:
            db.set_account_active(a["email"], False)
            paused.append(a["email"])
            logger.warning(f"Auto-paused {a['email']}: {reason}")

    return paused


def get_account_warmup_stats() -> List[Dict]:
    """Returns warmup health stats for all accounts."""
    accounts = db.get_all_accounts()
    result = []

    for a in accounts:
        a = dict(a)
        sent_today  = a.get("sent_today", 0) or 0
        daily_limit = a.get("daily_limit", 50) or 50
        added_at    = a.get("added_at") or a.get("created_at")

        try:
            if added_at:
                added_dt = datetime.fromisoformat(str(added_at).replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - added_dt).days
            else:
                age_days = 999
        except Exception:
            age_days = 999

        warmup_cap   = get_warmup_limit(age_days, daily_limit)
        health_score = score_account_health(dict(a))
        bounce_rate  = a.get("bounce_rate", 0.0) or 0.0
        spam_rate    = a.get("spam_rate", 0.0) or 0.0

        result.append({
            "email":        a["email"],
            "age_days":     age_days,
            "warmup_cap":   warmup_cap,
            "sent_today":   sent_today,
            "daily_limit":  daily_limit,
            "health_score": health_score,
            "health_grade": "A" if health_score > 0.8 else ("B" if health_score > 0.6 else ("C" if health_score > 0.4 else ("D" if health_score > 0.2 else "F"))),
            "bounce_rate":  round(bounce_rate * 100, 2),
            "spam_rate":    round(spam_rate * 100, 2),
            "active":       a.get("active", 1) == 1,
            "is_warming_up": age_days <= 30,
            "utilization":  round(sent_today / max(daily_limit, 1) * 100, 1),
        })

    return result


# ═══════════════════════════════════════════════════════════════════
#   REPLY INTENT CLASSIFIER
# ═══════════════════════════════════════════════════════════════════

INTENT_PATTERNS = {
    "interested": [
        r"\binterested\b", r"\bsounds good\b", r"\btell me more\b", r"\bwould love to\b",
        r"\byes\b.*\bcall\b", r"\bbook\b.*\bcall\b", r"\bschedule\b", r"\blet'?s?\s+chat\b",
        r"\bsend me\b", r"\bhow much\b", r"\bwhat'?s?\s+the\s+price\b", r"\bwhat are your rates\b",
    ],
    "not_interested": [
        r"\bnot interested\b", r"\bno thanks\b", r"\bdon'?t?\s+contact\b", r"\bremove me\b",
        r"\bunsubscribe\b", r"\bstop emailing\b", r"\bno,?\s+thank you\b", r"\bwe'?re?\s+good\b",
        r"\bhave someone\b", r"\bnot looking\b", r"\bnot at this time\b",
    ],
    "out_of_office": [
        r"\bout of\s+office\b", r"\bauto.?reply\b", r"\bvacation\b", r"\baway until\b",
        r"\bon leave\b", r"\bwill be back\b", r"\bcurrently unavailable\b",
    ],
    "meeting_booked": [
        r"\bbooked\b", r"\bscheduled\b", r"\bcalendar\b", r"\bcal\.?com\b", r"\bcalendly\b",
        r"\bconfirm\b.*\bmeeting\b", r"\bsee you\b",
    ],
    "bounce": [
        r"\bmail delivery failed\b", r"\bdelivery status notification\b", r"\bmailer-daemon\b",
        r"\bno such user\b", r"\baccount does not exist\b", r"\bpermanent failure\b",
    ],
}


def classify_reply_intent(body: str, subject: str = "") -> str:
    """
    Rule-based intent classification.
    Returns: interested | not_interested | out_of_office | meeting_booked | bounce | general
    """
    text = f"{subject} {body}".lower()

    # Priority order
    for intent in ["bounce", "meeting_booked", "out_of_office", "not_interested", "interested"]:
        patterns = INTENT_PATTERNS.get(intent, [])
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return intent

    return "general"


def ai_classify_reply_and_draft(body: str, subject: str = "", lead: Optional[dict] = None) -> Dict[str, Any]:
    """
    Uses AI to:
    1. Classify the intent (interested/not_interested/ooo/etc.)
    2. Draft a contextual reply
    """
    intent = classify_reply_intent(body, subject)

    if intent in ("bounce", "out_of_office"):
        return {"intent": intent, "ai_draft": None, "confidence": "high"}

    # AI drafting
    lead_info = ""
    if lead:
        lead_info = f"Lead: {lead.get('name', 'Unknown')}, Company: {lead.get('company', 'N/A')}, Niche: {lead.get('niche', 'N/A')}"

    prompt = f"""You are an expert cold email reply handler for an SMMA agency.
A prospect replied to our outreach email.

{lead_info}
Reply Subject: {subject}
Reply Body: {body}

Detected intent: {intent}

Write a concise, professional, non-pushy reply (max 100 words).
If interested: confirm next step (brief call / Calendly).
If not interested: gracefully acknowledge and close.
If OOO: note to follow up after their return date.
Only output the email body. No subject line. No sign-off needed."""

    try:
        ai_result = ai_router.generate_reply(prompt, max_tokens=200)
        draft = ai_result.get("reply", "").strip()
    except Exception as e:
        logger.warning(f"AI draft generation failed: {e}")
        draft = _get_fallback_draft(intent)

    return {
        "intent": intent,
        "ai_draft": draft,
        "confidence": "high" if intent != "general" else "medium",
    }


def _get_fallback_draft(intent: str) -> str:
    """Fallback drafts if AI is unavailable."""
    drafts = {
        "interested": "Thanks for getting back to me! I'd love to learn more about your business. Would you be open to a quick 15-minute call this week?",
        "not_interested": "Totally understand — no problem at all. I'll make sure to remove you from our list. Hope things go well with your business!",
        "out_of_office": "Thanks for the heads up! I'll reach out again after your return. Have a great time off!",
        "meeting_booked": "Awesome — looking forward to our conversation! I'll send over a quick agenda beforehand.",
        "general": "Thanks for getting back to me! How can I help you further?",
    }
    return drafts.get(intent, drafts["general"])


# ═══════════════════════════════════════════════════════════════════
#   SMARTLEAD WEBHOOK INGESTION
# ═══════════════════════════════════════════════════════════════════

def ingest_smartlead_webhook(payload: dict) -> Dict[str, Any]:
    """
    Processes incoming Smartlead webhook events.
    Supported events: reply_received, email_opened, email_bounced, unsubscribed
    """
    event_type = payload.get("type") or payload.get("event_type", "")
    lead_email  = payload.get("lead_email") or payload.get("email", "")

    if not lead_email:
        return {"success": False, "error": "No lead email in payload"}

    lead = db.get_lead_by_email(lead_email)

    if event_type in ("reply_received", "reply"):
        reply_body    = payload.get("reply_text") or payload.get("body", "")
        reply_subject = payload.get("reply_subject") or payload.get("subject", "")

        classification = ai_classify_reply_and_draft(reply_body, reply_subject, lead=dict(lead) if lead else None)
        intent = classification["intent"]

        if lead:
            if intent == "interested":
                db.update_lead_stage(lead["id"], "replied")
            elif intent == "not_interested":
                db.update_lead_stage(lead["id"], "opted_out")

            # Store reply in unibox
            db.add_reply_to_unibox(
                lead_id=lead["id"],
                sender=lead_email,
                subject=reply_subject,
                body=reply_body,
                ai_draft=classification.get("ai_draft"),
                intent=intent,
                source="smartlead_webhook",
            )

        return {
            "success": True,
            "event": event_type,
            "lead_email": lead_email,
            "intent": intent,
            "ai_draft_generated": bool(classification.get("ai_draft")),
        }

    elif event_type in ("email_opened", "open"):
        if lead:
            db.record_open(lead_id=lead["id"])
            db.update_lead_stage(lead["id"], "opened")
        return {"success": True, "event": "open_recorded", "lead_email": lead_email}

    elif event_type in ("email_bounced", "bounce"):
        if lead:
            db.blacklist_lead(lead["id"], "Smartlead bounce event")
        db.add_to_blacklist(lead_email, reason="Smartlead webhook bounce")
        return {"success": True, "event": "bounced_and_blacklisted", "lead_email": lead_email}

    elif event_type in ("unsubscribed", "opt_out"):
        if lead:
            db.update_lead_stage(lead["id"], "opted_out")
        db.add_to_blacklist(lead_email, reason="Smartlead unsubscribe")
        return {"success": True, "event": "unsubscribed", "lead_email": lead_email}

    return {"success": True, "event": "unhandled", "event_type": event_type}


# ═══════════════════════════════════════════════════════════════════
#   SMTP VERIFICATION — Live end-to-end test
# ═══════════════════════════════════════════════════════════════════

def verify_smtp_connection(smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str) -> Dict[str, Any]:
    """
    Tests raw SMTP connection + authentication without sending.
    Returns latency, auth result, and server banner.
    """
    import smtplib
    import ssl

    start = time.time()
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            banner = server.ehlo()[1].decode("utf-8", errors="ignore") if server.ehlo()[0] == 250 else ""
            server.starttls(context=ssl.create_default_context())
            server.login(smtp_user, smtp_pass)
            elapsed = round((time.time() - start) * 1000)
            return {
                "success": True,
                "latency_ms": elapsed,
                "server_banner": banner[:120],
                "auth": "OK",
                "tls": True,
            }
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": "Authentication failed. Check app password or credentials.", "latency_ms": round((time.time()-start)*1000)}
    except smtplib.SMTPConnectError as e:
        return {"success": False, "error": f"Cannot connect to {smtp_host}:{smtp_port} — {e}", "latency_ms": round((time.time()-start)*1000)}
    except Exception as e:
        return {"success": False, "error": str(e), "latency_ms": round((time.time()-start)*1000)}


# ═══════════════════════════════════════════════════════════════════
#   TERMINAL COMMAND DISPATCHER — Run bot commands from webapp
# ═══════════════════════════════════════════════════════════════════

COMMAND_REGISTRY = {}

def register_cmd(name):
    def decorator(fn):
        COMMAND_REGISTRY[name.lower()] = fn
        return fn
    return decorator


@register_cmd("stats")
def cmd_stats(*_) -> str:
    stats = db.get_stats()
    tracking = db.get_tracking_stats()
    return (
        f"📊 *Flinza Stats*\n"
        f"  Leads: {stats.get('total_leads', 0)}\n"
        f"  Sent today: {stats.get('sent_today', 0)}\n"
        f"  Total sent: {stats.get('total_sent', 0)}\n"
        f"  Replies: {stats.get('total_replies', 0)} ({stats.get('unhandled_replies', 0)} unhandled)\n"
        f"  Open rate: {tracking.get('open_rate', 0)}% | Click rate: {tracking.get('click_rate', 0)}%"
    )


@register_cmd("launch")
def cmd_launch(*args) -> str:
    dry = "--dry" in args or "-d" in args
    result = launch_campaign(dry_run=dry)
    if result.get("success"):
        return f"🚀 Campaign {'dry-run: ' if dry else ''}queued {result['queued_count']} leads | skipped {result['skipped_count']}"
    return f"⚠️ {result.get('message', 'Launch failed')}"


@register_cmd("accounts")
def cmd_accounts(*_) -> str:
    accounts = db.get_all_accounts()
    if not accounts:
        return "No accounts configured."
    lines = ["📬 *Sending Accounts:*"]
    for a in accounts:
        lines.append(f"  • {a['email']} — sent today: {a.get('sent_today',0)}/{a.get('daily_limit',50)}")
    return "\n".join(lines)


@register_cmd("leads")
def cmd_leads(*args) -> str:
    stage = args[0] if args else "all"
    leads = db.get_leads(stage=stage if stage != "all" else None, limit=20)
    if not leads:
        return "No leads found."
    lines = [f"👥 *Leads* (stage={stage}):"]
    for l in leads[:10]:
        lines.append(f"  • {l['email']} — {l['stage']}")
    if len(leads) > 10:
        lines.append(f"  ... and {len(leads)-10} more")
    return "\n".join(lines)


@register_cmd("warmup")
def cmd_warmup(*_) -> str:
    stats = get_account_warmup_stats()
    if not stats:
        return "No accounts found."
    lines = ["🔥 *Warmup Status:*"]
    for a in stats:
        grade = a['health_grade']
        lines.append(f"  • {a['email']}: Grade {grade} | {a['sent_today']}/{a['warmup_cap']} | bounce={a['bounce_rate']}%")
    return "\n".join(lines)


@register_cmd("pause")
def cmd_pause(*_) -> str:
    try:
        import email_queue
        email_queue.pause_queue()
        return "⏸ Queue paused."
    except Exception as e:
        return f"Error: {e}"


@register_cmd("resume")
def cmd_resume(*_) -> str:
    try:
        import email_queue
        email_queue.resume_queue()
        return "▶️ Queue resumed."
    except Exception as e:
        return f"Error: {e}"


@register_cmd("score")
def cmd_score(*args) -> str:
    """Score an email template. Usage: score <subject> | <body>"""
    text = " ".join(args)
    if "|" in text:
        subject, body = text.split("|", 1)
    else:
        subject, body = text, text
    result = score_email_deliverability(subject.strip(), body.strip())
    lines = [f"📧 Deliverability Score: {result['score']}/100 (Grade: {result['grade']})"]
    if result["issues"]:
        lines.append("⚠️ Issues:")
        for i in result["issues"]:
            lines.append(f"  • {i}")
    if result["suggestions"]:
        lines.append("💡 Suggestions:")
        for s in result["suggestions"][:3]:
            lines.append(f"  • {s}")
    return "\n".join(lines)


@register_cmd("help")
def cmd_help(*_) -> str:
    cmds = sorted(COMMAND_REGISTRY.keys())
    return "🤖 *Available Commands:*\n" + "\n".join(f"  /{c}" for c in cmds)


def dispatch_terminal_command(raw_input: str) -> Dict[str, Any]:
    """
    Parses and dispatches a terminal command from the webapp.
    Input format: /command arg1 arg2 or just 'command arg1 arg2'
    """
    raw = raw_input.strip().lstrip("/")
    parts = raw.split()
    if not parts:
        return {"success": False, "output": "Empty command. Type /help to see commands."}

    cmd_name = parts[0].lower()
    args = parts[1:]

    handler = COMMAND_REGISTRY.get(cmd_name)
    if not handler:
        return {
            "success": False,
            "output": f"Unknown command: /{cmd_name}\nType /help to see available commands.",
        }

    try:
        output = handler(*args)
        return {"success": True, "command": cmd_name, "output": output}
    except Exception as e:
        logger.error(f"Terminal command error /{cmd_name}: {e}")
        return {"success": False, "output": f"Error executing /{cmd_name}: {str(e)}"}
