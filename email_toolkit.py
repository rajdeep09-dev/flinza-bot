"""
Flinza — Email Toolkit & Deliverability Suite
Enterprise-grade cold outreach utilities:
1. Spintax parser & dynamic merge tags engine
2. Spam trigger words & deliverability score analyzer
3. DNS MX validator & disposable domain detector
4. Reply sentiment & intent classifier with auto-unsubscribe detection
5. Mailbox warmup schedule calculator
"""

import re
import random
import logging
from typing import Dict, Any, Tuple, List
import dns.resolver

logger = logging.getLogger(__name__)

# ─── 1. DISPOSABLE & ROLE-BASED DOMAINS ───────────────────────────
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "sharklasers.com", "throwawaymail.com", "yopmail.com", "trashmail.com",
    "fakeinbox.com", "getairmail.com", "dispostable.com", "temp-mail.org",
}

ROLE_PREFIXES = {
    "admin", "support", "billing", "info", "help", "contact",
    "sales", "abuse", "postmaster", "webmaster", "security",
}

# ─── 2. SPAM TRIGGER WORDS ───────────────────────────────────────
SPAM_TRIGGERS = {
    "high_risk": [
        "100% free", "act now", "apply now", "call now", "urgent", "instant cash",
        "make money", "work from home", "guaranteed income", "free gift", "no cost",
        "risk free", "risk-free", "double your", "earn extra cash", "unlimited",
        "million dollars", "fast cash", "congratulations", "winner", "you have been selected",
        "click here", "buy now", "order now", "as seen on", "special promotion",
        "wire transfer", "bank account", "social security", "credit card", "crypto investment"
    ],
    "medium_risk": [
        "limited time", "exclusive deal", "special offer", "don't delete", "hidden charges",
        "lowest price", "drastically reduced", "miracle", "once in a lifetime",
        "pure profit", "save big", "promise you", "dear friend", "incredible deal",
        "no obligation", "satisfaction guaranteed", "cancel at any time", "affordable"
    ],
    "overused_marketing": [
        "synergy", "revolutionary", "game changer", "game-changing", "disruptive",
        "cutting edge", "state of the art", "best in class", "paradigm shift"
    ]
}


# ═══════════════════════════════════════════════════════════════
#                    SPINTAX & MERGE TAGS
# ═══════════════════════════════════════════════════════════════

def resolve_spintax(text: str) -> str:
    """
    Recursively resolves Spintax patterns: {Option A|Option B|{Sub 1|Sub 2}}
    """
    if not text:
        return ""
    pattern = re.compile(r"\{([^{}]+)\}")
    while True:
        match = pattern.search(text)
        if not match:
            break
        choices = match.group(1).split("|")
        picked = random.choice(choices)
        text = text[:match.start()] + picked + text[match.end():]
    return text


def apply_merge_tags(text: str, variables: Dict[str, Any]) -> str:
    """
    Replaces merge tags: {{name}}, {{first_name}}, {{handle}}, {{niche}},
    {{followers}}, {{company}}, {{sender_name}}, etc.
    """
    if not text or not variables:
        return text or ""

    name = variables.get("name") or variables.get("handle") or "there"
    first_name = name.split()[0] if name else "there"

    replacements = {
        "{{name}}": name,
        "{{first_name}}": first_name,
        "{{firstname}}": first_name,
        "{{handle}}": variables.get("handle") or "",
        "{{email}}": variables.get("email") or "",
        "{{niche}}": variables.get("niche") or "content",
        "{{company}}": variables.get("company") or "your brand",
        "{{followers}}": f"{variables.get('followers'):,}" if variables.get("followers") else "",
        "{{tier}}": variables.get("tier") or "",
        "{{sender_name}}": variables.get("sender_name") or "The Team",
    }

    # Add custom variables if provided
    for k, v in variables.items():
        if v is not None:
            replacements[f"{{{{{k}}}}}"] = str(v)

    for tag, val in replacements.items():
        text = text.replace(tag, str(val))

    return text


def process_email_template(raw_text: str, variables: Dict[str, Any]) -> str:
    """First applies merge tags, then resolves spintax."""
    text_with_tags = apply_merge_tags(raw_text, variables)
    return resolve_spintax(text_with_tags)


# ═══════════════════════════════════════════════════════════════
#             SPAM & DELIVERABILITY ANALYZER
# ═══════════════════════════════════════════════════════════════

