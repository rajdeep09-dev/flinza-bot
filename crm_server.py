#!/usr/bin/env python3
"""
Flinza CRM Dashboard Server
Flask-based CRM with:
  - Advanced lead filters (revenue, company size, niche, country, ICP, status, priority)
  - Bulk actions (delete, status change, priority assignment)
  - 3-tier priority system (Tier 1=Next Send, 2=Secondary, 3=Backup)
  - Country-wise sending hours
  - Enriched lead data display
"""

import os
import sys
import json
import sqlite3
import csv
import io
import smtplib
import imaplib
from pathlib import Path
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid, formatdate
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template_string,
    Response, send_file, session, redirect, url_for
)

# ── Load .env ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

DB_PATH    = os.environ.get("DB_PATH", "flinza.db")
SECRET_KEY = os.environ.get("DASHBOARD_API_KEY", "flinza-secret-2026")
LOGIN_EMAIL = os.environ.get("DASHBOARD_LOGIN_EMAIL", "admin@flinza.com")
LOGIN_PASS  = os.environ.get("DASHBOARD_LOGIN_PASSWORD", "flinza2026")
PORT = int(os.environ.get("PORT", 7880))

app = Flask(__name__)
app.secret_key = SECRET_KEY


# ── DB helpers ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Auth ──────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        require_auth = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"
        if require_auth and not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        email = (data.get("email") or "").strip()
        pwd   = (data.get("password") or "").strip()
        if email == LOGIN_EMAIL and pwd == LOGIN_PASS:
            session["logged_in"] = True
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    return render_template_string(LOGIN_HTML)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")


# ── Leads API ──────────────────────────────────────────────────────────────────

@app.route("/api/leads", methods=["GET"])
@login_required
def list_leads():
    """Advanced filtered leads list."""
    conn = get_db()

    # Query params
    stage         = request.args.get("stage")
    search        = request.args.get("search")
    niche         = request.args.get("niche")
    country       = request.args.get("country")
    crm_priority  = request.args.get("crm_priority")
    icp_fit       = request.args.get("icp_fit")
    company_size  = request.args.get("company_size")
    revenue       = request.args.get("revenue")
    del_status    = request.args.get("deliverability_status")
    sort_by       = request.args.get("sort", "crm_priority_asc")
    limit         = int(request.args.get("limit", 500))

    query  = "SELECT * FROM leads WHERE COALESCE(blacklisted,0)=0 AND COALESCE(unsubscribed,0)=0"
    params = []

    if stage and stage != "all":
        query += " AND stage=?"; params.append(stage)
    if niche and niche != "all":
        query += " AND (niche LIKE ? OR sub_niche LIKE ?)"; params += [f"%{niche}%", f"%{niche}%"]
    if country and country != "all":
        query += " AND country LIKE ?"; params.append(f"%{country}%")
    if crm_priority and crm_priority != "all":
        query += " AND crm_priority=?"; params.append(int(crm_priority))
    if icp_fit and icp_fit != "all":
        query += " AND icp_fit LIKE ?"; params.append(f"%{icp_fit}%")
    if company_size and company_size != "all":
        query += " AND company_size LIKE ?"; params.append(f"%{company_size}%")
    if revenue and revenue != "all":
        query += " AND revenue LIKE ?"; params.append(f"%{revenue}%")
    if del_status and del_status != "all":
        query += " AND deliverability_status=?"; params.append(del_status)
    if search:
        s = f"%{search}%"
        query += " AND (email LIKE ? OR name LIKE ? OR company LIKE ? OR niche LIKE ?)"
        params += [s, s, s, s]

    # Sorting
    sort_map = {
        "crm_priority_asc":  "CASE WHEN crm_priority=0 THEN 9 ELSE crm_priority END ASC, added_at DESC",
        "crm_priority_desc": "crm_priority DESC, added_at DESC",
        "added_desc":        "added_at DESC",
        "added_asc":         "added_at ASC",
        "company_asc":       "company ASC",
        "score_desc":        "score DESC",
        "followers_desc":    "instagram_followers DESC",
    }
    order = sort_map.get(sort_by, "CASE WHEN crm_priority=0 THEN 9 ELSE crm_priority END ASC, added_at DESC")
    query += f" ORDER BY {order} LIMIT {int(limit)}"

    rows = conn.execute(query, params).fetchall()
    leads = [dict(r) for r in rows]
    conn.close()
    return jsonify({"success": True, "count": len(leads), "leads": leads})


@app.route("/api/leads/<int:lead_id>", methods=["GET"])
@login_required
def get_lead(lead_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.route("/api/leads/<int:lead_id>", methods=["PUT", "PATCH"])
@login_required
def update_lead(lead_id):
    body = request.get_json(silent=True) or {}
    allowed = ["name", "email", "company", "niche", "website", "linkedin", "stage",
               "tier", "notes", "custom_hook", "crm_priority", "country", "revenue",
               "company_size", "icp_fit", "sub_niche", "contact_title"]
    sets = []
    vals = []
    for k in allowed:
        if k in body:
            sets.append(f"{k}=?")
            vals.append(body[k])
    if not sets:
        return jsonify({"error": "No fields to update"}), 400
    vals.append(lead_id)
    conn = get_db()
    conn.execute(f"UPDATE leads SET {','.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/leads/<int:lead_id>", methods=["DELETE"])
@login_required
def delete_lead(lead_id):
    conn = get_db()
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "deleted_id": lead_id})


# ── Bulk Actions ──────────────────────────────────────────────────────────────

@app.route("/api/leads/bulk", methods=["POST"])
@login_required
def bulk_action():
    """Bulk operations on selected lead IDs."""
    body = request.get_json(silent=True) or {}
    ids    = body.get("ids", [])
    action = body.get("action", "")

    if not ids or not action:
        return jsonify({"error": "ids and action required"}), 400

    # Safety: ensure all ids are integers
    ids = [int(i) for i in ids]
    placeholders = ",".join("?" * len(ids))
    conn = get_db()

    if action == "delete":
        conn.execute(f"DELETE FROM leads WHERE id IN ({placeholders})", ids)
        conn.commit()
        conn.close()
        return jsonify({"success": True, "affected": len(ids), "action": "delete"})

    elif action == "set_stage":
        stage = body.get("value", "new")
        conn.execute(f"UPDATE leads SET stage=? WHERE id IN ({placeholders})", [stage] + ids)
        conn.commit()
        conn.close()
        return jsonify({"success": True, "affected": len(ids), "action": "set_stage", "value": stage})

    elif action == "set_priority":
        priority = int(body.get("value", 0))
        if priority not in (0, 1, 2, 3):
            conn.close()
            return jsonify({"error": "Priority must be 0, 1, 2, or 3"}), 400
        conn.execute(f"UPDATE leads SET crm_priority=? WHERE id IN ({placeholders})", [priority] + ids)
        conn.commit()
        conn.close()
        return jsonify({"success": True, "affected": len(ids), "action": "set_priority", "value": priority})

    elif action == "set_niche":
        niche = body.get("value", "")
        conn.execute(f"UPDATE leads SET niche=? WHERE id IN ({placeholders})", [niche] + ids)
        conn.commit()
        conn.close()
        return jsonify({"success": True, "affected": len(ids), "action": "set_niche"})

    elif action == "blacklist":
        conn.execute(
            f"UPDATE leads SET blacklisted=1, stage='blacklisted' WHERE id IN ({placeholders})", ids
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "affected": len(ids), "action": "blacklist"})

    elif action == "unsubscribe":
        conn.execute(
            f"UPDATE leads SET unsubscribed=1, stage='unsubscribed' WHERE id IN ({placeholders})", ids
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "affected": len(ids), "action": "unsubscribe"})

    else:
        conn.close()
        return jsonify({"error": f"Unknown action: {action}"}), 400


