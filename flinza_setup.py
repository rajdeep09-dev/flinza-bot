#!/usr/bin/env python3
"""
flinza_setup.py — One-shot setup script for Flinza outreach bot.

Actions performed:
  1. Initialise / migrate the database (adds crm_priority, country, revenue, etc.)
  2. Wipe old dummy leads, Gmail-only accounts, old mailboxes
  3. Load all 29 Spacemail mailboxes from spacemail_accounts.json
  4. Import verified brand leads from leads_final_brands.csv + FINAL_ENRICHED_WITH_EXECUTIVES.csv
  5. Send a test email via the first active Spacemail account
"""

import os
import sys
import csv
import json
import smtplib
import sqlite3
import imaplib

from datetime import date, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid, formatdate
from pathlib import Path

# ── Load .env ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

DB_PATH = os.environ.get("DB_PATH", "flinza.db")
LEADS_CSV   = "/data/data/com.termux/files/home/storage/dcim/dashboard/leads_final_brands.csv"
ENRICHED_CSV = "/data/data/com.termux/files/home/FINAL_ENRICHED_WITH_EXECUTIVES.csv"
SPACEMAIL_JSON = BASE_DIR / "spacemail_accounts.json"
TEST_EMAIL_TO = "f12x.studio@gmail.com"


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── 1. Migrate DB ─────────────────────────────────────────────────────────────
def migrate_db():
    print("⚙️  Migrating database schema…")
    conn = get_db()

    # Core tables (idempotent)
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
            custom_hook TEXT,
            linkedin TEXT,
            ai_subject TEXT,
            ai_draft TEXT,
            deliverability_status TEXT DEFAULT 'unverified',
            deliverability_score INTEGER DEFAULT 100,
            last_audit_details TEXT,
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
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP,
            provider TEXT DEFAULT 'smtp',
            smtp_host TEXT DEFAULT 'smtp.gmail.com',
            smtp_port INTEGER DEFAULT 587,
            smtp_user TEXT,
            smtp_pass TEXT,
            label TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS emails_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            from_account TEXT,
            to_email TEXT,
            subject TEXT,
            body TEXT,
            message_type TEXT DEFAULT 'opener',
            status TEXT DEFAULT 'queued',
            queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            error_msg TEXT,
            message_id TEXT
        );

        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            from_email TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subject TEXT,
            body TEXT,
            handled INTEGER DEFAULT 0,
            action_taken TEXT
        );
    """)
    conn.commit()

    # ADD new enrichment + CRM priority columns (safe ALTER TABLE)
    new_columns = [
        ("crm_priority", "INTEGER DEFAULT 0"),           # 1=Tier1, 2=Tier2, 3=Tier3, 0=unset
        ("country", "TEXT"),
        ("revenue", "TEXT"),
        ("company_size", "TEXT"),
        ("icp_fit", "TEXT"),
        ("instagram_handle", "TEXT"),
        ("instagram_followers", "INTEGER"),
        ("email_confidence", "TEXT"),
        ("email_type", "TEXT"),
        ("contact_title", "TEXT"),
        ("sub_niche", "TEXT"),
        ("brand_confidence", "TEXT"),
        ("instagram_url", "TEXT"),
        ("mx_status", "TEXT"),
        ("dmarc_status", "TEXT"),
        ("spf_status", "TEXT"),
        ("personalized_icebreaker", "TEXT"),
        ("exec_name", "TEXT"),
        ("exec_title", "TEXT"),
        ("exec_email", "TEXT"),
    ]

    existing = {row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for col, col_type in new_columns:
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {col_type}")
                print(f"   + Added column: leads.{col}")
            except Exception as e:
                print(f"   ! Could not add {col}: {e}")

    # gmail_accounts — add missing columns
    ga_columns = [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("provider", "TEXT DEFAULT 'smtp'"),
        ("smtp_host", "TEXT DEFAULT 'smtp.gmail.com'"),
        ("smtp_port", "INTEGER DEFAULT 587"),
        ("smtp_user", "TEXT"),
        ("smtp_pass", "TEXT"),
        ("label", "TEXT"),
    ]
    existing_ga = {row[1] for row in conn.execute("PRAGMA table_info(gmail_accounts)").fetchall()}
    for col, col_type in ga_columns:
        if col not in existing_ga and "PRIMARY" not in col_type:
            try:
                conn.execute(f"ALTER TABLE gmail_accounts ADD COLUMN {col} {col_type}")
                print(f"   + Added column: gmail_accounts.{col}")
            except Exception:
                pass

    conn.commit()
    conn.close()
    print("   ✅ Schema migration complete.\n")


# ── 2. Clear old data ─────────────────────────────────────────────────────────
def clear_old_data():
    print("🗑️  Clearing old leads & Gmail-only accounts…")
    conn = get_db()
    # Remove old leads (keep none — fresh import)
    n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    conn.execute("DELETE FROM leads")
    # Remove Gmail accounts (not spacemail)
    conn.execute(
        "DELETE FROM gmail_accounts WHERE provider != 'spacemail' OR provider IS NULL"
    )
    conn.commit()
    conn.close()
    print(f"   Deleted {n} old leads. Accounts cleaned.\n")


# ── 3. Load 29 Spacemail accounts ─────────────────────────────────────────────
def load_spacemail_accounts():
    print("📬 Loading Spacemail fleet…")
    with open(SPACEMAIL_JSON) as f:
        data = json.load(f)

    accounts = data.get("accounts", [])
    smtp_host = data.get("smtp_host", "mail.spacemail.com")
    smtp_port = data.get("smtp_port", 465)

    conn = get_db()
    created = updated = 0
    today = date.today().isoformat()

    for acc in accounts:
        email    = acc["email"].strip()
        password = acc["password"].strip()
        existing = conn.execute(
            "SELECT email FROM gmail_accounts WHERE email=? COLLATE NOCASE", (email,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE gmail_accounts
                SET app_password=?, provider='spacemail', smtp_host=?, smtp_port=?,
                    smtp_user=?, smtp_pass=?, active=1
                WHERE email=? COLLATE NOCASE
            """, (password, smtp_host, smtp_port, email, password, email))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO gmail_accounts
                    (email, app_password, daily_limit, last_reset_date, provider,
                     smtp_host, smtp_port, smtp_user, smtp_pass, label)
                VALUES (?,?,50,?,?,?,?,?,?,?)
            """, (email, password, today, "spacemail", smtp_host, smtp_port, email, password, "Flinza Fleet"))
            created += 1

    conn.commit()
    conn.close()
    print(f"   ✅ {created} created, {updated} updated. Total: {len(accounts)} mailboxes.\n")
    return accounts


# ── 4a. Import leads_final_brands.csv ─────────────────────────────────────────
def import_brands_csv():
    print(f"📋 Importing brand leads from leads_final_brands.csv…")
    if not os.path.exists(LEADS_CSV):
        print("   ⚠️  File not found, skipping.\n")
        return 0

    conn = get_db()
    count = 0

    with open(LEADS_CSV, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize keys
            r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}

            email = r.get("best_email", "") or r.get("email", "")
            if not email or "@" not in email:
                continue

            name   = r.get("contact_name_sheet", "") or r.get("contact_name", "") or "Founder"
            company = r.get("brand_name", "") or r.get("company", "")
            niche   = r.get("niche", "DTC Brand")
            sub_niche = r.get("sub_niche", "")
            website = r.get("final_domain", "") or r.get("website", "")
            if website and not website.startswith("http"):
                website = "https://" + website
            country = r.get("country", "")
            instagram_handle = r.get("instagram_handle", "")
            instagram_url    = r.get("instagram_url", "")
            followers_raw    = r.get("followers", "0")
            try:
                followers = int(str(followers_raw).replace(",", "").split(".")[0])
            except Exception:
                followers = 0

            email_type       = r.get("email_type", "")
            email_confidence = r.get("email_confidence", "")
            contact_title    = r.get("contact_title_sheet", "") or r.get("contact_title", "")
            brand_confidence = r.get("brand_confidence", "")

            existing = conn.execute("SELECT id FROM leads WHERE email=?", (email.lower(),)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE leads SET
                        name=COALESCE(NULLIF(name,''),?), company=COALESCE(NULLIF(company,''),?),
                        niche=?, sub_niche=?, website=?, country=?, instagram_handle=?,
                        instagram_url=?, instagram_followers=?, email_type=?,
                        email_confidence=?, contact_title=?, brand_confidence=?
                    WHERE email=?
                """, (name, company, niche, sub_niche, website, country,
                      instagram_handle, instagram_url, followers, email_type,
                      email_confidence, contact_title, brand_confidence, email.lower()))
            else:
                conn.execute("""
                    INSERT INTO leads
                        (name, email, company, niche, sub_niche, website, country,
                         instagram_handle, instagram_url, instagram_followers,
                         email_type, email_confidence, contact_title, brand_confidence,
                         stage, source, added_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new','leads_final_brands',?)
                """, (name, email.lower(), company, niche, sub_niche, website, country,
                      instagram_handle, instagram_url, followers, email_type,
                      email_confidence, contact_title, brand_confidence,
                      datetime.utcnow().isoformat()))
            count += 1

    conn.commit()
    conn.close()
    print(f"   ✅ {count} brand leads imported.\n")
    return count