def analyze_spam(subject: str, body: str) -> Dict[str, Any]:
    """
    Comprehensive Deliverability & Spam Score Analyzer.
    Returns:
    - score (0 - 100, where 100 is pristine deliverability)
    - rating ('Pristine', 'Good', 'Caution', 'High Spam Risk')
    - detected_triggers (list of found words)
    - issues (list of problems)
    - recommendations (how to improve)
    """
    score = 100
    detected_triggers = []
    issues = []
    recommendations = []

    full_text = f"{subject} {body}".lower()

    # 1. High risk triggers
    for trig in SPAM_TRIGGERS["high_risk"]:
        if trig in full_text:
            score -= 15
            detected_triggers.append(f"High risk: '{trig}'")

    # 2. Medium risk triggers
    for trig in SPAM_TRIGGERS["medium_risk"]:
        if trig in full_text:
            score -= 8
            detected_triggers.append(f"Medium risk: '{trig}'")

    # 3. Overused marketing buzzwords
    for trig in SPAM_TRIGGERS["overused_marketing"]:
        if trig in full_text:
            score -= 5
            detected_triggers.append(f"Marketing buzzword: '{trig}'")

    # 4. Subject line checks
    if subject:
        # All caps subject
        upper_letters = sum(1 for c in subject if c.isupper())
        total_letters = sum(1 for c in subject if c.isalpha())
        if total_letters > 0 and (upper_letters / total_letters) > 0.4:
            score -= 15
            issues.append("Subject line has excessive capital letters (>40%).")
            recommendations.append("Use natural casing or lowercase in the subject line.")

        # Punctuation in subject
        if "!" in subject:
            score -= 10
            issues.append("Exclamation mark in subject line triggers spam filters.")
            recommendations.append("Remove exclamation marks from the subject line.")
        if "$$" in subject or "€" in subject or "£" in subject:
            score -= 15
            issues.append("Currency symbols in subject line.")
            recommendations.append("Avoid currency symbols in subject lines.")

        # Subject length
        words = len(subject.split())
        if words > 9:
            score -= 5
            issues.append(f"Subject is too long ({words} words). Cold emails perform best with 2-5 words.")
            recommendations.append("Shorten subject line to 2-5 words (e.g. 'quick question', 'collab inquiry').")
        elif words == 0:
            score -= 30
            issues.append("Missing subject line.")

    # 5. Body checks
    if body:
        # Check link count
        links = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', body)
        if len(links) > 2:
            score -= 15
            issues.append(f"Body contains {len(links)} links. Multiple links severely hurt first-touch deliverability.")
            recommendations.append("Keep maximum 1 link or zero links in the initial cold opener.")

        # Excessive exclamation in body
        exclamations = body.count("!")
        if exclamations > 3:
            score -= 10
            issues.append(f"Body contains {exclamations} exclamation marks.")
            recommendations.append("Tone down punctuation to sound conversational and human.")

        # Length check
        body_words = len(body.split())
        if body_words > 250:
            score -= 10
            issues.append(f"Body is quite long ({body_words} words). Cold openers should be under 150 words.")
            recommendations.append("Shorten the body to 50-125 words for higher response rates.")
        elif body_words < 15:
            score -= 10
            issues.append("Body is too short/sparse.")

    score = max(0, min(100, score))

    if score >= 85:
        rating = "Pristine (High Deliverability)"
    elif score >= 70:
        rating = "Good (Minor Improvements Possible)"
    elif score >= 50:
        rating = "Caution (May Hit Promotions/Spam)"
    else:
        rating = "High Spam Risk (Likely Spam Folder)"

    return {
        "score": score,
        "rating": rating,
        "detected_triggers": detected_triggers,
        "issues": issues,
        "recommendations": recommendations,
    }


# ═══════════════════════════════════════════════════════════════
#             DNS MX & DELIVERABILITY VALIDATOR
# ═══════════════════════════════════════════════════════════════

def validate_email_deliverability(email: str) -> Dict[str, Any]:
    """
    Validates email format, domain MX records, disposable providers, and role accounts.
    Protects domain sender reputation by preventing hard bounces.
    """
    email = (email or "").strip().lower()

    # 1. Basic format
    if not re.match(r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z0-9\.\-]+$", email):
        return {
            "valid": False,
            "deliverable": False,
            "reason": "Invalid email syntax format."
        }

    user_part, domain = email.split("@", 1)

    # 2. Disposable check
    if domain in DISPOSABLE_DOMAINS:
        return {
            "valid": True,
            "deliverable": False,
            "is_disposable": True,
            "reason": "Temporary/disposable email address (high bounce probability)."
        }

    # 3. Role-based check
    is_role = user_part in ROLE_PREFIXES

    # 4. DNS MX Lookup
    try:
        mx_records = dns.resolver.resolve(domain, "MX", lifetime=5)
        mx_hosts = [str(r.exchange).rstrip(".") for r in mx_records]
        if not mx_hosts:
            return {
                "valid": True,
                "deliverable": False,
                "reason": f"Domain '{domain}' has no MX mail server records."
            }
        return {
            "valid": True,
            "deliverable": True,
            "domain": domain,
            "mx_records": mx_hosts[:3],
            "is_role_based": is_role,
            "reason": f"Active MX records verified ({mx_hosts[0]})."
        }
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        return {
            "valid": True,
            "deliverable": False,
            "reason": f"Domain '{domain}' does not exist or has no mail configuration."
        }
    except Exception as e:
        # Fallback if DNS timeout or offline
        logger.warning(f"DNS MX check failed for {domain}: {e}")
        return {
            "valid": True,
            "deliverable": True,
            "is_role_based": is_role,
            "reason": f"Syntax valid (DNS lookup timeout: {e})."
        }