# ── Filter metadata ────────────────────────────────────────────────────────────

@app.route("/api/leads/filter-options", methods=["GET"])
@login_required
def filter_options():
    """Return distinct values for filter dropdowns."""
    conn = get_db()

    niches   = [r[0] for r in conn.execute(
        "SELECT DISTINCT niche FROM leads WHERE niche IS NOT NULL AND niche!='' ORDER BY niche"
    ).fetchall()]
    countries = [r[0] for r in conn.execute(
        "SELECT DISTINCT country FROM leads WHERE country IS NOT NULL AND country!='' ORDER BY country"
    ).fetchall()]
    stages   = [r[0] for r in conn.execute(
        "SELECT DISTINCT stage FROM leads WHERE stage IS NOT NULL ORDER BY stage"
    ).fetchall()]

    conn.close()
    return jsonify({
        "niches": niches,
        "countries": countries,
        "stages": stages,
        "priorities": [
            {"value": 0, "label": "Unset"},
            {"value": 1, "label": "⭐ Tier 1 — Next Send"},
            {"value": 2, "label": "Tier 2 — Secondary"},
            {"value": 3, "label": "Tier 3 — Backup"},
        ]
    })


# ── Stats ──────────────────────────────────────────────────────────────────────

@app.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    conn = get_db()
    stats = {
        "total_leads":    conn.execute("SELECT COUNT(*) FROM leads WHERE COALESCE(blacklisted,0)=0").fetchone()[0],
        "tier1":          conn.execute("SELECT COUNT(*) FROM leads WHERE crm_priority=1").fetchone()[0],
        "tier2":          conn.execute("SELECT COUNT(*) FROM leads WHERE crm_priority=2").fetchone()[0],
        "tier3":          conn.execute("SELECT COUNT(*) FROM leads WHERE crm_priority=3").fetchone()[0],
        "verified":       conn.execute("SELECT COUNT(*) FROM leads WHERE deliverability_status='verified'").fetchone()[0],
        "new_leads":      conn.execute("SELECT COUNT(*) FROM leads WHERE stage='new'").fetchone()[0],
        "contacted":      conn.execute("SELECT COUNT(*) FROM leads WHERE stage='contacted'").fetchone()[0],
        "replied":        conn.execute("SELECT COUNT(*) FROM leads WHERE stage='replied'").fetchone()[0],
        "active_mailboxes": conn.execute("SELECT COUNT(*) FROM gmail_accounts WHERE active=1").fetchone()[0],
        "daily_capacity": conn.execute("SELECT COALESCE(SUM(daily_limit),0) FROM gmail_accounts WHERE active=1").fetchone()[0],
    }
    conn.close()
    return jsonify({"success": True, "stats": stats})


# ── Templates ─────────────────────────────────────────────────────────────────

@app.route("/api/templates", methods=["GET"])
@login_required
def get_templates():
    conn = get_db()
    rows = conn.execute("SELECT * FROM templates ORDER BY id").fetchall()
    conn.close()
    return jsonify({"success": True, "templates": [dict(r) for r in rows]})


# ── Accounts ──────────────────────────────────────────────────────────────────

def _sender_first_name(email_addr: str) -> str:
    """Extract and capitalize first name from email local part.
    e.g. zoya@flinzamedia.com -> 'Zoya', derek.smith@domain.com -> 'Derek'
    """
    local = email_addr.split("@")[0]
    name = local.split(".")[0].split("_")[0]
    return name.capitalize()


def _reset_sent_today_if_new_day(conn):
    """Reset sent_today counter for all accounts if it's a new calendar day."""
    today = date.today().isoformat()
    conn.execute("""
        UPDATE gmail_accounts
        SET sent_today=0, last_reset_date=?
        WHERE last_reset_date IS NULL OR last_reset_date != ?
    """, (today, today))
    conn.commit()


@app.route("/api/accounts", methods=["GET"])
@login_required
def get_accounts():
    conn = get_db()
    _reset_sent_today_if_new_day(conn)
    rows = conn.execute("SELECT * FROM gmail_accounts ORDER BY email").fetchall()
    accounts = []
    for r in rows:
        d = dict(r)
        d.pop("app_password", None)
        d.pop("smtp_pass", None)
        accounts.append(d)
    conn.close()
    return jsonify({"success": True, "accounts": accounts})


@app.route("/api/accounts/next-sender", methods=["GET"])
@login_required
def next_sender():
    """Returns the first name of the next mailbox that would be used for sending."""
    conn = get_db()
    _reset_sent_today_if_new_day(conn)
    row = conn.execute("""
        SELECT email FROM gmail_accounts
        WHERE active=1
        AND COALESCE(sent_today, 0) < COALESCE(daily_limit, 50)
        ORDER BY COALESCE(last_used, '1970-01-01') ASC
        LIMIT 1
    """).fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "first_name": "Flinza"})
    first_name = _sender_first_name(row["email"])
    return jsonify({"success": True, "first_name": first_name, "email": row["email"]})


def _send_smtp_email(smtp_host: str, smtp_port: int, email_addr: str, password: str, to_email: str, msg_string: str):
    """Robust SMTP dispatcher supporting direct SSL (465) and STARTTLS (587/25)."""
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=25) as server:
            server.login(email_addr, password)
            server.sendmail(email_addr, [to_email], msg_string)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=25) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_addr, password)
            server.sendmail(email_addr, [to_email], msg_string)


