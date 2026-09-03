"""
Flinza — Database module
SQLite, all in one file. Leads, emails, accounts, replies, followups, settings, templates.
"""

import sqlite3
import json
import hashlib
from datetime import datetime, date, timedelta
from config import (
    DB_PATH, DEFAULT_DAILY_LIMIT, DEFAULT_MIN_INTERVAL, DEFAULT_MAX_INTERVAL,
    DEFAULT_FOLLOWUP_DAYS, DEFAULT_MAX_FOLLOWUPS, DEFAULT_REPLY_CHECK_MINUTES,
    DEFAULT_AUTO_REPLY_MODE, DEFAULT_SYSTEM_PROMPT,
)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db():
    """Create all tables and indices."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE NOT NULL,
            handle TEXT,
            platform TEXT DEFAULT 'email',
            followers INTEGER,
            tier TEXT,
            bio TEXT,
            niche TEXT,
            company TEXT,
            website TEXT,
            stage TEXT DEFAULT 'new',
            source TEXT,
            score INTEGER DEFAULT 0,
            blacklisted INTEGER DEFAULT 0,
            unsubscribed INTEGER DEFAULT 0,
            notes TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_contact TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS gmail_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            app_password TEXT NOT NULL,
            daily_limit INTEGER DEFAULT 50,
            sent_today INTEGER DEFAULT 0,
            last_reset_date TEXT,
            active INTEGER DEFAULT 1,
            proxy_url TEXT,
            warmup_mode INTEGER DEFAULT 0,
            warmup_day INTEGER DEFAULT 1,
            label TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS smtp_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT UNIQUE NOT NULL,
            display_name TEXT,
            smtp_user TEXT NOT NULL,
            smtp_pass TEXT,
            daily_sent INTEGER DEFAULT 0,
            daily_limit INTEGER DEFAULT 20,
            last_reset TEXT,
            is_active INTEGER DEFAULT 1,
            warmup_day INTEGER DEFAULT 1,
            source TEXT DEFAULT 'manual',
            cf_rule_id TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS emails_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            from_account TEXT,
            to_email TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            message_type TEXT DEFAULT 'opener',
            status TEXT DEFAULT 'queued',
            queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            scheduled_for TIMESTAMP,
            error_msg TEXT,
            message_id TEXT,
            campaign_id INTEGER,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            from_email TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subject TEXT,
            body TEXT,
            sentiment TEXT,
            intent TEXT,
            ai_draft_subject TEXT,
            ai_draft_body TEXT,
            handled INTEGER DEFAULT 0,
            action_taken TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS followups_scheduled (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            scheduled_for TIMESTAMP,
            followup_number INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT DEFAULT 'opener',
            subject TEXT,
            body TEXT,
            use_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            status TEXT DEFAULT 'draft',
            total_leads INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            reply_count INTEGER DEFAULT 0,
            bounce_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            domain TEXT,
            reason TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT,
            google_id TEXT,
            role TEXT DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_email TEXT UNIQUE NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            token_expiry TIMESTAMP,
            client_id TEXT,
            client_secret TEXT,
            scopes TEXT,
            provider TEXT DEFAULT 'google',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS campaign_sequences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            step_number INTEGER NOT NULL,
            delay_days INTEGER DEFAULT 3,
            condition_type TEXT DEFAULT 'always',
            subject_a TEXT NOT NULL,
            body_a TEXT NOT NULL,
            subject_b TEXT,
            body_b TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS email_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER UNIQUE,
            tracking_token TEXT UNIQUE NOT NULL,
            opened_at TIMESTAMP,
            open_count INTEGER DEFAULT 0,
            clicked_at TIMESTAMP,
            click_count INTEGER DEFAULT 0,
            last_user_agent TEXT,
            last_ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (email_id) REFERENCES emails_sent(id)
        );

        CREATE TABLE IF NOT EXISTS custom_api_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            provider_type TEXT DEFAULT 'openai_compatible',
            base_url TEXT NOT NULL,
            api_key TEXT,
            model_name TEXT NOT NULL,
            temperature REAL DEFAULT 0.85,
            max_tokens INTEGER DEFAULT 2048,
            custom_headers_json TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS dns_audit_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE NOT NULL,
            spf_record TEXT,
            spf_status TEXT,
            dkim_record TEXT,
            dkim_status TEXT,
            dmarc_record TEXT,
            dmarc_status TEXT,
            mx_status TEXT,
            overall_score INTEGER DEFAULT 0,
            last_audited TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            events_json TEXT,
            secret TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Indices for performance
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
        CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
        CREATE INDEX IF NOT EXISTS idx_emails_status ON emails_sent(status, queued_at);
        CREATE INDEX IF NOT EXISTS idx_emails_lead ON emails_sent(lead_id);
        CREATE INDEX IF NOT EXISTS idx_replies_lead ON replies(lead_id);
        CREATE INDEX IF NOT EXISTS idx_followups_due ON followups_scheduled(status, scheduled_for);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_blacklist_email ON blacklist(email) WHERE email IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_blacklist_domain ON blacklist(domain) WHERE domain IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_tracking_token ON email_tracking(tracking_token);
        CREATE INDEX IF NOT EXISTS idx_sequences_camp ON campaign_sequences(campaign_id, step_number);
    """)

    # Multi-provider column migrations for gmail_accounts (Cloudflare API, Amazon SES, SMTP)
    for col, col_type in [
        ("provider", "TEXT DEFAULT 'smtp'"),
        ("smtp_host", "TEXT"),
        ("smtp_port", "INTEGER"),
        ("smtp_user", "TEXT"),
        ("smtp_pass", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE gmail_accounts ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    # Out-of-the-box routing mode migrations for smtp_aliases (Gmail Send-As vs Cloudflare API vs Amazon SES)
    for col, col_type in [
        ("routing_mode", "TEXT DEFAULT 'gmail_send_as'"),
        ("smtp_host", "TEXT"),
        ("smtp_port", "INTEGER"),
        ("custom_smtp_user", "TEXT"),
        ("custom_smtp_pass", "TEXT"),
        ("forward_to", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE smtp_aliases ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    # Migrations for leads: AI hyper-personalization & deep deliverability checks
    for col, col_type in [
        ("custom_hook", "TEXT"),
        ("linkedin", "TEXT"),
        ("ai_subject", "TEXT"),
        ("ai_draft", "TEXT"),
        ("deliverability_status", "TEXT DEFAULT 'unverified'"),
        ("deliverability_score", "INTEGER DEFAULT 100"),
        ("last_audit_details", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    _init_default_settings(conn)
    conn.close()


def _init_default_settings(conn):
    defaults = {
        "min_interval_seconds":  str(DEFAULT_MIN_INTERVAL),
        "max_interval_seconds":  str(DEFAULT_MAX_INTERVAL),
        "followup_days":         json.dumps(DEFAULT_FOLLOWUP_DAYS),
        "max_followups":         str(DEFAULT_MAX_FOLLOWUPS),
        "reply_check_minutes":   str(DEFAULT_REPLY_CHECK_MINUTES),
        "auto_reply_mode":       DEFAULT_AUTO_REPLY_MODE,
        "system_prompt":         DEFAULT_SYSTEM_PROMPT,
        "sender_name":           "The Team",
        "openrouter_api_key":    "",
        "openrouter_model":      "meta-llama/llama-3.1-8b-instruct:free",
        "gemini_api_key":        "",
        "groq_api_key":          "",
        "nvidia_api_key":        "",
        "mistral_api_key":       "",
        "cf_api_token":          "",
        "cf_account_id":         "",
        "cf_zone_id":            "",
        "cf_domain":             "",
        "warmup_enabled":        "0",
        "smart_hours_enabled":   "0",
        "smart_hours_start":     "9",
        "smart_hours_end":       "18",
        "bounce_blacklist":      "1",
        "optout_footer_enabled": "0",
        "optout_text":           "\n\nPS: If you'd rather not hear from me again, simply reply with 'stop' and I will immediately take you off our list.",
        "google_client_id":      "",
        "google_client_secret":  "",
        "tracking_base_url":     "http://localhost:8000",
        "tracking_enabled":      "1",
        "studio_port":           "8000",
        "custom_llm_active_id":  "",
        "aws_ses_region":        "us-east-1",
        "aws_ses_smtp_host":     "email-smtp.us-east-1.amazonaws.com",
        "aws_ses_smtp_port":     "587",
        "aws_ses_smtp_user":     "",
        "aws_ses_smtp_pass":     "",
        "inbound_webhook_secret": "flinza_cf_inbound_secret_2026",
    }
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
#                         SETTINGS
# ═══════════════════════════════════════════════════════════════

def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value) if value is not None else "")
    )
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# ═══════════════════════════════════════════════════════════════
#                      GMAIL ACCOUNTS
# ═══════════════════════════════════════════════════════════════

def add_account(
    email,
    app_password,
    daily_limit=DEFAULT_DAILY_LIMIT,
    proxy_url=None,
    label=None,
    provider="smtp",
    smtp_host=None,
    smtp_port=None,
    smtp_user=None,
    smtp_pass=None
):
    conn = get_db()
    today = date.today().isoformat()
    try:
        conn.execute(
            """INSERT INTO gmail_accounts 
               (email, app_password, daily_limit, last_reset_date, proxy_url, label, provider, smtp_host, smtp_port, smtp_user, smtp_pass) 
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (email, app_password, daily_limit, today, proxy_url, label, provider, smtp_host, smtp_port, smtp_user, smtp_pass)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def add_cloudflare_sending_account(from_email: str, daily_limit: int = 100, label: str = "Cloudflare Native API"):
    """Adds a Cloudflare Email Sending account ($5/mo Workers Paid plan)."""
    return add_account(
        email=from_email,
        app_password="cf_api_sending",
        daily_limit=daily_limit,
        label=label,
        provider="cloudflare_api"
    )


def add_amazon_ses_account(
    from_email: str,
    smtp_user: str,
    smtp_pass: str,
    smtp_host: str = "email-smtp.us-east-1.amazonaws.com",
    smtp_port: int = 587,
    daily_limit: int = 200,
    label: str = "Amazon SES"
):
    """Adds an Amazon SES SMTP sending account."""
    return add_account(
        email=from_email,
        app_password=smtp_pass,
        daily_limit=daily_limit,
        label=label,
        provider="amazon_ses",
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass
    )


def remove_account(email):
    conn = get_db()
    conn.execute("UPDATE emails_sent SET from_account=NULL WHERE from_account=?", (email,))
    conn.execute("DELETE FROM smtp_aliases WHERE smtp_user=?", (email,))
    conn.execute("DELETE FROM gmail_accounts WHERE email=?", (email,))
    conn.commit()
    conn.close()


def get_all_accounts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM gmail_accounts ORDER BY added_at").fetchall()
    conn.close()
    return rows


def set_account_active(email, active: bool):
    conn = get_db()
    conn.execute("UPDATE gmail_accounts SET active=? WHERE email=?", (1 if active else 0, email))
    conn.commit()
    conn.close()


def set_account_limit(email, limit: int):
    conn = get_db()
    conn.execute("UPDATE gmail_accounts SET daily_limit=? WHERE email=?", (limit, email))
    conn.commit()
    conn.close()


def set_account_proxy(email, proxy_url: str):
    conn = get_db()
    conn.execute("UPDATE gmail_accounts SET proxy_url=? WHERE email=?", (proxy_url or None, email))
    conn.commit()
    conn.close()


def get_next_available_account():
    """Round-robin: pick least-used account/alias that still has daily capacity."""
    conn = get_db()
    today = date.today().isoformat()

    # Reset daily counters on new day
    conn.execute(
        "UPDATE gmail_accounts SET sent_today=0, last_reset_date=? WHERE last_reset_date!=? OR last_reset_date IS NULL",
        (today, today)
    )
    conn.execute(
        "UPDATE smtp_aliases SET daily_sent=0, last_reset=? WHERE last_reset!=? OR last_reset IS NULL",
        (today, today)
    )
    conn.commit()

    candidates = []

    # Accounts with remaining capacity
    acc_rows = conn.execute("""
        SELECT email as id, COALESCE(provider, 'gmail') as type, email as from_email,
               COALESCE(smtp_user, email) as smtp_user,
               COALESCE(smtp_pass, app_password) as smtp_pass,
               provider, smtp_host, smtp_port,
               proxy_url, sent_today, daily_limit, last_used,
               NULL as display_name
        FROM gmail_accounts
        WHERE active=1 AND sent_today < daily_limit
    """).fetchall()
    candidates.extend([dict(r) for r in acc_rows])

    # Aliases with flexible routing modes (Gmail Send-As vs Cloudflare API vs Amazon SES)
    alias_rows = conn.execute("""
        SELECT a.alias as id, 'alias' as type, a.alias as from_email,
               COALESCE(a.custom_smtp_user, a.smtp_user) as smtp_user,
               COALESCE(a.custom_smtp_pass, a.smtp_pass, g.app_password) as smtp_pass,
               COALESCE(a.routing_mode, g.provider, 'gmail_send_as') as routing_mode,
               COALESCE(a.smtp_host, g.smtp_host) as smtp_host,
               COALESCE(a.smtp_port, g.smtp_port) as smtp_port,
               COALESCE(a.routing_mode, g.provider) as provider,
               g.proxy_url, a.daily_sent as sent_today, a.daily_limit,
               NULL as last_used, a.display_name
        FROM smtp_aliases a
        LEFT JOIN gmail_accounts g ON a.smtp_user = g.email
        WHERE a.is_active=1 AND a.daily_sent < a.daily_limit
          AND (g.active=1 OR a.routing_mode IN ('cloudflare_api', 'external_smtp'))
    """).fetchall()
    candidates.extend([dict(r) for r in alias_rows])

    conn.close()

    if not candidates:
        return None

    # Prefer aliases (better deliverability diversity), then least sent today
    candidates.sort(key=lambda x: (x["sent_today"], 0 if x["type"] == "alias" else 1))
    return candidates[0]


def increment_account_sent(account_id: str, is_alias: bool = False):
    conn = get_db()
    now = datetime.now().isoformat()
    if is_alias:
        conn.execute(
            "UPDATE smtp_aliases SET daily_sent=daily_sent+1 WHERE alias=?",
            (account_id,)
        )
        row = conn.execute("SELECT smtp_user FROM smtp_aliases WHERE alias=?", (account_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE gmail_accounts SET sent_today=sent_today+1, last_used=? WHERE email=?",
                (now, row["smtp_user"])
            )
    else:
        conn.execute(
            "UPDATE gmail_accounts SET sent_today=sent_today+1, last_used=? WHERE email=?",
            (now, account_id)
        )
    conn.commit()
    conn.close()


def total_remaining_today():
    conn = get_db()
    today = date.today().isoformat()
    conn.execute(
        "UPDATE gmail_accounts SET sent_today=0, last_reset_date=? WHERE last_reset_date!=? OR last_reset_date IS NULL",
        (today, today)
    )
    conn.execute(
        "UPDATE smtp_aliases SET daily_sent=0, last_reset=? WHERE last_reset!=? OR last_reset IS NULL",
        (today, today)
    )
    conn.commit()
    r1 = conn.execute(
        "SELECT COALESCE(SUM(daily_limit-sent_today),0) as r FROM gmail_accounts WHERE active=1 AND sent_today<daily_limit"
    ).fetchone()
    r2 = conn.execute(
        "SELECT COALESCE(SUM(daily_limit-daily_sent),0) as r FROM smtp_aliases WHERE is_active=1 AND daily_sent<daily_limit"
    ).fetchone()
    conn.close()
    return (r1["r"] if r1 else 0) + (r2["r"] if r2 else 0)


# ═══════════════════════════════════════════════════════════════
#                       SMTP ALIASES
# ═══════════════════════════════════════════════════════════════

def add_alias(
    alias,
    smtp_user,
    smtp_pass=None,
    display_name=None,
    source="manual",
    cf_rule_id=None,
    daily_limit=20,
    routing_mode="gmail_send_as",
    smtp_host=None,
    smtp_port=None,
    custom_smtp_user=None,
    custom_smtp_pass=None,
    forward_to=None
):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO smtp_aliases
               (alias, smtp_user, smtp_pass, display_name, source, cf_rule_id, daily_limit,
                routing_mode, smtp_host, smtp_port, custom_smtp_user, custom_smtp_pass, forward_to)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (alias, smtp_user, smtp_pass, display_name, source, cf_rule_id, daily_limit,
             routing_mode, smtp_host, smtp_port, custom_smtp_user, custom_smtp_pass, forward_to)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def update_alias_routing(
    alias: str,
    routing_mode: str,
    smtp_user: str = None,
    smtp_host: str = None,
    smtp_port: int = None,
    custom_smtp_user: str = None,
    custom_smtp_pass: str = None,
    forward_to: str = None
):
    conn = get_db()
    conn.execute(
        """UPDATE smtp_aliases
           SET routing_mode=?,
               smtp_user=COALESCE(?, smtp_user),
               smtp_host=?,
               smtp_port=?,
               custom_smtp_user=?,
               custom_smtp_pass=?,
               forward_to=?
           WHERE alias=?""",
        (routing_mode, smtp_user, smtp_host, smtp_port, custom_smtp_user, custom_smtp_pass, forward_to, alias)
    )
    conn.commit()
    conn.close()
    return True


def get_all_aliases():
    conn = get_db()
    rows = conn.execute("SELECT * FROM smtp_aliases ORDER BY added_at DESC").fetchall()
    conn.close()
    return rows


def remove_alias(alias):
    conn = get_db()
    conn.execute("UPDATE emails_sent SET from_account=NULL WHERE from_account=?", (alias,))
    conn.execute("DELETE FROM smtp_aliases WHERE alias=?", (alias,))
    conn.commit()
    conn.close()


def toggle_alias(alias):
    conn = get_db()
    row = conn.execute("SELECT is_active FROM smtp_aliases WHERE alias=?", (alias,)).fetchone()
    if not row:
        conn.close()
        return None
    new_val = 0 if row["is_active"] else 1
    conn.execute("UPDATE smtp_aliases SET is_active=? WHERE alias=?", (new_val, alias))
    conn.commit()
    conn.close()
    return bool(new_val)


def set_alias_limit(alias, limit: int):
    conn = get_db()
    conn.execute("UPDATE smtp_aliases SET daily_limit=? WHERE alias=?", (limit, alias))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#                          LEADS
# ═══════════════════════════════════════════════════════════════

def add_or_get_lead(email: str, **kwargs):
    conn = get_db()
    existing = conn.execute("SELECT id FROM leads WHERE email=?", (email.lower(),)).fetchone()
    if existing:
        conn.close()
        return existing["id"], False

    fields = ["email"] + [k for k in kwargs if kwargs[k] is not None]
    values = [email.lower()] + [kwargs[k] for k in kwargs if kwargs[k] is not None]
    placeholders = ",".join("?" * len(fields))
    cur = conn.execute(
        f"INSERT INTO leads ({','.join(fields)}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    lead_id = cur.lastrowid
    conn.close()
    return lead_id, True


def get_lead(lead_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    return row


def get_lead_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE email=?", (email.lower(),)).fetchone()
    conn.close()
    return row


def get_leads(stage=None, blacklisted=False, unsubscribed=False, limit=None, search=None):
    conn = get_db()
    query = "SELECT * FROM leads WHERE 1=1"
    params = []
    if not blacklisted:
        query += " AND blacklisted=0"
    if not unsubscribed:
        query += " AND unsubscribed=0"
    if stage:
        if isinstance(stage, list):
            placeholders = ",".join("?" * len(stage))
            query += f" AND stage IN ({placeholders})"
            params.extend(stage)
        else:
            query += " AND stage=?"
            params.append(stage)
    if search:
        query += " AND (email LIKE ? OR name LIKE ? OR handle LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    query += " ORDER BY added_at DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_lead_by_id(lead_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_lead_ai_draft(lead_id: int, ai_subject: str, ai_draft: str):
    conn = get_db()
    conn.execute(
        "UPDATE leads SET ai_subject=?, ai_draft=? WHERE id=?",
        (ai_subject, ai_draft, lead_id)
    )
    conn.commit()
    conn.close()


def update_lead_deliverability(lead_id: int, status: str, score: int, details_json: str):
    conn = get_db()
    conn.execute(
        "UPDATE leads SET deliverability_status=?, deliverability_score=?, last_audit_details=? WHERE id=?",
        (status, score, details_json, lead_id)
    )
    conn.commit()
    conn.close()


def add_or_update_lead(name: str, email: str, company: str = None, niche: str = None, website: str = None, linkedin: str = None, custom_hook: str = None, stage: str = "new"):
    conn = get_db()
    email = email.strip().lower()
    existing = conn.execute("SELECT id FROM leads WHERE email=?", (email,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE leads
               SET name=COALESCE(?, name),
                   company=COALESCE(?, company),
                   niche=COALESCE(?, niche),
                   website=COALESCE(?, website),
                   linkedin=COALESCE(?, linkedin),
                   custom_hook=COALESCE(?, custom_hook)
               WHERE id=?""",
            (name, company, niche, website, linkedin, custom_hook, existing["id"])
        )
        lead_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO leads (name, email, company, niche, website, linkedin, custom_hook, stage)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, email, company, niche, website, linkedin, custom_hook, stage or "new")
        )
        lead_id = cur.lastrowid
    conn.commit()
    conn.close()
    return lead_id


def update_lead_stage(lead_id: int, stage: str):
    conn = get_db()
    conn.execute(
        "UPDATE leads SET stage=?, last_contact=? WHERE id=?",
        (stage, datetime.now().isoformat(), lead_id)
    )
    conn.commit()
    conn.close()


def blacklist_lead(lead_id: int, reason: str = "manual"):
    conn = get_db()
    conn.execute(
        "UPDATE leads SET blacklisted=1, stage='blacklisted', notes=COALESCE(notes||' | ','')|| ? WHERE id=?",
        (f"Blacklisted: {reason}", lead_id)
    )
    conn.commit()
    conn.close()


def unsubscribe_lead(lead_id: int):
    conn = get_db()
    conn.execute("UPDATE leads SET unsubscribed=1, stage='unsubscribed' WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()


def get_pipeline_breakdown():
    conn = get_db()
    rows = conn.execute(
        "SELECT stage, COUNT(*) as cnt FROM leads GROUP BY stage ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    return {r["stage"]: r["cnt"] for r in rows}


def is_blacklisted(email: str):
    domain = email.split("@")[-1].lower() if "@" in email else ""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM blacklist WHERE email=? OR domain=?",
        (email.lower(), domain)
    ).fetchone()
    # Also check leads table blacklisted flag
    row2 = conn.execute("SELECT blacklisted, unsubscribed FROM leads WHERE email=?", (email.lower(),)).fetchone()
    conn.close()
    if row:
        return True
    if row2 and (row2["blacklisted"] or row2["unsubscribed"]):
        return True
    return False


def add_to_blacklist(email=None, domain=None, reason="manual"):
    conn = get_db()
    try:
        if email:
            conn.execute("INSERT OR IGNORE INTO blacklist (email, reason) VALUES (?, ?)", (email.lower(), reason))
        if domain:
            conn.execute("INSERT OR IGNORE INTO blacklist (domain, reason) VALUES (?, ?)", (domain.lower(), reason))
        conn.commit()
    finally:
        conn.close()


def delete_lead(lead_id: int):
    conn = get_db()
    conn.execute("DELETE FROM followups_scheduled WHERE lead_id=?", (lead_id,))
    conn.execute("DELETE FROM conversation_history WHERE lead_id=?", (lead_id,))
    conn.execute("DELETE FROM replies WHERE lead_id=?", (lead_id,))
    conn.execute("UPDATE emails_sent SET lead_id=NULL WHERE lead_id=?", (lead_id,))
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#                         EMAILS
# ═══════════════════════════════════════════════════════════════

def log_email(lead_id, from_account, to_email, subject, body,
              message_type="opener", status="queued", scheduled_for=None, campaign_id=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO emails_sent
           (lead_id, from_account, to_email, subject, body, message_type, status, scheduled_for, campaign_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (lead_id, from_account, to_email, subject, body, message_type, status, scheduled_for, campaign_id)
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def mark_email_sent(email_id: int, message_id: str = None, from_account: str = None):
    conn = get_db()
    conn.execute(
        """UPDATE emails_sent
           SET status='sent', sent_at=?, message_id=?,
               from_account=COALESCE(?, from_account)
           WHERE id=?""",
        (datetime.now().isoformat(), message_id, from_account, email_id)
    )
    conn.commit()
    conn.close()


def mark_email_failed(email_id: int, error_msg: str):
    conn = get_db()
    conn.execute(
        "UPDATE emails_sent SET status='failed', error_msg=? WHERE id=?",
        (error_msg, email_id)
    )
    conn.commit()
    conn.close()


def get_queued_emails(limit=100):
    conn = get_db()
    rows = conn.execute(
        """SELECT e.*, l.name, l.handle, l.tier, l.followers, l.bio, l.niche
           FROM emails_sent e
           LEFT JOIN leads l ON e.lead_id = l.id
           WHERE e.status='queued'
           ORDER BY e.queued_at
           LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_emails_for_lead(lead_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM emails_sent WHERE lead_id=? ORDER BY queued_at",
        (lead_id,)
    ).fetchall()
    conn.close()
    return rows


def email_already_queued_or_sent(to_email: str):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM emails_sent WHERE to_email=? AND status IN ('sent','queued')",
        (to_email.lower(),)
    ).fetchone()
    conn.close()
    return row["c"] > 0


def retry_failed_emails():
    """Reset failed emails to queued status."""
    conn = get_db()
    cur = conn.execute(
        "UPDATE emails_sent SET status='queued', error_msg=NULL WHERE status='failed'"
    )
    conn.commit()
    count = cur.rowcount
    conn.close()
def get_sent_emails_history(limit=50, offset=0, status=None, search=None, from_account=None):
    """
    Returns paginated history of sent/failed/queued emails with lead info and tracking engagement.
    """
    conn = get_db()
    query = """
        SELECT e.id, e.lead_id, e.from_account, e.to_email, e.subject, e.body,
               e.message_type, e.status, e.sent_at, e.queued_at, e.error_msg,
               e.message_id, e.campaign_id,
               l.name as lead_name, l.company as lead_company, l.stage as lead_stage,
               t.open_count, t.opened_at, t.click_count, t.clicked_at, t.tracking_token
        FROM emails_sent e
        LEFT JOIN leads l ON e.lead_id = l.id
        LEFT JOIN email_tracking t ON e.id = t.email_id
        WHERE 1=1
    """
    params = []
    if status and status != "all":
        if status == "opened":
            query += " AND t.open_count > 0"
        elif status == "clicked":
            query += " AND t.click_count > 0"
        else:
            query += " AND e.status = ?"
            params.append(status)

    if from_account:
        query += " AND e.from_account = ?"
        params.append(from_account)

    if search:
        query += " AND (e.to_email LIKE ? OR e.subject LIKE ? OR l.name LIKE ? OR l.company LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s, s])

    query += " ORDER BY COALESCE(e.sent_at, e.queued_at) DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()

    count_query = "SELECT COUNT(*) as c FROM emails_sent e LEFT JOIN email_tracking t ON e.id = t.email_id WHERE 1=1"
    count_params = []
    if status and status != "all":
        if status == "opened":
            count_query += " AND t.open_count > 0"
        elif status == "clicked":
            count_query += " AND t.click_count > 0"
        else:
            count_query += " AND e.status = ?"
            count_params.append(status)

    if search:
        count_query += " AND (e.to_email LIKE ? OR e.subject LIKE ?)"
        s = f"%{search}%"
        count_params.extend([s, s])

    total_count = conn.execute(count_query, count_params).fetchone()["c"]
    conn.close()
    return {"items": [dict(r) for r in rows], "total": total_count}


def get_sent_email_detail(email_id: int):
    """Fetches complete details and body of a single sent email."""
    conn = get_db()
    row = conn.execute("""
        SELECT e.*, l.name as lead_name, l.company as lead_company, l.stage as lead_stage,
               t.open_count, t.opened_at, t.click_count, t.clicked_at, t.last_user_agent, t.last_ip
        FROM emails_sent e
        LEFT JOIN leads l ON e.lead_id = l.id
        LEFT JOIN email_tracking t ON e.id = t.email_id
        WHERE e.id = ?
    """, (email_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_lead_by_unsub_token(token: str):
    """Finds lead associated with an unsubscribe token without exposing email in URL."""
    conn = get_db()
    import os
    salt = os.environ.get("UNSUB_SALT", "flinza_unsub_salt_2026")
    rows = conn.execute("SELECT id, email, name, company, stage FROM leads WHERE unsubscribed = 0").fetchall()
    for r in rows:
        lead_d = dict(r)
        h = hashlib.sha256(f"{lead_d['email']}:{salt}".encode()).hexdigest()[:24]
        if h == token:
            conn.close()
            return lead_d
    conn.close()
    return None


def get_stats():
    conn = get_db()
    today = date.today().isoformat()
    stats = {}
    stats["total_leads"]       = conn.execute("SELECT COUNT(*) as c FROM leads").fetchone()["c"]
    stats["new_leads"]         = conn.execute("SELECT COUNT(*) as c FROM leads WHERE stage='new'").fetchone()["c"]
    stats["total_sent"]        = conn.execute("SELECT COUNT(*) as c FROM emails_sent WHERE status='sent'").fetchone()["c"]
    stats["sent_today"]        = conn.execute(
        "SELECT COUNT(*) as c FROM emails_sent WHERE status='sent' AND DATE(sent_at)=?", (today,)
    ).fetchone()["c"]
    stats["queued"]            = conn.execute("SELECT COUNT(*) as c FROM emails_sent WHERE status='queued'").fetchone()["c"]
    stats["failed"]            = conn.execute("SELECT COUNT(*) as c FROM emails_sent WHERE status='failed'").fetchone()["c"]
    stats["total_replies"]     = conn.execute("SELECT COUNT(*) as c FROM replies").fetchone()["c"]
    stats["unhandled_replies"] = conn.execute("SELECT COUNT(*) as c FROM replies WHERE handled=0").fetchone()["c"]
    stats["replied_leads"]     = conn.execute("SELECT COUNT(*) as c FROM leads WHERE stage='replied'").fetchone()["c"]
    stats["accounts"]          = conn.execute("SELECT COUNT(*) as c FROM gmail_accounts WHERE active=1").fetchone()["c"]
    stats["aliases"]           = conn.execute("SELECT COUNT(*) as c FROM smtp_aliases WHERE is_active=1").fetchone()["c"]
    stats["remaining_today"]   = total_remaining_today()
    stats["blacklisted"]       = conn.execute("SELECT COUNT(*) as c FROM leads WHERE blacklisted=1").fetchone()["c"]
    stats["unsubscribed"]      = conn.execute("SELECT COUNT(*) as c FROM leads WHERE unsubscribed=1").fetchone()["c"]
    conn.close()
    return stats


# ═══════════════════════════════════════════════════════════════
#                         REPLIES
# ═══════════════════════════════════════════════════════════════

def log_reply(lead_id, from_email, subject, body, ai_draft_subject=None, ai_draft_body=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO replies (lead_id, from_email, subject, body, ai_draft_subject, ai_draft_body)
           VALUES (?,?,?,?,?,?)""",
        (lead_id, from_email, subject, body, ai_draft_subject, ai_draft_body)
    )
    conn.commit()
    reply_id = cur.lastrowid
    conn.close()
    return reply_id


def get_unhandled_replies():
    conn = get_db()
    rows = conn.execute("""
        SELECT r.*, l.name, l.handle, l.email as lead_email, l.followers, l.tier
        FROM replies r
        LEFT JOIN leads l ON r.lead_id = l.id
        WHERE r.handled=0
        ORDER BY r.received_at DESC
    """).fetchall()
    conn.close()
    return rows


def get_reply(reply_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM replies WHERE id=?", (reply_id,)).fetchone()
    conn.close()
    return row


def mark_reply_handled(reply_id: int, action: str = "sent"):
    conn = get_db()
    conn.execute("UPDATE replies SET handled=1, action_taken=? WHERE id=?", (action, reply_id))
    conn.commit()
    conn.close()


def update_reply_draft(reply_id: int, subject: str, body: str):
    conn = get_db()
    conn.execute(
        "UPDATE replies SET ai_draft_subject=?, ai_draft_body=? WHERE id=?",
        (subject, body, reply_id)
    )
    conn.commit()
    conn.close()


def reply_already_logged(lead_id: int, subject: str, body: str) -> bool:
    msg_hash = hashlib.md5(f"{subject}|{body[:500]}".encode("utf-8", errors="replace")).hexdigest()
    conn = get_db()
    rows = conn.execute(
        "SELECT subject, body FROM replies WHERE lead_id=?", (lead_id,)
    ).fetchall()
    conn.close()
    for r in rows:
        h = hashlib.md5(
            f"{r['subject'] or ''}|{(r['body'] or '')[:500]}".encode("utf-8", errors="replace")
        ).hexdigest()
        if h == msg_hash:
            return True
    return False


def log_inbound_webhook_reply(from_email: str, to_email: str, subject: str, body: str, raw_headers: dict = None):
    """
    Called when Cloudflare Inbound Email Routing Worker posts a received email.
    Matches from_email to existing lead in database.
    Updates lead stage to 'replied', cancels pending followups, and inserts reply.
    """
    clean_from = from_email.lower().strip()
    conn = get_db()

    # 1. Match lead by email
    lead = conn.execute("SELECT * FROM leads WHERE LOWER(email) = ?", (clean_from,)).fetchone()
    if not lead:
        name_part = clean_from.split("@")[0].replace(".", " ").title()
        cur = conn.execute(
            "INSERT INTO leads (name, email, stage, source) VALUES (?, ?, 'replied', 'inbound_cloudflare')",
            (name_part, clean_from)
        )
        lead_id = cur.lastrowid
        lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    else:
        lead_id = lead["id"]
        conn.execute("UPDATE leads SET stage='replied', last_contact=? WHERE id=?", (datetime.now().isoformat(), lead_id))
        conn.execute("UPDATE followups_scheduled SET status='cancelled' WHERE lead_id=? AND status='pending'", (lead_id,))

    # 2. Check duplicate reply
    if reply_already_logged(lead_id, subject, body):
        lead_dict = dict(lead)
        conn.close()
        return None, lead_dict

    # 3. Log reply
    cur = conn.execute(
        """INSERT INTO replies (lead_id, from_email, subject, body, action_taken)
           VALUES (?, ?, ?, ?, ?)""",
        (lead_id, clean_from, subject, body, f"inbound_to_{to_email}")
    )
    reply_id = cur.lastrowid
    conn.commit()
    lead_dict = dict(lead)
    conn.close()
    return reply_id, lead_dict


# ═══════════════════════════════════════════════════════════════
#                     CONVERSATION HISTORY
# ═══════════════════════════════════════════════════════════════

def add_conversation_message(lead_id: int, role: str, content: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO conversation_history (lead_id, role, content) VALUES (?,?,?)",
        (lead_id, role, content)
    )
    conn.commit()
    conn.close()


def get_conversation(lead_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM conversation_history WHERE lead_id=? ORDER BY timestamp",
        (lead_id,)
    ).fetchall()
    conn.close()
    return rows


# ═══════════════════════════════════════════════════════════════
#                         FOLLOWUPS
# ═══════════════════════════════════════════════════════════════

def schedule_followup(lead_id: int, days_from_now: int, followup_number: int):
    conn = get_db()
    scheduled = (datetime.now() + timedelta(days=days_from_now)).isoformat()
    conn.execute(
        "INSERT INTO followups_scheduled (lead_id, scheduled_for, followup_number) VALUES (?,?,?)",
        (lead_id, scheduled, followup_number)
    )
    conn.commit()
    conn.close()


def get_due_followups():
    conn = get_db()
    now = datetime.now().isoformat()
    rows = conn.execute("""
        SELECT f.*, l.email, l.name, l.handle, l.tier, l.followers, l.bio, l.niche
        FROM followups_scheduled f
        JOIN leads l ON f.lead_id = l.id
        WHERE f.status='pending' AND f.scheduled_for <= ?
          AND l.stage NOT IN ('replied','negotiating','closed_won','closed_lost','blacklisted','unsubscribed')
          AND l.blacklisted=0 AND l.unsubscribed=0
    """, (now,)).fetchall()
    conn.close()
    return rows


def cancel_followups(lead_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE followups_scheduled SET status='cancelled' WHERE lead_id=? AND status='pending'",
        (lead_id,)
    )
    conn.commit()
    conn.close()


def mark_followup_sent(followup_id: int):
    conn = get_db()
    conn.execute("UPDATE followups_scheduled SET status='sent' WHERE id=?", (followup_id,))
    conn.commit()
    conn.close()


def schedule_first_followup(lead_id: int):
    days_list = json.loads(get_setting("followup_days", "[3, 2]"))
    days = days_list[0] if days_list else 3
    schedule_followup(lead_id, days, 1)


def get_scheduled_followups_count():
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM followups_scheduled WHERE status='pending'"
    ).fetchone()
    conn.close()
    return row["c"] if row else 0


# ═══════════════════════════════════════════════════════════════
#                        TEMPLATES
# ═══════════════════════════════════════════════════════════════

def save_template(name: str, type_: str, subject: str, body: str):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO templates (name, type, subject, body) VALUES (?,?,?,?)",
            (name, type_, subject, body)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_templates(type_=None):
    conn = get_db()
    if type_:
        rows = conn.execute(
            "SELECT * FROM templates WHERE type=? ORDER BY use_count DESC, name", (type_,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM templates ORDER BY type, use_count DESC"
        ).fetchall()
    conn.close()
    return rows


def get_template(name: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM templates WHERE name=?", (name,)).fetchone()
    conn.close()
    return row


def delete_template(name: str):
    conn = get_db()
    conn.execute("DELETE FROM templates WHERE name=?", (name,))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#                       ACTIVITY LOG
# ═══════════════════════════════════════════════════════════════

def log_activity(action: str, details: str = ""):
    conn = get_db()
    conn.execute("INSERT INTO activity_log (action, details) VALUES (?,?)", (action, str(details)))
    conn.commit()
    conn.close()


def get_recent_activity(limit: int = 20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


# ═══════════════════════════════════════════════════════════════
#               REPLY CHECK TIMESTAMP
# ═══════════════════════════════════════════════════════════════

def record_reply_check():
    set_setting("last_reply_check", datetime.now().isoformat())


def get_last_reply_check():
    return get_setting("last_reply_check", "")


# ═══════════════════════════════════════════════════════════════
#             ENTERPRISE UTILITIES: UNSUBSCRIBE & WARMUP
# ═══════════════════════════════════════════════════════════════

def handle_unsubscribe(email: str, reason: str = "replied_unsubscribe") -> bool:
    """
    Auto-compliance:
    1. Flags lead as unsubscribed
    2. Cancels all scheduled followups
    3. Adds email to global blacklist
    4. Logs activity
    """
    if not email:
        return False
    email = email.lower().strip()
    conn = get_db()
    lead = conn.execute("SELECT id FROM leads WHERE email=?", (email,)).fetchone()
    if lead:
        conn.execute(
            "UPDATE leads SET unsubscribed=1, stage='unsubscribed', notes=COALESCE(notes||' | ','')||? WHERE id=?",
            (f"Unsubscribed: {reason}", lead["id"])
        )
        conn.execute(
            "UPDATE followups_scheduled SET status='cancelled' WHERE lead_id=? AND status='pending'",
            (lead["id"],)
        )
    conn.commit()
    conn.close()

    add_to_blacklist(email=email, reason=reason)
    log_activity("unsubscribed", f"{email} ({reason})")
    return True


def get_warmup_status():
    """Returns status of mailbox and alias warmups."""
    conn = get_db()
    accounts = conn.execute("SELECT email, warmup_mode, warmup_day, daily_limit FROM gmail_accounts").fetchall()
    aliases = conn.execute("SELECT alias, warmup_day, daily_limit FROM smtp_aliases").fetchall()
    conn.close()
    return {
        "accounts": [dict(a) for a in accounts],
        "aliases": [dict(al) for al in aliases],
    }


def advance_all_warmups() -> list:
    """
    Advances warmup day for all active accounts and aliases.
    Increases daily sending limit according to safe warmup curve.
    """
    import email_toolkit
    conn = get_db()
    results = []

    # Gmail accounts in warmup mode
    accs = conn.execute("SELECT id, email, warmup_day, daily_limit FROM gmail_accounts WHERE warmup_mode=1").fetchall()
    for a in accs:
        new_day = (a["warmup_day"] or 1) + 1
        new_limit = email_toolkit.get_warmup_limit_for_day(new_day, target_limit=50)
        conn.execute("UPDATE gmail_accounts SET warmup_day=?, daily_limit=? WHERE id=?", (new_day, new_limit, a["id"]))
        results.append(f"Account {a['email']}: Day {new_day} (limit: {new_limit}/day)")

    # Aliases
    aliases = conn.execute("SELECT id, alias, warmup_day, daily_limit FROM smtp_aliases WHERE is_active=1").fetchall()
    for al in aliases:
        new_day = (al["warmup_day"] or 1) + 1
        new_limit = email_toolkit.get_warmup_limit_for_day(new_day, target_limit=30)
        conn.execute("UPDATE smtp_aliases SET warmup_day=?, daily_limit=? WHERE id=?", (new_day, new_limit, al["id"]))
        results.append(f"Alias {al['alias']}: Day {new_day} (limit: {new_limit}/day)")

    conn.commit()
    conn.close()
    return results


def export_leads_csv(stage=None) -> str:
    """Exports leads to a formatted CSV string."""
    import csv
    import io
    leads = get_leads(stage=stage, limit=None)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Email", "Handle", "Stage", "Followers", "Tier", "Niche", "Company", "Added_At", "Last_Contact"])
    for l in leads:
        writer.writerow([
            l["id"], l["name"] or "", l["email"], l["handle"] or "", l["stage"],
            l["followers"] or "", l["tier"] or "", l["niche"] or "", l["company"] or "",
            l["added_at"] or "", l["last_contact"] or ""
        ])
    return output.getvalue()


def export_sent_csv(limit=1000) -> str:
    """Exports outreach sent log to a formatted CSV string."""
    import csv
    import io
    conn = get_db()
    rows = conn.execute("""
        SELECT e.id, e.to_email, e.from_account, e.subject, e.message_type,
               e.status, e.sent_at, e.error_msg, l.name, l.handle
        FROM emails_sent e
        LEFT JOIN leads l ON e.lead_id = l.id
        ORDER BY e.queued_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "To_Email", "Lead_Name", "Lead_Handle", "From_Account", "Subject", "Type", "Status", "Sent_At", "Error"])
    for r in rows:
        writer.writerow([
            r["id"], r["to_email"], r["name"] or "", r["handle"] or "",
            r["from_account"] or "", r["subject"], r["message_type"],
            r["status"], r["sent_at"] or "", r["error_msg"] or ""
        ])
    return output.getvalue()


# ═══════════════════════════════════════════════════════════════
#             GOOGLE OAUTH & TOKEN MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def save_oauth_token(email: str, access_token: str, refresh_token: str = None,
                     expiry: str = None, client_id: str = None, client_secret: str = None,
                     scopes: str = None, provider: str = "google"):
    conn = get_db()
    conn.execute("""
        INSERT INTO oauth_tokens (account_email, access_token, refresh_token, token_expiry, client_id, client_secret, scopes, provider, updated_at)
        VALUES (?, ?, COALESCE(?, (SELECT refresh_token FROM oauth_tokens WHERE account_email=?)), ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(account_email) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=COALESCE(excluded.refresh_token, oauth_tokens.refresh_token),
            token_expiry=excluded.token_expiry,
            client_id=COALESCE(excluded.client_id, oauth_tokens.client_id),
            client_secret=COALESCE(excluded.client_secret, oauth_tokens.client_secret),
            scopes=COALESCE(excluded.scopes, oauth_tokens.scopes),
            updated_at=datetime('now')
    """, (email.lower(), access_token, refresh_token, email.lower(), expiry, client_id, client_secret, scopes, provider))
    conn.commit()
    conn.close()


def get_oauth_token(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM oauth_tokens WHERE account_email=?", (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_oauth_token(email: str):
    conn = get_db()
    conn.execute("DELETE FROM oauth_tokens WHERE account_email=?", (email.lower(),))
    conn.commit()
    conn.close()


def get_all_oauth_accounts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM oauth_tokens ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
#             CUSTOM DYNAMIC API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

def add_custom_endpoint(name: str, base_url: str, model_name: str,
                        api_key: str = None, provider_type: str = "openai_compatible",
                        temperature: float = 0.85, max_tokens: int = 2048,
                        headers_dict: dict = None) -> int:
    conn = get_db()
    headers_json = json.dumps(headers_dict or {})
    cur = conn.execute("""
        INSERT INTO custom_api_endpoints (name, provider_type, base_url, api_key, model_name, temperature, max_tokens, custom_headers_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, provider_type, base_url.rstrip("/"), api_key or "", model_name, temperature, max_tokens, headers_json))
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_custom_endpoints(active_only: bool = False):
    conn = get_db()
    q = "SELECT * FROM custom_api_endpoints"
    if active_only:
        q += " WHERE is_active=1"
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_custom_endpoint(endpoint_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM custom_api_endpoints WHERE id=?", (endpoint_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_custom_endpoint(endpoint_id: int):
    conn = get_db()
    conn.execute("DELETE FROM custom_api_endpoints WHERE id=?", (endpoint_id,))
    conn.commit()
    conn.close()


def toggle_custom_endpoint(endpoint_id: int):
    conn = get_db()
    row = conn.execute("SELECT is_active FROM custom_api_endpoints WHERE id=?", (endpoint_id,)).fetchone()
    if not row:
        conn.close()
        return False
    new_val = 0 if row["is_active"] else 1
    conn.execute("UPDATE custom_api_endpoints SET is_active=? WHERE id=?", (new_val, endpoint_id))
    conn.commit()
    conn.close()
    return bool(new_val)


# ═══════════════════════════════════════════════════════════════
#             EMAIL TRACKING (OPENS & CLICKS)
# ═══════════════════════════════════════════════════════════════

def create_tracking_token(email_id: int) -> str:
    import secrets
    token = secrets.token_urlsafe(18)
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO email_tracking (email_id, tracking_token)
        VALUES (?, ?)
    """, (email_id, token))
    conn.commit()
    conn.close()
    return token


def record_email_open(tracking_token: str, user_agent: str = None, ip: str = None) -> dict:
    conn = get_db()
    row = conn.execute("""
        SELECT t.*, e.to_email, e.subject, e.lead_id, l.name, l.company
        FROM email_tracking t
        JOIN emails_sent e ON t.email_id = e.id
        LEFT JOIN leads l ON e.lead_id = l.id
        WHERE t.tracking_token=?
    """, (tracking_token,)).fetchone()

    if not row:
        conn.close()
        return None

    now = datetime.now().isoformat()
    opened_at = row["opened_at"] or now
    new_count = (row["open_count"] or 0) + 1

    conn.execute("""
        UPDATE email_tracking
        SET opened_at=?, open_count=?, last_user_agent=?, last_ip=?
        WHERE tracking_token=?
    """, (opened_at, new_count, user_agent, ip, tracking_token))

    if row["lead_id"]:
        conn.execute("""
            UPDATE leads
            SET stage='opened'
            WHERE id=? AND stage IN ('sent', 'contacted', 'queued')
        """, (row["lead_id"],))

    conn.commit()
    conn.close()

    result = dict(row)
    result["open_count"] = new_count
    result["opened_at"] = opened_at
    return result


def record_email_click(tracking_token: str, user_agent: str = None, ip: str = None) -> dict:
    conn = get_db()
    row = conn.execute("""
        SELECT t.*, e.to_email, e.subject, e.lead_id, l.name, l.company
        FROM email_tracking t
        JOIN emails_sent e ON t.email_id = e.id
        LEFT JOIN leads l ON e.lead_id = l.id
        WHERE t.tracking_token=?
    """, (tracking_token,)).fetchone()

    if not row:
        conn.close()
        return None

    now = datetime.now().isoformat()
    clicked_at = row["clicked_at"] or now
    new_count = (row["click_count"] or 0) + 1

    conn.execute("""
        UPDATE email_tracking
        SET clicked_at=?, click_count=?, last_user_agent=?, last_ip=?
        WHERE tracking_token=?
    """, (clicked_at, new_count, user_agent, ip, tracking_token))

    if row["lead_id"]:
        conn.execute("""
            UPDATE leads
            SET stage='clicked'
            WHERE id=? AND stage IN ('sent', 'contacted', 'opened')
        """, (row["lead_id"],))

    conn.commit()
    conn.close()

    result = dict(row)
    result["click_count"] = new_count
    result["clicked_at"] = clicked_at
    return result


def get_tracking_stats() -> dict:
    conn = get_db()
    total_sent = conn.execute("SELECT COUNT(*) as c FROM emails_sent WHERE status='sent'").fetchone()["c"]
    total_tracked = conn.execute("SELECT COUNT(*) as c FROM email_tracking").fetchone()["c"]
    total_opened = conn.execute("SELECT COUNT(*) as c FROM email_tracking WHERE open_count > 0").fetchone()["c"]
    total_clicked = conn.execute("SELECT COUNT(*) as c FROM email_tracking WHERE click_count > 0").fetchone()["c"]
    conn.close()

    open_rate = round((total_opened / total_sent * 100), 1) if total_sent > 0 else 0.0
    click_rate = round((total_clicked / total_sent * 100), 1) if total_sent > 0 else 0.0

    return {
        "total_sent": total_sent,
        "total_tracked": total_tracked,
        "total_opened": total_opened,
        "total_clicked": total_clicked,
        "open_rate": open_rate,
        "click_rate": click_rate,
    }


# ═══════════════════════════════════════════════════════════════
#             CAMPAIGN SEQUENCES (MULTI-STEP)
# ═══════════════════════════════════════════════════════════════

def save_sequence_step(campaign_id: int, step_number: int, delay_days: int,
                       subject_a: str, body_a: str,
                       subject_b: str = None, body_b: str = None,
                       condition_type: str = "always") -> int:
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO campaign_sequences (campaign_id, step_number, delay_days, condition_type, subject_a, body_a, subject_b, body_b)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (campaign_id, step_number, delay_days, condition_type, subject_a, body_a, subject_b, body_b))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def get_campaign_sequences(campaign_id: int):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM campaign_sequences
        WHERE campaign_id=? AND is_active=1
        ORDER BY step_number ASC
    """, (campaign_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_sequence_step(sequence_id: int):
    conn = get_db()
    conn.execute("DELETE FROM campaign_sequences WHERE id=?", (sequence_id,))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#             DNS AUDIT CACHE (CLOUDFLARE & DOMAINS)
# ═══════════════════════════════════════════════════════════════

def save_dns_audit(domain: str, spf_record: str, spf_status: str,
                   dkim_record: str, dkim_status: str,
                   dmarc_record: str, dmarc_status: str,
                   mx_status: str, score: int):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO dns_audit_cache (domain, spf_record, spf_status, dkim_record, dkim_status, dmarc_record, dmarc_status, mx_status, overall_score, last_audited)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (domain.lower(), spf_record, spf_status, dkim_record, dkim_status, dmarc_record, dmarc_status, mx_status, score))
    conn.commit()
    conn.close()


def get_dns_audit(domain: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM dns_audit_cache WHERE domain=?", (domain.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


# ═══════════════════════════════════════════════════════════════
#             STUDIO USERS & AUTH
# ═══════════════════════════════════════════════════════════════

def create_user(username: str, email: str = None, password_hash: str = None,
                google_id: str = None, role: str = "admin") -> int:
    conn = get_db()
    cur = conn.execute("""
        INSERT OR IGNORE INTO users (username, email, password_hash, google_id, role)
        VALUES (?, ?, ?, ?, ?)
    """, (username, email.lower() if email else None, password_hash, google_id, role))
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


def get_user_by_username(username: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_google_id(google_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