# ═══════════════════════════════════════════════════════════════
#             INTENT & UNSUBSCRIBE CLASSIFIER
# ═══════════════════════════════════════════════════════════════

UNSUBSCRIBE_KEYWORDS = [
    "unsubscribe", "remove me", "stop emailing", "take me off",
    "opt out", "opt-out", "don't email me", "lose my email",
    "do not contact", "wrong person", "cease and desist", "never email"
]

def classify_reply_intent(subject: str, body: str) -> Dict[str, Any]:
    """
    Classifies incoming reply intent and checks for unsubscribe requests.
    Categories:
    - 'unsubscribe' (Auto-blacklist + cancel followups)
    - 'not_interested' (Polite decline)
    - 'interested' (Wants to collaborate / positive)
    - 'rate_inquiry' (Asking for budget, fee, rate card)
    - 'out_of_office' (Automated response)
    - 'general_reply' (Needs review)
    """
    text = f"{subject} {body}".lower()

    # 1. Unsubscribe check
    for kw in UNSUBSCRIBE_KEYWORDS:
        if kw in text:
            return {
                "intent": "unsubscribe",
                "sentiment": "negative",
                "is_unsubscribe": True,
                "confidence": 0.95,
                "suggested_action": "Auto-blacklist and cancel all future followups"
            }

    # 2. Out of Office check
    ooo_triggers = ["out of the office", "on vacation", "away from my desk", "auto-reply", "automatic reply"]
    if any(t in text for t in ooo_triggers):
        return {
            "intent": "out_of_office",
            "sentiment": "neutral",
            "is_unsubscribe": False,
            "confidence": 0.90,
            "suggested_action": "Ignore or reschedule followup for later"
        }

    # 3. Not interested check
    not_interested_triggers = [
        "not interested", "not looking for", "no thanks", "pass on this",
        "don't have time", "not taking on", "we're good", "not for us"
    ]
    if any(t in text for t in not_interested_triggers):
        return {
            "intent": "not_interested",
            "sentiment": "negative",
            "is_unsubscribe": False,
            "confidence": 0.85,
            "suggested_action": "Mark closed_lost and send graceful sign-off"
        }

    # 4. Rate inquiry
    rate_triggers = [
        "rates", "rate card", "pricing", "how much", "budget", "quote",
        "compensation", "paid", "fee", "cost", "deliverables", "package"
    ]
    if any(t in text for t in rate_triggers):
        return {
            "intent": "rate_inquiry",
            "sentiment": "positive",
            "is_unsubscribe": False,
            "confidence": 0.88,
            "suggested_action": "Share agency tier package and upside commission"
        }

    # 5. General interest
    interested_triggers = [
        "sounds interesting", "would love to", "tell me more", "let's connect",
        "send details", "interested", "available for", "open to", "happy to chat",
        "sounds good", "let's talk", "hop on a call"
    ]
    if any(t in text for t in interested_triggers):
        return {
            "intent": "interested",
            "sentiment": "positive",
            "is_unsubscribe": False,
            "confidence": 0.90,
            "suggested_action": "Send collaboration proposal and schedule next step"
        }

    return {
        "intent": "general_reply",
        "sentiment": "neutral",
        "is_unsubscribe": False,
        "confidence": 0.60,
        "suggested_action": "Review draft and customize reply"
    }


# ═══════════════════════════════════════════════════════════════
#             WARMUP SCHEDULE CALCULATOR
# ═══════════════════════════════════════════════════════════════

def get_warmup_limit_for_day(warmup_day: int, target_limit: int = 50) -> int:
    """
    Ramps sending capacity safely:
    Day 1: 5
    Day 2: 8
    Day 3: 12
    Day 4: 18
    Day 5: 25
    Day 6: 32
    Day 7: 40
    Day 8+: target_limit
    """
    ramp = [5, 8, 12, 18, 25, 32, 40]
    if warmup_day <= len(ramp):
        return min(ramp[warmup_day - 1], target_limit)
    return target_limit