@app.route("/api/accounts/test", methods=["POST"])
@login_required
def test_account():
    """Send a test email via a specific account (or auto-pick with failover).
    
    Robustness guarantees:
    - Auto-picks least recently used active account with remaining daily capacity
    - Failover: if the chosen account fails (network/credentials), immediately tries next available account
    - Handles both SSL (465) and STARTTLS (587)
    - Replaces hardcoded names with the mailbox first name
    - Accurately tracks last_used timestamp and sent_today counter
    """
    body = request.get_json(silent=True) or {}
    to_email = body.get("to_email", "f12x.studio@gmail.com")
    account_email = body.get("email")

    conn = get_db()
    _reset_sent_today_if_new_day(conn)

    if account_email:
        rows = conn.execute(
            "SELECT * FROM gmail_accounts WHERE email=? AND active=1",
            (account_email,)
        ).fetchall()
    else:
        # Get top 3 eligible accounts for failover
        rows = conn.execute("""
            SELECT * FROM gmail_accounts
            WHERE active=1
            AND COALESCE(sent_today, 0) < COALESCE(daily_limit, 50)
            ORDER BY COALESCE(last_used, '1970-01-01') ASC
            LIMIT 3
        """).fetchall()

    conn.close()

    if not rows:
        return jsonify({"success": False, "error": "No active mailbox with capacity found"}), 404

    last_error = None
    for row in rows:
        acc = dict(row)
        email_addr = acc["email"]
        password   = acc.get("smtp_pass") or acc.get("app_password")
        smtp_host  = acc.get("smtp_host", "mail.spacemail.com")
        smtp_port  = int(acc.get("smtp_port", 465))

        sender_first = _sender_first_name(email_addr)
        display_name = f"{sender_first} from Flinza"

        try:
            custom_subject = body.get("subject")
            custom_body    = body.get("body")

            if custom_body:
                import re as _re
                custom_body = _re.sub(r'\bRajdeep\b', sender_first, custom_body)

            msg = MIMEMultipart("alternative")
            msg["From"]       = formataddr((display_name, email_addr))
            msg["To"]         = to_email
            msg["Subject"]    = custom_subject or f"✅ Test Email from {email_addr}"
            msg["Date"]       = formatdate(localtime=True)
            message_id        = make_msgid(domain=email_addr.split("@")[-1])
            msg["Message-ID"] = message_id

            body_text = custom_body or (
                f"This is a live test email sent from the Flinza outreach system.\n\n"
                f"Sender: {display_name} <{email_addr}>\n"
                f"SMTP: {smtp_host}:{smtp_port}\n"
                f"Sent: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"✅ Sending pipeline is working!\n\n- {sender_first}\nFlinza Media"
            )
            msg.attach(MIMEText(body_text, "plain", "utf-8"))

            _send_smtp_email(smtp_host, smtp_port, email_addr, password, to_email, msg.as_string())

            # Track successful send
            conn2 = get_db()
            conn2.execute(
                "UPDATE gmail_accounts SET last_used=?, sent_today=COALESCE(sent_today,0)+1 WHERE email=?",
                (datetime.now().isoformat(), email_addr)
            )
            conn2.commit()
            conn2.close()

            return jsonify({
                "success":     True,
                "from":        email_addr,
                "sender_name": sender_first,
                "to":          to_email,
                "message_id":  message_id,
                "smtp":        f"{smtp_host}:{smtp_port}"
            })
        except Exception as e:
            last_error = f"{email_addr}: {str(e)}"
            continue

    return jsonify({"success": False, "error": last_error or "All candidate mailboxes failed"}), 500


# ── Sending Hours Settings ─────────────────────────────────────────────────────

@app.route("/api/settings/sending-hours", methods=["GET"])
@login_required
def get_sending_hours():
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='sending_hours'").fetchone()
    conn.close()
    if row:
        return jsonify({"success": True, "sending_hours": json.loads(row[0])})
    # Default: send 9am-6pm local time for each country timezone
    defaults = {
        "US": {"start": "09:00", "end": "18:00", "timezone": "America/New_York", "enabled": True},
        "UK": {"start": "09:00", "end": "17:30", "timezone": "Europe/London",   "enabled": True},
        "UAE": {"start": "10:00", "end": "17:00", "timezone": "Asia/Dubai",     "enabled": True},
        "AU": {"start": "09:00", "end": "17:00", "timezone": "Australia/Sydney","enabled": True},
        "CA": {"start": "09:00", "end": "18:00", "timezone": "America/Toronto", "enabled": True},
        "IN": {"start": "10:00", "end": "19:00", "timezone": "Asia/Kolkata",    "enabled": True},
        "default": {"start": "09:00", "end": "18:00", "timezone": "UTC",        "enabled": True},
    }
    return jsonify({"success": True, "sending_hours": defaults})


@app.route("/api/settings/sending-hours", methods=["POST"])
@login_required
def save_sending_hours():
    body = request.get_json(silent=True) or {}
    hours = body.get("sending_hours", {})
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('sending_hours', ?)",
        (json.dumps(hours),)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ── Export ────────────────────────────────────────────────────────────────────

@app.route("/api/leads/export", methods=["GET"])
@login_required
def export_leads():
    crm_priority = request.args.get("crm_priority")
    conn = get_db()
    query = "SELECT * FROM leads WHERE COALESCE(blacklisted,0)=0 AND COALESCE(unsubscribed,0)=0"
    params = []
    if crm_priority:
        query += " AND crm_priority=?"; params.append(crm_priority)
    query += " ORDER BY CASE WHEN crm_priority=0 THEN 9 ELSE crm_priority END ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=flinza_leads_export.csv"}
    )


