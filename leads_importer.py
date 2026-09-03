"""
Flinza — Leads Importer
Imports leads from CSV files with flexible column mapping.
Supports deduplication, auto-tier assignment, and blacklist filtering.
"""

import csv
import io
import logging
import re

import database as db

logger = logging.getLogger(__name__)

# ─── Column name aliases (maps common names → internal names) ─────
COLUMN_ALIASES = {
    "email":     ["email", "email_address", "e-mail", "mail"],
    "name":      ["name", "full_name", "fullname", "contact_name", "first_name"],
    "handle":    ["handle", "username", "instagram", "ig", "twitter", "profile", "url"],
    "followers": ["followers", "follower_count", "subs", "subscribers", "audience"],
    "bio":       ["bio", "description", "about", "profile_bio"],
    "niche":     ["niche", "category", "niche_category", "vertical", "topic"],
    "company":   ["company", "brand", "business", "org", "organization"],
    "website":   ["website", "site", "url", "web"],
    "platform":  ["platform", "channel", "social", "network"],
    "notes":     ["notes", "note", "comment", "remarks"],
}


def _map_columns(header_row: list) -> dict:
    """Build a mapping from internal field name → CSV column index."""
    header_lower = [h.strip().lower().replace(" ", "_") for h in header_row]
    mapping = {}
    for internal, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in header_lower:
                mapping[internal] = header_lower.index(alias)
                break
    return mapping


def _parse_followers(val: str) -> int | None:
    """Parse '125K', '1.2M', '50000' → integer."""
    if not val:
        return None
    val = str(val).strip().upper().replace(",", "")
    try:
        if val.endswith("K"):
            return int(float(val[:-1]) * 1_000)
        if val.endswith("M"):
            return int(float(val[:-1]) * 1_000_000)
        return int(float(val))
    except Exception:
        return None


def assign_tier(followers: int | None) -> str:
    if not followers:
        return "unknown"
    if followers < 50_000:
        return "under_50k"
    if followers < 100_000:
        return "50k_100k"
    return "100k_plus"


def import_from_csv_bytes(content: bytes, source: str = "csv_import") -> dict:
    """
    Parse CSV bytes and import leads into the database.
    Returns: {added, skipped, blacklisted, invalid, errors}
    """
    added       = 0
    skipped     = 0
    blacklisted = 0
    invalid     = 0
    errors      = []

    try:
        text = content.decode("utf-8-sig", errors="replace")
    except Exception:
        text = content.decode("latin-1", errors="replace")

    reader   = csv.reader(io.StringIO(text))
    rows     = list(reader)

    if not rows:
        return {"added": 0, "skipped": 0, "blacklisted": 0, "invalid": 0, "errors": ["Empty file"]}

    header  = rows[0]
    mapping = _map_columns(header)

    if "email" not in mapping:
        return {"added": 0, "skipped": 0, "blacklisted": 0, "invalid": 0,
                "errors": ["CSV must have an 'email' column"]}

    for i, row in enumerate(rows[1:], start=2):
        if not row or all(c.strip() == "" for c in row):
            continue

        def get(field):
            idx = mapping.get(field)
            if idx is None or idx >= len(row):
                return None
            val = row[idx].strip()
            return val if val else None

        email_val = get("email")
        if not email_val or "@" not in email_val:
            invalid += 1
            continue

        email_val = email_val.lower()

        # Blacklist check
        if db.is_blacklisted(email_val):
            blacklisted += 1
            continue

        followers_raw = get("followers")
        followers     = _parse_followers(followers_raw)
        tier          = assign_tier(followers)

        kwargs = {
            "name":      get("name"),
            "handle":    get("handle"),
            "platform":  get("platform"),
            "followers": followers,
            "tier":      tier,
            "bio":       get("bio"),
            "niche":     get("niche"),
            "company":   get("company"),
            "website":   get("website"),
            "notes":     get("notes"),
            "source":    source,
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        try:
            _, is_new = db.add_or_get_lead(email_val, **kwargs)
            if is_new:
                added += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")
            invalid += 1

    return {"added": added, "skipped": skipped, "blacklisted": blacklisted,
            "invalid": invalid, "errors": errors}


def import_from_csv_path(path: str, source: str = "csv_file") -> dict:
    with open(path, "rb") as f:
        return import_from_csv_bytes(f.read(), source=source)


def add_single_lead(email: str, name: str = None, **kwargs) -> dict:
    """Add a single lead manually. Returns {success, lead_id, is_new, error}."""
    if not email or "@" not in email:
        return {"success": False, "error": "Invalid email address"}

    email = email.lower().strip()

    if db.is_blacklisted(email):
        return {"success": False, "error": f"{email} is blacklisted"}

    followers = kwargs.get("followers")
    if followers and not kwargs.get("tier"):
        kwargs["tier"] = assign_tier(followers)

    try:
        lead_id, is_new = db.add_or_get_lead(email, name=name, **kwargs)
        return {"success": True, "lead_id": lead_id, "is_new": is_new}
    except Exception as e:
        return {"success": False, "error": str(e)}