# ── 4b. Import FINAL_ENRICHED_WITH_EXECUTIVES.csv ─────────────────────────────
def import_enriched_csv():
    print(f"📋 Importing enriched leads from FINAL_ENRICHED_WITH_EXECUTIVES.csv…")
    if not os.path.exists(ENRICHED_CSV):
        print("   ⚠️  File not found, skipping.\n")
        return 0

    conn = get_db()
    count = 0

    with open(ENRICHED_CSV, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}

            # Primary email
            email = r.get("email", "") or r.get("exec_email", "")
            if not email or "@" not in email:
                continue

            name    = r.get("first_name", "") or r.get("exec_first", "")
            company = r.get("store_name", "") or r.get("company", "")
            niche   = r.get("niche", "DTC Brand")
            website = r.get("website", "") or r.get("domain", "")
            if website and not website.startswith("http"):
                website = "https://" + website
            linkedin = ""
            instagram_handle = r.get("instagram", "")
            instagram_url    = r.get("instagram_url", "")
            mx_status        = r.get("mx_status", "")
            dmarc_status     = r.get("dmarc_status", "")
            spf_status       = r.get("spf_status", "")
            deliverability_score_raw = r.get("deliverability_score", "100")
            try:
                del_score = int(str(deliverability_score_raw).replace("%", "").split()[0])
            except Exception:
                del_score = 100
            del_status = "verified" if del_score >= 90 else "unverified"
            personalized_icebreaker = r.get("personalized_icebreaker", "") or r.get("custom_hook", "")
            exec_name   = r.get("exec_name", "")
            exec_title  = r.get("exec_title", "") or r.get("title", "")
            exec_email  = r.get("exec_email", "")

            existing = conn.execute("SELECT id FROM leads WHERE email=?", (email.lower(),)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE leads SET
                        name=COALESCE(NULLIF(name,''),?), company=COALESCE(NULLIF(company,''),?),
                        niche=?, website=?, instagram_handle=?,
                        mx_status=?, dmarc_status=?, spf_status=?,
                        deliverability_status=?, deliverability_score=?,
                        personalized_icebreaker=?, exec_name=?, exec_title=?, exec_email=?,
                        custom_hook=COALESCE(NULLIF(custom_hook,''),?)
                    WHERE email=?
                """, (name, company, niche, website, instagram_handle,
                      mx_status, dmarc_status, spf_status, del_status, del_score,
                      personalized_icebreaker, exec_name, exec_title, exec_email,
                      personalized_icebreaker, email.lower()))
            else:
                conn.execute("""
                    INSERT INTO leads
                        (name, email, company, niche, website, instagram_handle,
                         mx_status, dmarc_status, spf_status,
                         deliverability_status, deliverability_score,
                         personalized_icebreaker, custom_hook, exec_name, exec_title, exec_email,
                         stage, source, added_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new','enriched_csv',?)
                """, (name, email.lower(), company, niche, website, instagram_handle,
                      mx_status, dmarc_status, spf_status, del_status, del_score,
                      personalized_icebreaker, personalized_icebreaker,
                      exec_name, exec_title, exec_email,
                      datetime.utcnow().isoformat()))
            count += 1

    conn.commit()
    conn.close()
    print(f"   ✅ {count} enriched leads imported.\n")
    return count


# ── 5. Test email send ─────────────────────────────────────────────────────────
def send_test_email(accounts, to_email=TEST_EMAIL_TO):
    print(f"📧 Sending test email to {to_email}…")

    # Use first active account
    account = accounts[0]
    email_addr = account["email"]
    password   = account["password"]

    smtp_host = "mail.spacemail.com"
    smtp_port = 465

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]       = formataddr(("Rajdeep from Flinza", email_addr))
        msg["To"]         = to_email
        msg["Subject"]    = "✅ Flinza Bot — Test Email Sent Successfully"
        msg["Date"]       = formatdate(localtime=True)
        message_id        = make_msgid(domain="flinzamedia.com")
        msg["Message-ID"] = message_id

        body_text = f"""Hey there,

This is a live test email sent via the Flinza outreach bot's SMTP sending logic.

Sending from: {email_addr}
Sent via: Spacemail SMTP (mail.spacemail.com:465)
Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
Message-ID: {message_id}

✅ If you received this, the sending pipeline is working perfectly!

The bot is configured with:
• 29 Spacemail mailboxes across 6 domains
• SpaceMail SMTP/IMAP on mail.spacemail.com
• Daily limit: 50 emails per inbox (1,450 total/day across fleet)

Next steps:
1. Assign leads to priority tiers in the CRM dashboard
2. Set country-wise sending hours
3. Launch your first campaign

— Flinza Bot
"""

        body_html = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #6366f1;">✅ Flinza Bot — Test Email</h2>
  <p>This is a live test email sent via the Flinza outreach bot's SMTP pipeline.</p>
  <table style="width:100%; background:#f9f9f9; padding:15px; border-radius:8px; margin:15px 0;">
    <tr><td><strong>Sending from:</strong></td><td>{email_addr}</td></tr>
    <tr><td><strong>Via:</strong></td><td>Spacemail SMTP (mail.spacemail.com:465)</td></tr>
    <tr><td><strong>Timestamp:</strong></td><td>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
  </table>
  <p style="color: green;"><strong>✅ If you received this, the sending pipeline is working perfectly!</strong></p>
  <hr>
  <p style="color:#666; font-size:13px;">
    Fleet: 29 Spacemail mailboxes · 1,450 emails/day capacity<br>
    — Flinza Bot
  </p>
</div>
"""

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        print(f"   Connecting to {smtp_host}:{smtp_port} as {email_addr}…")
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(email_addr, password)
            server.sendmail(email_addr, [to_email], msg.as_string())

        print(f"   ✅ Test email sent! Message-ID: {message_id}\n")
        return {"success": True, "from": email_addr, "message_id": message_id}

    except Exception as e:
        print(f"   ❌ Failed: {e}\n")
        return {"success": False, "error": str(e), "from": email_addr}


# ── 6. Test IMAP (reply watching) ─────────────────────────────────────────────
def test_imap_receive(accounts):
    print("📥 Testing IMAP reply-watching (inbox access)…")
    account = accounts[0]
    email_addr = account["email"]
    password   = account["password"]

    try:
        with imaplib.IMAP4_SSL("mail.spacemail.com", 993, timeout=15) as mail:
            mail.login(email_addr, password)
            mail.select("INBOX")
            status, data = mail.search(None, "ALL")
            count = len(data[0].split()) if data[0] else 0
            print(f"   ✅ IMAP connected to {email_addr} — {count} messages in inbox\n")
            return {"success": True, "inbox_count": count}
    except Exception as e:
        print(f"   ❌ IMAP error: {e}\n")
        return {"success": False, "error": str(e)}


# ── 7. Summary stats ──────────────────────────────────────────────────────────
def print_summary():
    conn = get_db()
    leads_total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    accounts_total = conn.execute("SELECT COUNT(*) FROM gmail_accounts WHERE active=1").fetchone()[0]
    verified = conn.execute("SELECT COUNT(*) FROM leads WHERE deliverability_status='verified'").fetchone()[0]
    conn.close()

    print("=" * 55)
    print("📊 FLINZA SETUP COMPLETE — SUMMARY")
    print("=" * 55)
    print(f"  • Active mailboxes  : {accounts_total}")
    print(f"  • Total leads       : {leads_total}")
    print(f"  • Verified leads    : {verified}")
    print(f"  • Daily send cap    : {accounts_total * 50:,} emails/day")
    print("=" * 55)
    print("\nNext: Run the web server:  python web_server.py")
    print("Or   start the Telegram bot:  python bot.py\n")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🚀 Flinza Bot Setup — Starting…\n")

    migrate_db()
    clear_old_data()
    accounts = load_spacemail_accounts()
    import_brands_csv()
    import_enriched_csv()
    result = send_test_email(accounts)
    imap_result = test_imap_receive(accounts)
    print_summary()

    if not result["success"]:
        print(f"⚠️  Test email failed: {result.get('error')}")
        sys.exit(1)
