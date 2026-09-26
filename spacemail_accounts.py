"""
spacemail_accounts.py — Spacemail (Spaceship) mailbox fleet loader.
===================================================================

The Flinza fleet sends through Spacemail's relays instead of Gmail / Amazon SES:

    SMTP   mail.spacemail.com : 465   (SSL/TLS, username = full email address)
    IMAP   mail.spacemail.com : 993   (SSL/TLS)

Accounts are discovered from, in order of precedence:
  1. SPACEMAIL_ACCOUNTS        — JSON array in one env var (hosted deploys)
  2. SPACEMAIL_<n>_EMAIL/PASS  — numbered pairs (local .env)
  3. spacemail_accounts.json   — fleet file next to this module

No password is ever hardcoded here: secrets live in .env or the host's
env-var settings, never in this file.
"""

import json
import os
import re
from datetime import date
from pathlib import Path

# Loads .env into os.environ (no-op on hosts that inject real env vars).
try:
    import config  # noqa: F401
    from config import load_env as _load_env
    _load_env()
except Exception:  # keep the loader usable even standalone
    pass

PROVIDER  = "spacemail"
IMAP_HOST = os.environ.get("SPACEMAIL_IMAP_HOST", "mail.spacemail.com").strip() or "mail.spacemail.com"
IMAP_PORT = int(os.environ.get("SPACEMAIL_IMAP_PORT", "993") or 993)
SMTP_HOST = os.environ.get("SPACEMAIL_SMTP_HOST", "mail.spacemail.com").strip() or "mail.spacemail.com"
SMTP_PORT = int(os.environ.get("SPACEMAIL_SMTP_PORT", "465") or 465)

_PAIR_RE = re.compile(r"^SPACEMAIL_(\d+)_EMAIL$", re.I)


def _normalize(data) -> list:
    if isinstance(data, dict):
        data = data.get("accounts", [])
    out = []
    for row in data or []:
        if not isinstance(row, dict):
            continue
        email    = (row.get("email") or row.get("user") or "").strip()
        password = (row.get("password") or row.get("pass") or "").strip()
        if email and password and "@" in email:
            out.append({"email": email, "password": password})
    return out


def _from_json_env() -> list:
    raw = (os.environ.get("SPACEMAIL_ACCOUNTS") or "").strip()
    if not raw:
        return []
    try:
        return _normalize(json.loads(raw))
    except ValueError:
        return []


def _from_env_pairs() -> list:
    found = {}
    for key, value in os.environ.items():
        m = _PAIR_RE.match(key)
        if not m:
            continue
        email = (value or "").strip()
        password = (os.environ.get(f"SPACEMAIL_{m.group(1)}_PASS") or "").strip()
        if email and password:
            found[int(m.group(1))] = {"email": email, "password": password}
    return [found[k] for k in sorted(found)]


def _from_json_file() -> list:
    path = Path(__file__).parent / "spacemail_accounts.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return _normalize(json.load(f))
    except (ValueError, OSError):
        return []


def load_accounts() -> list:
    """Complete fleet, deduplicated by address."""
    merged = []
    for group in (_from_json_env(), _from_env_pairs(), _from_json_file()):
        merged.extend(group)

    seen, fleet = set(), []
    for acc in merged:
        key = acc["email"].lower()
        if key in seen:
            continue
        seen.add(key)
        fleet.append(acc)
    return fleet


def account_domains() -> list:
    """Sending domains present in the fleet, e.g. flinzamedia.com."""
    return sorted({a["email"].split("@")[1].lower() for a in load_accounts()})


def imap_settings(account) -> tuple:
    """
    Resolve (host, port) for IMAP reply-watching.

    Spacemail mailboxes must go to mail.spacemail.com instead of the Gmail
    default that reply_watcher historically assumed.
    """
    get = account.get if hasattr(account, "get") else (lambda k, d=None: None)
    if (get("provider") or "").strip().lower() == PROVIDER:
        return IMAP_HOST, IMAP_PORT
    if (get("smtp_host") or "").strip().lower() == SMTP_HOST.lower():
        return IMAP_HOST, IMAP_PORT
    return "imap.gmail.com", 993


def relay_for(email: str, fallback_host: str = "smtp.gmail.com", fallback_port: int = 587) -> tuple:
    """
    Resolve (provider, host, port) for an address.

    Spacemail domains route to mail.spacemail.com:465; anything else keeps the
    historical Gmail default so existing accounts are unaffected.
    """
    domain = (email or "").split("@")[-1].strip().lower()
    if domain and domain in account_domains():
        return PROVIDER, SMTP_HOST, SMTP_PORT
    return "smtp", fallback_host, fallback_port


def sync_to_db(daily_limit: int = 80, label: str = "Spacemail") -> dict:
    """
    Insert/refresh every fleet mailbox in the CRM accounts table.

    Idempotent: existing addresses are updated in place (password, relay,
    reactivated) rather than duplicated.
    """
    import database as db

    fleet = load_accounts()
    if not fleet:
        return {"success": False, "error": "No Spacemail accounts found in .env / environment"}

    created = updated = 0
    conn = db.get_db()
    try:
        for acc in fleet:
            email = acc["email"]
            row = conn.execute(
                "SELECT email FROM gmail_accounts WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE gmail_accounts
                          SET app_password = ?, provider = ?, smtp_host = ?, smtp_port = ?,
                              smtp_user = ?, smtp_pass = ?, active = 1
                        WHERE email = ? COLLATE NOCASE""",
                    (acc["password"], PROVIDER, SMTP_HOST, SMTP_PORT, email, acc["password"], email),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO gmail_accounts
                           (email, app_password, daily_limit, last_reset_date, provider,
                            smtp_host, smtp_port, smtp_user, smtp_pass, label)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (email, acc["password"], daily_limit, date.today().isoformat(),
                     PROVIDER, SMTP_HOST, SMTP_PORT, email, acc["password"], label),
                )
                created += 1
        conn.commit()
    finally:
        conn.close()

    return {"success": True, "created": created, "updated": updated, "total": len(fleet)}


if __name__ == "__main__":
    fleet = load_accounts()
    print(f"Discovered {len(fleet)} Spacemail mailboxes")
    for a in fleet:
        print(f"  {a['email']:<32} (password {len(a['password'])} chars)")
    print("Domains:", ", ".join(account_domains()))