# ── Serve Dashboard HTML ──────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
@login_required
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ═══════════════════════════════════════════════════════════════════════════════
# HTML Templates
# ═══════════════════════════════════════════════════════════════════════════════

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Flinza CRM — Login</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0f0f17;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Inter',system-ui,sans-serif}
  .card{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:16px;padding:40px;width:360px}
  h1{color:#fff;font-size:1.5rem;margin-bottom:8px}
  p{color:#888;font-size:0.9rem;margin-bottom:24px}
  label{display:block;color:#aaa;font-size:0.8rem;margin-bottom:6px;font-weight:600}
  input{width:100%;padding:12px 14px;background:#0f0f17;border:1px solid #2a2a4a;border-radius:8px;color:#fff;font-size:0.95rem;margin-bottom:16px;outline:none}
  input:focus{border-color:#6366f1}
  button{width:100%;padding:13px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer}
  button:hover{background:#4f52d8}
  .err{color:#f87171;font-size:0.85rem;margin-top:12px;display:none}
  .logo{font-size:2rem;margin-bottom:20px}
</style>
</head>
<body>
<div class="card">
  <div class="logo">⚡</div>
  <h1>Flinza CRM</h1>
  <p>Sign in to access your outreach dashboard</p>
  <form id="form">
    <label>Email</label>
    <input type="email" id="email" placeholder="you@flinza.com" required>
    <label>Password</label>
    <input type="password" id="pass" placeholder="••••••••" required>
    <button type="submit" id="btn">Sign In</button>
    <div class="err" id="err">Invalid credentials</div>
  </form>
</div>
<script>
  document.getElementById('form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = document.getElementById('btn');
    btn.textContent = 'Signing in…';
    btn.disabled = true;
    const r = await fetch('/login', {
      method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email: document.getElementById('email').value, password: document.getElementById('pass').value})
    });
    const d = await r.json();
    if(d.success){ window.location.href='/'; }
    else{ document.getElementById('err').style.display='block'; btn.textContent='Sign In'; btn.disabled=false; }
  });
</script>
</body>
</html>"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Flinza CRM — Lead Dashboard</title>
<style>
:root {
  --bg: #0a0a14;
  --surface: #12121e;
  --surface2: #1a1a2e;
  --border: #2a2a45;
  --text: #e2e2f0;
  --muted: #888;
  --accent: #6366f1;
  --accent2: #818cf8;
  --success: #22c55e;
  --warn: #f59e0b;
  --danger: #ef4444;
  --t1: #f59e0b;
  --t2: #6366f1;
  --t3: #64748b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;min-height:100vh}
.sidebar{position:fixed;left:0;top:0;bottom:0;width:220px;background:var(--surface);border-right:1px solid var(--border);padding:20px 0;z-index:100}
.logo{padding:0 20px 20px;font-size:1.3rem;font-weight:700;color:var(--accent);border-bottom:1px solid var(--border);margin-bottom:16px}
.logo span{color:var(--text)}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;color:var(--muted);font-size:0.9rem;cursor:pointer;transition:all 0.15s;border-radius:0}
.nav-item:hover,.nav-item.active{color:var(--text);background:var(--surface2)}
.nav-item svg{width:16px;height:16px}
.main{margin-left:220px;padding:24px;max-width:1600px}
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
h1{font-size:1.4rem;font-weight:700}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:0.75rem;font-weight:600}
.b-t1{background:#f59e0b22;color:var(--t1);border:1px solid #f59e0b44}
.b-t2{background:#6366f122;color:var(--t2);border:1px solid #6366f144}
.b-t3{background:#64748b22;color:var(--t3);border:1px solid #64748b44}
.b-unset{background:#ffffff11;color:#aaa;border:1px solid #ffffff22}
.b-verified{background:#22c55e22;color:var(--success);border:1px solid #22c55e44}
.b-new{background:#3b82f622;color:#60a5fa;border:1px solid #3b82f644}
.b-replied{background:#a855f722;color:#c084fc;border:1px solid #a855f744}
.b-contacted{background:#f97316;background:#f9731622;color:#fb923c;border:1px solid #f9731644}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px}
.stat-label{font-size:0.75rem;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
.stat-value{font-size:1.6rem;font-weight:700}
.stat-value.t1{color:var(--t1)}
.stat-value.t2{color:var(--t2)}
.filter-bar{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-label{font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
select, input[type=text], input[type=search]{background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:7px 12px;font-size:0.85rem;outline:none}
select:focus, input:focus{border-color:var(--accent)}
.btn{padding:8px 16px;border-radius:7px;border:none;font-size:0.85rem;font-weight:600;cursor:pointer;transition:all 0.15s}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:var(--accent2)}
.btn-danger{background:#ef444422;color:var(--danger);border:1px solid #ef444444}
.btn-danger:hover{background:var(--danger);color:#fff}
.btn-sm{padding:5px 10px;font-size:0.78rem}
.btn-outline{background:transparent;color:var(--text);border:1px solid var(--border)}
.btn-outline:hover{border-color:var(--accent);color:var(--accent)}
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
.bulk-bar{display:none;background:var(--accent);padding:10px 16px;align-items:center;gap:12px;font-size:0.85rem}
.bulk-bar.show{display:flex}
.bulk-bar select,.bulk-bar button{font-size:0.85rem}
table{width:100%;border-collapse:collapse}
thead th{background:var(--surface2);padding:11px 14px;text-align:left;font-size:0.75rem;text-transform:uppercase;color:var(--muted);letter-spacing:.5px;white-space:nowrap}
thead th:first-child{width:40px}
tbody tr{border-top:1px solid var(--border);transition:background 0.1s}
tbody tr:hover{background:var(--surface2)}
td{padding:10px 14px;font-size:0.85rem;vertical-align:middle}
td.email{color:var(--accent2);font-family:monospace;font-size:0.82rem}
.priority-btn{background:none;border:none;cursor:pointer;padding:3px 8px;border-radius:5px;font-size:0.78rem;font-weight:600;transition:all 0.15s}
.p-t1{background:#f59e0b22;color:var(--t1)}
.p-t2{background:#6366f122;color:var(--t2)}
.p-t3{background:#64748b22;color:var(--t3)}
.p-unset{background:#ffffff11;color:#aaa}
.priority-btn:hover{opacity:0.8;transform:scale(1.05)}
.modal-overlay{display:none;position:fixed;inset:0;background:#00000088;z-index:200;align-items:center;justify-content:center}
.modal-overlay.show{display:flex}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:28px;width:500px;max-height:80vh;overflow-y:auto}
.modal h2{font-size:1.1rem;margin-bottom:16px}
.form-row{margin-bottom:14px}
.form-row label{display:block;font-size:0.78rem;color:var(--muted);margin-bottom:5px}
.form-row input,.form-row select,.form-row textarea{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:8px 12px;font-size:0.85rem}
.form-row textarea{height:80px;resize:vertical;font-family:inherit}
.modal-footer{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
.toast{position:fixed;bottom:24px;right:24px;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:12px 20px;font-size:0.9rem;z-index:999;display:none;max-width:360px}
.toast.show{display:block;animation:slideIn 0.3s}
.toast.success{border-color:var(--success);color:var(--success)}
.toast.error{border-color:var(--danger);color:var(--danger)}
@keyframes slideIn{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}
.truncate{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.section{display:none}
.section.active{display:block}
.pill{display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;font-size:0.72rem;font-weight:600}
.hours-table{width:100%;border-collapse:collapse}
.hours-table th,.hours-table td{padding:10px 14px;border-top:1px solid var(--border);font-size:0.85rem;text-align:left}
.hours-table th{background:var(--surface2);font-size:0.75rem;color:var(--muted);text-transform:uppercase}
.hours-table input[type=time]{background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:5px 10px}
</style>
</head>
<body>

<!-- Sidebar -->
<div class="sidebar">
  <div class="logo">⚡ <span>Flinza</span></div>
  <div class="nav-item active" onclick="showSection('leads')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
    Leads CRM
  </div>
  <div class="nav-item" onclick="showSection('accounts')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
    Mailboxes
  </div>
  <div class="nav-item" onclick="showSection('hours')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
    Sending Hours
  </div>
  <div class="nav-item" onclick="showSection('stats')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
    Analytics
  </div>
</div>

<!-- Main Content -->
<div class="main">

  <!-- LEADS SECTION -->
  <div id="sec-leads" class="section active">
    <div class="topbar">
      <div>
        <h1>Lead Database</h1>
        <div style="color:var(--muted);font-size:0.85rem;margin-top:3px" id="lead-count-label">Loading…</div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn btn-outline" onclick="exportLeads()">⬇ Export CSV</button>
        <button class="btn btn-primary" onclick="openAddLead()">+ Add Lead</button>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-grid" id="stats-grid">
      <div class="stat-card"><div class="stat-label">Total Leads</div><div class="stat-value" id="s-total">—</div></div>
      <div class="stat-card"><div class="stat-label">⭐ Tier 1</div><div class="stat-value t1" id="s-t1">—</div></div>
      <div class="stat-card"><div class="stat-label">Tier 2</div><div class="stat-value t2" id="s-t2">—</div></div>
      <div class="stat-card"><div class="stat-label">Tier 3</div><div class="stat-value" id="s-t3" style="color:var(--t3)">—</div></div>
      <div class="stat-card"><div class="stat-label">Verified</div><div class="stat-value" id="s-verified" style="color:var(--success)">—</div></div>
      <div class="stat-card"><div class="stat-label">Daily Capacity</div><div class="stat-value" id="s-cap" style="font-size:1.1rem">—</div></div>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <div class="filter-group">
        <span class="filter-label">Search</span>
        <input type="search" id="f-search" placeholder="name, email, company…" oninput="debouncedLoad()" style="width:200px">
      </div>
      <div class="filter-group">
        <span class="filter-label">Priority</span>
        <select id="f-priority" onchange="loadLeads()">
          <option value="">All Priorities</option>
          <option value="1">⭐ Tier 1 — Next Send</option>
          <option value="2">Tier 2 — Secondary</option>
          <option value="3">Tier 3 — Backup</option>
          <option value="0">Unassigned</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Stage</span>
        <select id="f-stage" onchange="loadLeads()">
          <option value="">All Stages</option>
          <option value="new">New</option>
          <option value="contacted">Contacted</option>
          <option value="replied">Replied</option>
          <option value="closed">Closed</option>
          <option value="not_interested">Not Interested</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Niche</span>
        <select id="f-niche" onchange="loadLeads()">
          <option value="">All Niches</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Country</span>
        <select id="f-country" onchange="loadLeads()">
          <option value="">All Countries</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Email Status</span>
        <select id="f-del" onchange="loadLeads()">
          <option value="">All</option>
          <option value="verified">Verified</option>
          <option value="unverified">Unverified</option>
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-label">Sort By</span>
        <select id="f-sort" onchange="loadLeads()">
          <option value="crm_priority_asc">Priority (Low→High)</option>
          <option value="added_desc">Newest First</option>
          <option value="company_asc">Company A-Z</option>
          <option value="followers_desc">Most Followers</option>
          <option value="score_desc">Highest Score</option>
        </select>
      </div>
      <button class="btn btn-outline btn-sm" onclick="clearFilters()">✕ Clear</button>
    </div>

    <!-- Bulk Action Bar -->
    <div class="bulk-bar" id="bulk-bar">
      <span id="bulk-count">0 selected</span>
      <select id="bulk-action-type" onchange="updateBulkUI()">
        <option value="">— Bulk Action —</option>
        <option value="set_priority">Set Priority</option>
        <option value="set_stage">Set Stage</option>
        <option value="blacklist">Blacklist</option>
        <option value="delete">Delete</option>
      </select>
      <select id="bulk-priority-val" style="display:none">
        <option value="1">⭐ Tier 1 — Next Send</option>
        <option value="2">Tier 2 — Secondary</option>
        <option value="3">Tier 3 — Backup</option>
        <option value="0">Unassigned</option>
      </select>
      <select id="bulk-stage-val" style="display:none">
        <option value="new">New</option>
        <option value="contacted">Contacted</option>
        <option value="replied">Replied</option>
        <option value="closed">Closed</option>
        <option value="not_interested">Not Interested</option>
      </select>
      <button class="btn" style="background:#fff;color:#333" onclick="runBulkAction()">Apply</button>
      <button class="btn btn-outline" style="margin-left:auto" onclick="clearSelection()">Cancel</button>
    </div>

    <!-- Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th><input type="checkbox" id="select-all" onchange="toggleAll(this.checked)"></th>
            <th>Priority</th>
            <th>Name / Company</th>
            <th>Email</th>
            <th>Niche</th>
            <th>Country</th>
            <th>Followers</th>
            <th>Stage</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="leads-tbody">
          <tr><td colspan="10" style="text-align:center;padding:40px;color:var(--muted)">Loading leads…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- MAILBOXES SECTION -->
  <div id="sec-accounts" class="section">
    <div class="topbar">
      <h1>Mailbox Fleet</h1>
      <button class="btn btn-primary" onclick="sendTestEmail()">📧 Send Test Email</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Email</th><th>Provider</th><th>SMTP</th><th>Daily Limit</th><th>Sent Today</th><th>Status</th></tr>
        </thead>
        <tbody id="accounts-tbody">
          <tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted)">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- SENDING HOURS SECTION -->
  <div id="sec-hours" class="section">
    <div class="topbar">
      <h1>Country-wise Sending Hours</h1>
      <button class="btn btn-primary" onclick="saveSendingHours()">💾 Save Hours</button>
    </div>
    <p style="color:var(--muted);margin-bottom:20px;font-size:0.9rem">
      Set optimal sending windows per country for highest reply rates.
      Emails to leads in each country will only be sent during these local hours.
    </p>
    <div class="table-wrap">
      <table class="hours-table">
        <thead><tr><th>Country</th><th>Timezone</th><th>Send From</th><th>Send Until</th><th>Enabled</th></tr></thead>
        <tbody id="hours-tbody"><tr><td colspan="5" style="padding:30px;text-align:center;color:var(--muted)">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- ANALYTICS SECTION -->
  <div id="sec-stats" class="section">
    <h1>Campaign Analytics</h1>
    <div class="stats-grid" style="margin-top:20px">
      <div class="stat-card"><div class="stat-label">Total Leads</div><div class="stat-value" id="a-total">—</div></div>
      <div class="stat-card"><div class="stat-label">⭐ Tier 1</div><div class="stat-value t1" id="a-t1">—</div></div>
      <div class="stat-card"><div class="stat-label">Tier 2</div><div class="stat-value t2" id="a-t2">—</div></div>
      <div class="stat-card"><div class="stat-label">Tier 3</div><div class="stat-value" id="a-t3" style="color:var(--t3)">—</div></div>
      <div class="stat-card"><div class="stat-label">Verified Emails</div><div class="stat-value" id="a-ver" style="color:var(--success)">—</div></div>
      <div class="stat-card"><div class="stat-label">New Leads</div><div class="stat-value" id="a-new" style="color:#60a5fa">—</div></div>
      <div class="stat-card"><div class="stat-label">Contacted</div><div class="stat-value" id="a-cont" style="color:#fb923c">—</div></div>
      <div class="stat-card"><div class="stat-label">Replied</div><div class="stat-value" id="a-rep" style="color:#c084fc">—</div></div>
      <div class="stat-card"><div class="stat-label">Active Mailboxes</div><div class="stat-value" id="a-mb">—</div></div>
      <div class="stat-card"><div class="stat-label">Daily Capacity</div><div class="stat-value" id="a-cap" style="font-size:1.1rem">—</div></div>
    </div>
  </div>
</div>

<!-- Add/Edit Lead Modal -->
<div class="modal-overlay" id="lead-modal">
  <div class="modal">
    <h2 id="modal-title">Add Lead</h2>
    <div class="form-row"><label>Name</label><input id="m-name" placeholder="Founder name"></div>
    <div class="form-row"><label>Email *</label><input id="m-email" type="email" placeholder="email@brand.com"></div>
    <div class="form-row"><label>Company / Brand</label><input id="m-company" placeholder="Brand name"></div>
    <div class="form-row"><label>Niche</label><input id="m-niche" placeholder="DTC, Beauty, Jewelry…"></div>
    <div class="form-row"><label>Website</label><input id="m-website" placeholder="https://…"></div>
    <div class="form-row"><label>Country</label><input id="m-country" placeholder="US, UK, UAE…"></div>
    <div class="form-row"><label>Priority Tier</label>
      <select id="m-priority">
        <option value="0">Unassigned</option>
        <option value="1">⭐ Tier 1 — Next Send</option>
        <option value="2">Tier 2 — Secondary</option>
        <option value="3">Tier 3 — Backup</option>
      </select>
    </div>
    <div class="form-row"><label>Stage</label>
      <select id="m-stage">
        <option value="new">New</option>
        <option value="contacted">Contacted</option>
        <option value="replied">Replied</option>
        <option value="closed">Closed</option>
        <option value="not_interested">Not Interested</option>
      </select>
    </div>
    <div class="form-row"><label>Notes / Icebreaker</label><textarea id="m-notes" placeholder="Personalized hook…"></textarea></div>
    <div class="modal-footer">
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveLead()">Save Lead</button>
    </div>
  </div>
</div>

<!-- Email Preview Modal -->
<div class="modal-overlay" id="email-modal">
  <div class="modal" style="width:650px;max-width:95vw">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h2 id="email-modal-title" style="margin-bottom:0">Email Outreach Preview</h2>
      <button class="btn btn-outline btn-sm" onclick="closeEmailModal()">✕</button>
    </div>
    <div style="color:var(--muted);font-size:0.82rem;margin-bottom:16px" id="email-modal-lead-info"></div>

    <div style="display:flex;gap:8px;border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:16px">
      <button class="btn btn-sm" id="tab-btn-a" onclick="switchTemplateTab('A')" style="background:var(--accent);color:#fff">Template A (Ad Spend Gap)</button>
      <button class="btn btn-sm btn-outline" id="tab-btn-b" onclick="switchTemplateTab('B')">Template B (Creative 60D)</button>
      <button class="btn btn-sm btn-outline" id="tab-btn-f1" onclick="switchTemplateTab('F1')">Follow Up 1</button>
    </div>

    <div class="form-row">
      <label>Subject</label>
      <input type="text" id="em-subject" style="font-weight:600">
    </div>
    <div class="form-row">
      <label>Email Body</label>
      <textarea id="em-body" style="height:220px;font-family:inherit;font-size:0.9rem;line-height:1.5"></textarea>
    </div>

    <div class="modal-footer" style="display:flex;justify-content:space-between;align-items:center">
      <button class="btn btn-outline" onclick="sendPreviewTestEmail()" id="btn-send-preview-test">📧 Send Test to f12x.studio@gmail.com</button>
      <div style="display:flex;gap:10px">
        <button class="btn btn-outline" onclick="closeEmailModal()">Close</button>
        <button class="btn btn-primary" onclick="copyEmailText()">📋 Copy Text</button>
      </div>
    </div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let allLeads = [];
let selectedIds = new Set();
let editingLeadId = null;
let debounceTimer = null;
let nextSenderName = 'Zoya';
let nextSenderEmail = '';

async function fetchNextSender() {
  try {
    const d = await api('/api/accounts/next-sender');
    if(d && d.success && d.first_name) {
      nextSenderName = d.first_name;
      nextSenderEmail = d.email || '';
    }
  } catch(e) {
    console.error('fetchNextSender error:', e);
  }
}

const PRIORITY_LABELS = {0:'Unset',1:'⭐ T1',2:'T2',3:'T3'};
const PRIORITY_CSS    = {0:'p-unset',1:'p-t1',2:'p-t2',3:'p-t3'};
const STAGE_CSS       = {new:'b-new',contacted:'b-contacted',replied:'b-replied',closed:'b-verified',not_interested:'b-t3'};

// ── Section nav ───────────────────────────────────────────────────────────────
function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('sec-' + name).classList.add('active');
  event.currentTarget.classList.add('active');
  if(name === 'accounts') loadAccounts();
  if(name === 'hours') loadHours();
  if(name === 'stats') loadStats();
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.classList.remove('show'); }, 3500);
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function api(path, method='GET', body=null) {
  const opts = { method, headers: {'Content-Type':'application/json'} };
  if(body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.json();
}

// ── Stats ─────────────────────────────────────────────────────────────────────
async function loadStats() {
  const d = await api('/api/stats');
  if(!d.success) return;
  const s = d.stats;
  ['total','t1','t2','t3','verified','cap'].forEach(k => {
    const el = document.getElementById('s-'+k);
    if(el) el.textContent = k === 'cap' ? (s.daily_capacity||0).toLocaleString()+'/day' : (s[{total:'total_leads',t1:'tier1',t2:'tier2',t3:'tier3',verified:'verified',cap:'daily_capacity'}[k]]||0).toLocaleString();
  });
  ['total','t1','t2','t3','ver','new','cont','rep','mb','cap'].forEach(k => {
    const el = document.getElementById('a-'+k);
    if(el) {
      const map = {total:'total_leads',t1:'tier1',t2:'tier2',t3:'tier3',ver:'verified',new:'new_leads',cont:'contacted',rep:'replied',mb:'active_mailboxes',cap:'daily_capacity'};
      el.textContent = k === 'cap' ? (s.daily_capacity||0).toLocaleString()+'/day' : (s[map[k]]||0).toLocaleString();
    }
  });
}

// ── Filter options ─────────────────────────────────────────────────────────────
async function loadFilterOptions() {
  const d = await api('/api/leads/filter-options');
  const nn = document.getElementById('f-niche');
  d.niches.forEach(n => { const o = document.createElement('option'); o.value=n; o.textContent=n; nn.appendChild(o); });
  const cc = document.getElementById('f-country');
  d.countries.forEach(c => { const o = document.createElement('option'); o.value=c; o.textContent=c; cc.appendChild(o); });
}

// ── Load leads ─────────────────────────────────────────────────────────────────
async function loadLeads() {
  const params = new URLSearchParams();
  const search   = document.getElementById('f-search').value.trim();
  const priority = document.getElementById('f-priority').value;
  const stage    = document.getElementById('f-stage').value;
  const niche    = document.getElementById('f-niche').value;
  const country  = document.getElementById('f-country').value;
  const del      = document.getElementById('f-del').value;
  const sort     = document.getElementById('f-sort').value;
  if(search)   params.set('search', search);
  if(priority) params.set('crm_priority', priority);
  if(stage)    params.set('stage', stage);
  if(niche)    params.set('niche', niche);
  if(country)  params.set('country', country);
  if(del)      params.set('deliverability_status', del);
  if(sort)     params.set('sort', sort);
  params.set('limit', '1000');

  const d = await fetch('/api/leads?' + params).then(r => r.json());
  allLeads = d.leads || [];
  renderLeads(allLeads);
  document.getElementById('lead-count-label').textContent = `${allLeads.length} leads`;
  loadStats();
}

function debouncedLoad() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadLeads, 350);
}

function clearFilters() {
  ['f-search','f-priority','f-stage','f-niche','f-country','f-del'].forEach(id => {
    const el = document.getElementById(id);
    el.value = '';
  });
  document.getElementById('f-sort').value = 'crm_priority_asc';
  loadLeads();
}

// ── Render table ──────────────────────────────────────────────────────────────
function renderLeads(leads) {
  const tbody = document.getElementById('leads-tbody');
  if(!leads.length){
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:40px;color:var(--muted)">No leads found</td></tr>';
    return;
  }
  tbody.innerHTML = leads.map(l => {
    const prio = l.crm_priority || 0;
    const stage = l.stage || 'new';
    const stageBadge = STAGE_CSS[stage] || 'b-unset';
    const delBadge = l.deliverability_status === 'verified' ? 'b-verified' : 'b-unset';
    const checked = selectedIds.has(l.id) ? 'checked' : '';
    const followers = l.instagram_followers ? (l.instagram_followers >= 1000 ? (l.instagram_followers/1000).toFixed(0)+'K' : l.instagram_followers) : '—';
    return `<tr id="row-${l.id}" ${selectedIds.has(l.id)?'style="background:var(--accent)18"':''}>
      <td><input type="checkbox" ${checked} onchange="toggleRow(${l.id},this.checked)"></td>
      <td>
        <button class="priority-btn ${PRIORITY_CSS[prio]}" onclick="cyclePriority(${l.id},${prio})" title="Click to change priority">
          ${PRIORITY_LABELS[prio]}
        </button>
      </td>
      <td>
        <div style="font-weight:600;font-size:0.85rem" class="truncate">${l.name||'—'}</div>
        <div style="color:var(--muted);font-size:0.75rem" class="truncate">${l.company||''}</div>
      </td>
      <td class="email">${l.email}</td>
      <td>
        <div class="truncate" style="font-size:0.82rem">${l.niche||'—'}</div>
        ${l.sub_niche ? `<div style="color:var(--muted);font-size:0.72rem">${l.sub_niche}</div>` : ''}
      </td>
      <td>${l.country||'—'}</td>
      <td>${followers}</td>
      <td><span class="badge ${stageBadge}">${stage}</span></td>
      <td><span class="badge ${delBadge}">${l.deliverability_status||'—'}</span></td>
      <td style="white-space:nowrap">
        <button class="btn btn-outline btn-sm" onclick="previewEmail(${l.id})">✉️ Email</button>
        <button class="btn btn-outline btn-sm" onclick="openEditLead(${l.id})">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteLead(${l.id})">Del</button>
      </td>
    </tr>`;
  }).join('');
}

// ── Priority cycle ─────────────────────────────────────────────────────────────
async function cyclePriority(id, current) {
  const next = current === 0 ? 1 : current === 1 ? 2 : current === 2 ? 3 : 0;
  const d = await api(`/api/leads/${id}`, 'PATCH', {crm_priority: next});
  if(d.success) {
    const lead = allLeads.find(l => l.id === id);
    if(lead) lead.crm_priority = next;
    renderLeads(allLeads);
    toast(`Priority set to ${PRIORITY_LABELS[next]}`);
    loadStats();
  }
}

// ── Selection ──────────────────────────────────────────────────────────────────
function toggleRow(id, checked) {
  if(checked) selectedIds.add(id);
  else selectedIds.delete(id);
  updateBulkBar();
}

function toggleAll(checked) {
  allLeads.forEach(l => { if(checked) selectedIds.add(l.id); else selectedIds.delete(l.id); });
  document.querySelectorAll('#leads-tbody input[type=checkbox]').forEach(cb => cb.checked = checked);
  updateBulkBar();
}

function clearSelection() {
  selectedIds.clear();
  document.getElementById('select-all').checked = false;
  document.querySelectorAll('#leads-tbody input[type=checkbox]').forEach(cb => cb.checked = false);
  updateBulkBar();
}

function updateBulkBar() {
  const bar = document.getElementById('bulk-bar');
  if(selectedIds.size > 0) {
    bar.classList.add('show');
    document.getElementById('bulk-count').textContent = `${selectedIds.size} selected`;
  } else {
    bar.classList.remove('show');
  }
}

function updateBulkUI() {
  const action = document.getElementById('bulk-action-type').value;
  document.getElementById('bulk-priority-val').style.display = action === 'set_priority' ? 'block' : 'none';
  document.getElementById('bulk-stage-val').style.display    = action === 'set_stage'    ? 'block' : 'none';
}

async function runBulkAction() {
  const action = document.getElementById('bulk-action-type').value;
  if(!action) { toast('Select an action first', 'error'); return; }
  const ids = [...selectedIds];
  if(!ids.length) return;

  if(action === 'delete') {
    if(!confirm(`Delete ${ids.length} leads permanently? This cannot be undone.`)) return;
  }

  let body = {ids, action};
  if(action === 'set_priority') body.value = document.getElementById('bulk-priority-val').value;
  if(action === 'set_stage')    body.value = document.getElementById('bulk-stage-val').value;

  const d = await api('/api/leads/bulk', 'POST', body);
  if(d.success) {
    toast(`${action} applied to ${d.affected} leads ✅`);
    clearSelection();
    loadLeads();
  } else {
    toast(d.error || 'Error', 'error');
  }
}

// ── Add / Edit Lead ────────────────────────────────────────────────────────────
function openAddLead() {
  editingLeadId = null;
  document.getElementById('modal-title').textContent = 'Add Lead';
  ['m-name','m-email','m-company','m-niche','m-website','m-country','m-notes'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('m-priority').value = '0';
  document.getElementById('m-stage').value = 'new';
  document.getElementById('lead-modal').classList.add('show');
}

function openEditLead(id) {
  const l = allLeads.find(x => x.id === id);
  if(!l) return;
  editingLeadId = id;
  document.getElementById('modal-title').textContent = 'Edit Lead';
  document.getElementById('m-name').value    = l.name || '';
  document.getElementById('m-email').value   = l.email || '';
  document.getElementById('m-company').value = l.company || '';
  document.getElementById('m-niche').value   = l.niche || '';
  document.getElementById('m-website').value = l.website || '';
  document.getElementById('m-country').value = l.country || '';
  document.getElementById('m-notes').value   = l.notes || l.custom_hook || '';
  document.getElementById('m-priority').value = String(l.crm_priority || 0);
  document.getElementById('m-stage').value   = l.stage || 'new';
  document.getElementById('lead-modal').classList.add('show');
}

function closeModal() { document.getElementById('lead-modal').classList.remove('show'); }

async function saveLead() {
  const data = {
    name:        document.getElementById('m-name').value,
    email:       document.getElementById('m-email').value,
    company:     document.getElementById('m-company').value,
    niche:       document.getElementById('m-niche').value,
    website:     document.getElementById('m-website').value,
    country:     document.getElementById('m-country').value,
    notes:       document.getElementById('m-notes').value,
    crm_priority:parseInt(document.getElementById('m-priority').value) || 0,
    stage:       document.getElementById('m-stage').value,
  };

  if(!data.email || !data.email.includes('@')) {
    toast('Valid email required', 'error'); return;
  }

  let d;
  if(editingLeadId) {
    d = await api(`/api/leads/${editingLeadId}`, 'PATCH', data);
  } else {
    // Use import endpoint for add
    const csvRow = `first_name,email,company,niche,website\n${data.name},${data.email},${data.company},${data.niche},${data.website}`;
    d = await api('/api/leads/upload-csv', 'POST', {csv_text: csvRow});
    if(d.success && d.imported_count > 0) {
      // Also update additional fields
      const newId = d.leads[0]?.id;
      if(newId) await api(`/api/leads/${newId}`, 'PATCH', {crm_priority: data.crm_priority, stage: data.stage, country: data.country, notes: data.notes});
    }
  }

  if(d.success) {
    closeModal();
    toast(editingLeadId ? 'Lead updated ✅' : 'Lead added ✅');
    loadLeads();
  } else {
    toast(d.error || 'Error saving lead', 'error');
  }
}

async function deleteLead(id) {
  if(!confirm('Delete this lead?')) return;
  const d = await api(`/api/leads/${id}`, 'DELETE');
  if(d.success) { toast('Lead deleted'); loadLeads(); }
}

// ── Email Preview ─────────────────────────────────────────────────────────────
let previewLead = null;
let currentTab = 'A';

async function previewEmail(id) {
  previewLead = allLeads.find(l => l.id === id);
  if(!previewLead) return;
  await fetchNextSender();
  const mbInfo = nextSenderEmail ? ` • Sender: ${nextSenderName} <${nextSenderEmail}>` : ` • Sender: ${nextSenderName}`;
  document.getElementById('email-modal-lead-info').textContent = 
    `Lead: ${previewLead.name || 'Founder'} • ${previewLead.company || 'Brand'} • ${previewLead.email} • Country: ${previewLead.country || 'US'}${mbInfo}`;
  switchTemplateTab('A');
  document.getElementById('email-modal').classList.add('show');
}

function closeEmailModal() {
  document.getElementById('email-modal').classList.remove('show');
}

function switchTemplateTab(tab) {
  currentTab = tab;
  ['a', 'b', 'f1'].forEach(t => {
    const btn = document.getElementById('tab-btn-' + t);
    if(btn) {
      if(t === tab.toLowerCase()) {
        btn.style.background = 'var(--accent)';
        btn.style.color = '#fff';
      } else {
        btn.style.background = 'transparent';
        btn.style.color = 'var(--text)';
      }
    }
  });

  if(!previewLead) return;
  const firstName = (previewLead.name ? previewLead.name.split(' ')[0] : 'there') || 'there';
  const company = previewLead.company || 'your brand';
  const icebreaker = previewLead.personalized_icebreaker || previewLead.custom_hook || `Loved what ${company} is doing in your space, the creative aesthetic and product line really stand out.`;
  const followers = previewLead.instagram_followers || 0;
  
  let orderLift = '15-25 more orders a day';
  let revLift = '$30k-$50k in monthly revenue';
  if(followers >= 200000) {
    orderLift = '35-50 more orders a day';
    revLift = '$50k-$80k in monthly revenue';
  } else if((previewLead.niche||'').toLowerCase().includes('beauty') || (previewLead.niche||'').toLowerCase().includes('skin')) {
    orderLift = '15-20 more orders a day';
    revLift = '$28k-$45k in monthly revenue';
  }

  // sig is built from the actual next sender account's first name
  const sig = `${nextSenderName}\nFlinza Media`;

  if(tab === 'A') {
    document.getElementById('em-subject').value = `${firstName} - quick one on ${company}'s ad spend`;
    document.getElementById('em-body').value = 
`Hey ${firstName},

${icebreaker}

I checked out your ad account and found a gap you're leaving on the table. We think we can get you ${orderLift} and ${revLift}.

Want me to show you what I found?

${sig}

PS: got a skincare brand 15 more orders a day in 5 weeks.`;
  } else if(tab === 'B') {
    document.getElementById('em-subject').value = `${firstName} - quick question on ${company}'s creative`;
    document.getElementById('em-body').value = 
`Hi ${firstName},

${icebreaker}

We'll get you ${orderLift} and ${revLift} in 60 days. We run the creative end to end, you stay on delivery. No result, no invoice.

Want to hear how?

${sig}

PS: helped a supplements brand add $35k in revenue in under 2 months.`;
  } else if(tab === 'F1') {
    document.getElementById('em-subject').value = `Re: ${firstName} - quick one on ${company}'s ad spend`;
    document.getElementById('em-body').value = 
`Hi ${firstName},

Just circling up in case it got lost. Still happy to show you what we found for ${company} if useful.

Worth a quick look?

${sig}`;
  }
}

async function sendPreviewTestEmail() {
  if(!previewLead) return;
  const btn = document.getElementById('btn-send-preview-test');
  btn.textContent = 'Sending test…';
  btn.disabled = true;
  const subject = document.getElementById('em-subject').value;
  const body = document.getElementById('em-body').value;
  const d = await api('/api/accounts/test', 'POST', {
    to_email: 'f12x.studio@gmail.com',
    subject: subject,
    body: body
  });
  btn.textContent = '📧 Send Test to f12x.studio@gmail.com';
  btn.disabled = false;
  if(d.success) {
    // Refresh next sender name after a send (rotation happened)
    fetchNextSender();
    toast(`✅ Sent from ${d.from} (${d.sender_name}) to f12x.studio@gmail.com`);
  } else {
    toast('❌ ' + (d.error || 'Send failed'), 'error');
  }
}

function copyEmailText() {
  const s = document.getElementById('em-subject').value;
  const b = document.getElementById('em-body').value;
  navigator.clipboard.writeText(`Subject: ${s}\n\n${b}`);
  toast('Email copied to clipboard 📋');
}

// ── Accounts ──────────────────────────────────────────────────────────────────
async function loadAccounts() {
  const d = await api('/api/accounts');
  const tbody = document.getElementById('accounts-tbody');
  tbody.innerHTML = (d.accounts || []).map(a => `
    <tr>
      <td style="font-family:monospace;font-size:0.85rem">${a.email}</td>
      <td>${a.provider || 'smtp'}</td>
      <td style="font-size:0.8rem;color:var(--muted)">${a.smtp_host||''}:${a.smtp_port||''}</td>
      <td>${a.daily_limit || 50}</td>
      <td>${a.sent_today || 0}</td>
      <td><span class="badge ${a.active?'b-verified':'b-t3'}">${a.active?'Active':'Paused'}</span></td>
    </tr>`).join('');
}

async function sendTestEmail() {
  const to = prompt('Send test email to:', 'f12x.studio@gmail.com');
  if(!to) return;
  toast('Sending…');
  const d = await api('/api/accounts/test', 'POST', {to_email: to});
  if(d.success) toast(`✅ Test sent from ${d.from} to ${d.to}`);
  else toast('❌ ' + (d.error || 'Send failed'), 'error');
}

// ── Sending hours ─────────────────────────────────────────────────────────────
let hoursData = {};

async function loadHours() {
  const d = await api('/api/settings/sending-hours');
  hoursData = d.sending_hours || {};
  const tbody = document.getElementById('hours-tbody');
  tbody.innerHTML = Object.entries(hoursData).map(([country, cfg]) => `
    <tr>
      <td><strong>${country}</strong></td>
      <td style="color:var(--muted);font-size:0.82rem">${cfg.timezone}</td>
      <td><input type="time" id="h-start-${country}" value="${cfg.start||'09:00'}"></td>
      <td><input type="time" id="h-end-${country}"   value="${cfg.end||'18:00'}"></td>
      <td>
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="h-en-${country}" ${cfg.enabled?'checked':''}> Enabled
        </label>
      </td>
    </tr>`).join('');
}

async function saveSendingHours() {
  const updated = {};
  Object.entries(hoursData).forEach(([country, cfg]) => {
    updated[country] = {
      ...cfg,
      start:   document.getElementById('h-start-'+country)?.value || cfg.start,
      end:     document.getElementById('h-end-'+country)?.value   || cfg.end,
      enabled: document.getElementById('h-en-'+country)?.checked  ?? cfg.enabled,
    };
  });
  const d = await api('/api/settings/sending-hours', 'POST', {sending_hours: updated});
  if(d.success) toast('Sending hours saved ✅');
  else toast('Error saving hours', 'error');
}

function exportLeads() {
  const priority = document.getElementById('f-priority').value;
  const params = priority ? `?crm_priority=${priority}` : '';
  window.location.href = '/api/leads/export' + params;
}

// ── Upload CSV inline ─────────────────────────────────────────────────────────
async function uploadLeadsCSV(input) {
  if(!input.files[0]) return;
  const form = new FormData();
  form.append('file', input.files[0]);
  const r = await fetch('/api/leads/import', {method:'POST', body: form});
  const d = await r.json();
  if(d.success) { toast(`Imported ${d.result?.inserted||0} leads ✅`); loadLeads(); }
  else toast(d.error || 'Import failed', 'error');
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async function init() {
  await fetchNextSender();
  await loadFilterOptions();
  await loadLeads();
  await loadStats();
})();
</script>
</body>
</html>"""


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    print(f"\n⚡ Flinza CRM Dashboard starting on http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
