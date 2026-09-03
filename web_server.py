"""
Flinza — Enterprise Outreach Web Studio Server
FastAPI application providing REST APIs, Open/Click tracking handlers,
Google OAuth2 callback processing, and serving the Studio Single-Page Application.
"""

import os
import json
import logging
import threading
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Response, Query, Form, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import config
import database as db
import email_sender
import email_queue
import reply_watcher
import followup_scheduler
import cloudflare_aliases
import ai_router
import email_toolkit
import google_auth
import signature_generator
import tracking_server
import outreach_engine
import email_verifier

logger = logging.getLogger(__name__)

def mask_credentials(data: dict) -> dict:
    """Masks sensitive credentials before returning in API responses."""
    clean = dict(data)
    for key in ["app_password", "smtp_pass", "custom_smtp_pass", "password", "cf_api_token"]:
        if clean.get(key):
            clean[key] = "••••••••••••"
    return clean

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Flinza Works Outreach Studio",
    description="Enterprise Cold Email Outreach & Agency Studio",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
os.makedirs(STATIC_DIR / "css", exist_ok=True)
os.makedirs(STATIC_DIR / "js", exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ═══════════════════════════════════════════════════════════════
#                    SPA DASHBOARD ROUTE
# ═══════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Serves the main Flinza Studio application shell."""
    return templates.TemplateResponse(request=request, name="index.html", context={"app_name": "Flinza Studio"})


# ═══════════════════════════════════════════════════════════════
#             EMAIL TRACKING (OPENS & CLICKS)
# ═══════════════════════════════════════════════════════════════

@app.get("/t/o/{token}.png")
async def track_open_pixel(token: str, request: Request):
    """Serves 1x1 transparent GIF/PNG and records email open event."""
    user_agent = request.headers.get("user-agent", "")
    client_ip = request.client.host if request.client else ""
    png_bytes = tracking_server.handle_open(token, user_agent=user_agent, ip=client_ip)
    return Response(content=png_bytes, media_type="image/png", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/t/c/{token}")
async def track_click_redirect(token: str, target: str = Query(...), request: Request = None):
    """Records link click event and redirects to destination URL."""
    user_agent = request.headers.get("user-agent", "") if request else ""
    client_ip = request.client.host if request and request.client else ""
    dest_url = tracking_server.handle_click(token, target, user_agent=user_agent, ip=client_ip)
    return RedirectResponse(url=dest_url, status_code=302)


# ═══════════════════════════════════════════════════════════════
#             GOOGLE OAUTH2 AUTHENTICATION
# ═══════════════════════════════════════════════════════════════

@app.get("/auth/google/login")
async def google_login():
    """Generates Google OAuth2 consent URL and redirects the user."""
    url = google_auth.get_google_auth_url()
    if not url:
        return JSONResponse(
            {"error": "Google Client ID is not configured. Set it in settings or .env"},
            status_code=400,
        )
    return RedirectResponse(url=url)


@app.get("/auth/google/callback")
async def google_callback(code: Optional[str] = None, error: Optional[str] = None):
    """Handles OAuth callback and exchanges code for access & refresh tokens."""
    if error:
        return HTMLResponse(f"<h3>Google OAuth Failed</h3><p>{error}</p><a href='/'>Return to Studio</a>")
    if not code:
        return HTMLResponse("<h3>Missing authorization code</h3><a href='/'>Return to Studio</a>")

    res = google_auth.exchange_code_for_tokens(code)
    if res.get("success"):
        return HTMLResponse(
            f"""<html><body style="font-family:system-ui;background:#0f111a;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;">
            <div style="background:#1a1d2d;padding:40px;border-radius:12px;border:1px solid #313752;text-align:center;">
                <h2 style="color:#10b981;margin-top:0;">✅ Google Account Connected!</h2>
                <p>Connected email: <b>{res['email']}</b></p>
                <p style="color:#94a3b8;">Flinza can now dispatch emails via Gmail REST API.</p>
                <a href="/" style="display:inline-block;margin-top:20px;padding:10px 24px;background:#6366f1;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;">Open Flinza Studio</a>
            </div>
            <script>setTimeout(function(){{ window.location.href = '/'; }}, 2500);</script>
            </body></html>"""
        )
    return HTMLResponse(f"<h3>OAuth Exchange Error</h3><p>{res.get('error')}</p><a href='/'>Return</a>")


# ═══════════════════════════════════════════════════════════════
#                      REST API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/api/stats")
async def get_dashboard_stats():
    """Returns overview statistics, delivery metrics, pipeline breakdown, and queue status."""
    stats = db.get_stats()
    tracking = db.get_tracking_stats()
    pipeline = db.get_pipeline_breakdown()
    warmup = db.get_warmup_status()
    is_q_running = email_queue.is_running()
    is_q_paused = email_queue.is_paused()

    return {
        "success": True,
        "stats": stats,
        "tracking": tracking,
        "pipeline": pipeline,
        "warmup": warmup,
        "queue_status": "paused" if is_q_paused else ("running" if is_q_running else "idle"),
    }


@app.get("/api/leads")
async def list_leads(stage: Optional[str] = None, search: Optional[str] = None):
    """Returns leads list with optional stage and text filter."""
    if search:
        leads = db.search_leads(search)
    else:
        leads = db.get_leads(stage=stage if stage and stage != "all" else None, limit=150)
    return {"success": True, "count": len(leads), "leads": leads}


@app.post("/api/leads")
async def add_or_update_lead(request: Request):
    """Add a new lead to database."""
    body = await request.json()
    email = body.get("email", "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")

    lead_id = db.add_lead(
        email=email,
        name=body.get("name", "").strip(),
        handle=body.get("handle", "").strip(),
        niche=body.get("niche", "").strip(),
        tier=body.get("tier", "medium"),
        notes=body.get("notes", "").strip(),
        company=body.get("company", "").strip(),
        website=body.get("website", "").strip(),
    )
    return {"success": True, "lead_id": lead_id}


@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int):
    """Deletes a lead from the CRM."""
    db.delete_lead(lead_id)
    return {"success": True, "deleted_id": lead_id}


@app.post("/api/leads/import")
async def import_leads_csv(file: UploadFile = File(...)):
    """Uploads and imports a CSV file of leads."""
    content = await file.read()
    temp_path = BASE_DIR / f"temp_{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(content)

    import leads_importer
    result = leads_importer.import_csv(str(temp_path))
    try:
        os.remove(temp_path)
    except Exception:
        pass
    return {"success": True, "result": result}


@app.get("/api/leads/export")
async def export_leads():
    """Exports leads as CSV string."""
    csv_str = db.export_leads_csv()
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flinza_leads.csv"},
    )


@app.get("/api/accounts")
async def get_accounts_fleet():
    """Returns list of all Gmail master inboxes, OAuth accounts, and domain aliases."""
    raw_accounts = db.get_all_accounts()
    raw_aliases = db.get_all_aliases()
    oauth_accs = db.get_all_oauth_accounts()
    oauth_map = {o["account_email"].lower(): True for o in oauth_accs}

    accounts = []
    for a in raw_accounts:
        d = dict(a)
        d["is_oauth"] = bool(oauth_map.get(d["email"].lower()))
        accounts.append(d)

    aliases = [dict(al) for al in raw_aliases]

    return {
        "success": True,
        "accounts": accounts,
        "aliases": aliases,
        "total_inboxes": len(accounts),
        "total_aliases": len(aliases),
    }


@app.post("/api/accounts")
async def create_account(request: Request):
    """Adds a Gmail account or alias."""
    body = await request.json()
    acct_type = body.get("type", "gmail")

    if acct_type == "alias":
        alias = body.get("alias", "").strip().lower()
        smtp_user = body.get("smtp_user", "").strip().lower()
        smtp_pass = body.get("smtp_pass", "").strip()
        disp = body.get("display_name", "")
        db.add_alias(alias, smtp_user, smtp_pass, display_name=disp, source="manual")
        return {"success": True, "created": alias}
    else:
        email = body.get("email", "").strip().lower()
        password = body.get("app_password", "").strip()
        limit = int(body.get("daily_limit", 50))
        db.add_account(email, password, daily_limit=limit)
        return {"success": True, "created": email}


@app.delete("/api/accounts/{account_id}")
async def delete_account_by_id(account_id: int):
    """Deletes an account from fleet."""
    db.remove_account(account_id)
    return {"success": True, "deleted_id": account_id}


@app.post("/api/accounts/cloudflare")
async def add_cf_sending_account(request: Request):
    """Adds a Cloudflare Email Sending account ($5/mo Workers Paid plan)."""
    b = await request.json()
    from_email = b.get("from_email", "").strip().lower()
    daily_limit = int(b.get("daily_limit", 100))
    label = b.get("label") or "Cloudflare Native API"
    if not from_email:
        raise HTTPException(status_code=400, detail="from_email is required")
    ok = db.add_cloudflare_sending_account(from_email, daily_limit=daily_limit, label=label)
    return {"success": ok, "account": from_email, "provider": "cloudflare_api"}


@app.post("/api/accounts/amazon-ses")
async def add_ses_sending_account(request: Request):
    """Adds an Amazon SES SMTP sending account."""
    b = await request.json()
    from_email = b.get("from_email", "").strip().lower()
    smtp_user = b.get("smtp_user", "").strip()
    smtp_pass = b.get("smtp_pass", "").strip()
    smtp_host = b.get("smtp_host") or config.AWS_SES_SMTP_HOST
    smtp_port = int(b.get("smtp_port") or 587)
    daily_limit = int(b.get("daily_limit", 200))
    label = b.get("label") or "Amazon SES"

    if not from_email or not smtp_user or not smtp_pass:
        raise HTTPException(status_code=400, detail="from_email, smtp_user, and smtp_pass are required")

    ok = db.add_amazon_ses_account(
        from_email=from_email,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        daily_limit=daily_limit,
        label=label
    )
    return {"success": ok, "account": from_email, "provider": "amazon_ses"}


@app.post("/api/accounts/test")
async def test_account_creds(request: Request):
    """Tests authentication for an account."""
    body = await request.json()
    email = body.get("email")
    pwd = body.get("password")
    host = body.get("smtp_host") or "smtp.gmail.com"
    port = int(body.get("smtp_port") or 587)
    res = email_sender.test_account_connection(email, pwd, smtp_host=host, smtp_port=port)
    return res


# ── Inbound Email Webhook (Cloudflare Routing Worker) ──────────
@app.post("/api/webhooks/inbound")
async def inbound_email_webhook(request: Request):
    """
    Receives incoming emails forwarded by the Cloudflare Email Routing Worker.
    Validates secret, updates lead status, runs AI intent classification,
    generates suggested reply draft, and pushes instant alert to Telegram.
    """
    secret = request.headers.get("x-webhook-secret", "")
    expected_secret = config.INBOUND_WEBHOOK_SECRET or db.get_setting("inbound_webhook_secret", "flinza_cf_inbound_secret_2026")

    if expected_secret and secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    body = await request.json()
    from_email = body.get("from", "").strip()
    to_email   = body.get("to", "").strip()
    subject    = body.get("subject", "")
    content    = body.get("body", "")

    if not from_email:
        raise HTTPException(status_code=400, detail="Missing 'from' email address")

    # 1. Log inbound reply to database
    reply_id, lead = db.log_inbound_webhook_reply(
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body=content
    )

    if not reply_id:
        return {"status": "ignored_duplicate", "from": from_email}

    # 2. AI Intent Classification & Draft Generation
    import email_toolkit
    intent_data = email_toolkit.classify_reply_intent(subject, content)
    intent = intent_data.get("intent", "general_reply")
    sentiment = intent_data.get("sentiment", "neutral")
    is_unsub = intent_data.get("is_unsubscribe", False)

    if is_unsub:
        db.handle_unsubscribe(from_email, reason="inbound_reply_unsubscribe")

    draft_body = ""
    draft_subj = f"Re: {subject}"
    if not is_unsub:
        try:
            instruction_hint = f"Lead intent is {intent}. {intent_data.get('suggested_action', '')}"
            conversation = db.get_conversation(lead["id"])
            draft = ai_router.generate_reply_draft(
                lead_info=dict(lead),
                conversation=conversation,
                their_reply=content,
                instruction=instruction_hint
            )
            draft_body = draft.get("body", "")
            draft_subj = draft.get("subject", draft_subj)
        except Exception as e:
            logger.error(f"Error generating AI reply draft for {reply_id}: {e}")

    db.update_reply_draft(reply_id, draft_subj, draft_body)
    conn = db.get_db()
    conn.execute("UPDATE replies SET intent=?, sentiment=? WHERE id=?", (intent, sentiment, reply_id))
    conn.commit()
    conn.close()

    # 3. Trigger instant Telegram Push Notification
    try:
        import bot
        bot.notify_telegram({
            "type": "inbound_reply",
            "reply_id": reply_id,
            "lead_id": lead.get("id"),
            "lead_name": lead.get("name") or "Lead",
            "from_email": from_email,
            "to_email": to_email,
            "subject": subject,
            "body": content,
            "ai_draft_body": draft_body,
            "intent": intent,
            "is_unsubscribe": (intent == "unsubscribe")
        })
    except Exception as e:
        logger.warning(f"Telegram notification error: {e}")

    return {
        "success": True,
        "reply_id": reply_id,
        "lead_id": lead.get("id"),
        "intent": intent
    }


# ── Cloudflare Studio Endpoints ────────────────────────────────
@app.get("/api/cloudflare/zones")
async def get_cf_zones():
    """Discovers all active zones on the user's Cloudflare account."""
    zones = cloudflare_aliases.list_user_zones()
    current_domain = db.get_setting("cf_domain") or config.CF_DOMAIN
    return {"success": True, "zones": zones, "current_domain": current_domain}


@app.post("/api/cloudflare/audit")
async def audit_dns(request: Request):
    """Deep DNS audit for SPF, DKIM, DMARC, and MX records."""
    body = await request.json()
    domain = body.get("domain") or db.get_setting("cf_domain") or config.CF_DOMAIN
    if not domain:
        raise HTTPException(status_code=400, detail="Domain name is required")
    res = cloudflare_aliases.audit_domain_dns(domain)
    return {"success": True, "audit": res}


@app.post("/api/cloudflare/generate")
async def generate_cf_aliases(request: Request):
    """Auto-generates 5 agency aliases and binds them to master Gmail."""
    body = await request.json()
    master = body.get("master_email")
    if not master:
        accs = db.get_all_accounts()
        if not accs:
            raise HTTPException(status_code=400, detail="Add at least one master Gmail account first")
        master = accs[0]["email"]

    count = int(body.get("count", 5))
    created = cloudflare_aliases.create_multiple_aliases(master, count=count)
    return {"success": True, "created": created}


# ── Campaign Sequences Endpoints ──────────────────────────────
@app.get("/api/sequences")
async def get_sequences(campaign_id: int = 1):
    """Returns sequence steps for campaign."""
    steps = db.get_campaign_sequences(campaign_id)
    return {"success": True, "steps": steps}


@app.post("/api/sequences")
async def save_sequence(request: Request):
    """Creates a sequence step."""
    body = await request.json()
    sid = db.save_sequence_step(
        campaign_id=int(body.get("campaign_id", 1)),
        step_number=int(body.get("step_number", 1)),
        delay_days=int(body.get("delay_days", 3)),
        condition_type=body.get("condition_type", "always"),
        subject_a=body.get("subject_a", ""),
        body_a=body.get("body_a", ""),
        subject_b=body.get("subject_b"),
        body_b=body.get("body_b"),
    )
    return {"success": True, "sequence_id": sid}


@app.delete("/api/sequences/{sequence_id}")
async def delete_sequence(sequence_id: int):
    """Deletes a sequence step."""
    db.delete_sequence_step(sequence_id)
    return {"success": True, "deleted_id": sequence_id}


# ── Unibox (Unified Inbox) Endpoints ──────────────────────────
@app.get("/api/unibox")
async def get_unibox_replies():
    """Returns all unhandled incoming replies with AI drafts."""
    replies = db.get_unhandled_replies()
    return {"success": True, "replies": replies}


@app.post("/api/unibox/reply")
async def send_unibox_reply(request: Request):
    """Dispatches reply draft to lead."""
    body = await request.json()
    reply_id = int(body.get("reply_id"))
    custom_text = body.get("body")
    conn = db.get_db()
    rep = conn.execute("SELECT * FROM replies WHERE id=?", (reply_id,)).fetchone()
    conn.close()

    if not rep:
        raise HTTPException(status_code=404, detail="Reply not found")

    text_to_send = custom_text or rep["ai_draft_body"]
    lead = db.get_lead(rep["lead_id"]) if rep["lead_id"] else None
    subj = f"Re: {rep['subject']}" if not rep["subject"].lower().startswith("re:") else rep["subject"]

    res = email_sender.send_with_logging(
        lead_id=rep["lead_id"],
        to_email=rep["from_email"],
        subject=subj,
        body=text_to_send,
        message_type="negotiation_reply",
    )
    if res.get("success"):
        db.mark_reply_handled(reply_id)
        return {"success": True, "result": res}
    return {"success": False, "error": res.get("error")}


@app.post("/api/unibox/check")
async def poll_inboxes():
    """Triggers immediate check of all inboxes for replies in background."""
    def _do_poll():
        try:
            reply_watcher.check_now()
        except Exception as e:
            logger.error(f"Background inbox check error: {e}")
    threading.Thread(target=_do_poll, daemon=True).start()
    return {"success": True, "message": "Reply sync started in background"}


# ── Webmail & Priority Inbox Endpoints (Mailflare Style) ──────
@app.get("/api/webmail/threads")
async def get_webmail_threads(folder: str = "inbox", search: Optional[str] = None):
    """
    Returns threads for the Mailflare Webmail UI:
    folder: inbox | sent | drafts | spam | trash
    """
    conn = db.get_db()
    threads = []

    # Counts
    inbox_cnt = conn.execute("SELECT COUNT(*) as c FROM replies WHERE handled=0").fetchone()["c"]
    drafts_cnt = conn.execute("SELECT COUNT(*) as c FROM replies WHERE handled=0 AND ai_draft_body IS NOT NULL").fetchone()["c"]
    sent_cnt = conn.execute("SELECT COUNT(*) as c FROM emails_sent WHERE status='sent'").fetchone()["c"]
    spam_cnt = conn.execute("SELECT COUNT(*) as c FROM blacklist").fetchone()["c"]

    if folder == "inbox":
        query = """
            SELECT r.id, r.from_email as sender, 'me' as recipient, r.subject, r.body,
                   r.received_at as timestamp, r.sentiment, r.intent, r.ai_draft_subject, r.ai_draft_body,
                   r.handled, l.name as lead_name, l.company as lead_company
            FROM replies r
            LEFT JOIN leads l ON r.lead_id = l.id
            WHERE r.handled = 0
        """
        params = []
        if search:
            query += " AND (r.from_email LIKE ? OR r.subject LIKE ? OR r.body LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])
        query += " ORDER BY r.received_at DESC LIMIT 50"
        rows = conn.execute(query, params).fetchall()
        for r in rows:
            intent = r["intent"] or "Inbound"
            tag = "Inbound"
            if intent in ("interested", "rate_inquiry"):
                tag = "Interested"
            elif intent == "unsubscribe":
                tag = "Opt-Out"
            threads.append({
                "id": r["id"],
                "type": "inbound",
                "sender": r["sender"],
                "recipient": "Flinza Inbox",
                "subject": r["subject"] or "(No Subject)",
                "snippet": (r["body"] or "").replace("\n", " ")[:140],
                "body": r["body"] or "",
                "ai_draft_subject": r["ai_draft_subject"],
                "ai_draft_body": r["ai_draft_body"],
                "timestamp": r["timestamp"],
                "tag": tag,
                "unread": True,
                "lead_name": r["lead_name"],
                "lead_company": r["lead_company"]
            })
    elif folder == "sent":
        query = """
            SELECT e.id, e.from_account as sender, e.to_email as recipient, e.subject, e.body,
                   e.sent_at as timestamp, e.status, COALESCE(t.open_count, 0) as open_count, COALESCE(t.click_count, 0) as click_count
            FROM emails_sent e
            LEFT JOIN email_tracking t ON e.id = t.email_id
            WHERE e.status = 'sent'
        """
        params = []
        if search:
            query += " AND (e.to_email LIKE ? OR e.subject LIKE ? OR e.body LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])
        query += " ORDER BY e.sent_at DESC LIMIT 50"
        rows = conn.execute(query, params).fetchall()
        for r in rows:
            tag = "Sent"
            if (r["click_count"] or 0) > 0:
                tag = "Clicked"
            elif (r["open_count"] or 0) > 0:
                tag = "Opened"
            threads.append({
                "id": r["id"],
                "type": "outbound",
                "sender": r["sender"] or "Outreach Bot",
                "recipient": r["recipient"],
                "subject": r["subject"] or "(No Subject)",
                "snippet": (r["body"] or "").replace("\n", " ")[:140],
                "body": r["body"] or "",
                "timestamp": r["timestamp"],
                "tag": tag,
                "unread": False
            })
    elif folder == "drafts":
        query = """
            SELECT r.id, r.from_email as sender, r.subject, r.ai_draft_body as body,
                   r.received_at as timestamp
            FROM replies r
            WHERE r.handled = 0 AND r.ai_draft_body IS NOT NULL
        """
        params = []
        if search:
            query += " AND (r.from_email LIKE ? OR r.subject LIKE ? OR r.ai_draft_body LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])
        query += " ORDER BY r.received_at DESC LIMIT 50"
        rows = conn.execute(query, params).fetchall()
        for r in rows:
            threads.append({
                "id": r["id"],
                "type": "draft",
                "sender": "AI Draft",
                "recipient": r["sender"],
                "subject": f"Re: {r['subject'] or ''}",
                "snippet": (r["body"] or "").replace("\n", " ")[:140],
                "body": r["body"] or "",
                "timestamp": r["timestamp"],
                "tag": "AI Draft",
                "unread": False
            })
    elif folder == "spam":
        rows = conn.execute("SELECT id, email, domain, reason, added_at as timestamp FROM blacklist ORDER BY added_at DESC LIMIT 50").fetchall()
        for r in rows:
            threads.append({
                "id": r["id"],
                "type": "spam",
                "sender": r["email"] or r["domain"] or "Blacklisted",
                "recipient": "Flinza",
                "subject": f"Suppressed / Blacklisted: {r['reason'] or 'Manual'}",
                "snippet": f"Reason: {r['reason']} | Added: {r['timestamp']}",
                "body": f"Address {r['email']} suppressed due to: {r['reason']}",
                "timestamp": r["timestamp"],
                "tag": "Spam",
                "unread": False
            })

    conn.close()
    return {
        "success": True,
        "folder": folder,
        "counts": {
            "inbox": inbox_cnt,
            "drafts": drafts_cnt,
            "sent": sent_cnt,
            "spam": spam_cnt
        },
        "threads": threads
    }


@app.post("/api/webmail/compose")
async def compose_and_send_email(request: Request):
    """Dispatches an email composed directly from Webmail."""
    b = await request.json()
    from_account = b.get("from_account")
    to_email = b.get("to_email", "").strip()
    subject = b.get("subject", "").strip()
    body = b.get("body", "").strip()

    if not to_email or not body:
        raise HTTPException(status_code=400, detail="to_email and body are required")

    lead = db.get_lead_by_email(to_email)
    lead_id = lead["id"] if lead else db.add_lead(email=to_email, name=to_email.split("@")[0].title())

    res = email_sender.send_with_logging(
        lead_id=lead_id,
        to_email=to_email,
        subject=subject or "Hello",
        body=body,
        message_type="manual_webmail"
    )
    return res


# ── Aliases & Routing Management Endpoints ────────────────────
@app.get("/api/aliases/routing")
async def get_aliases_routing():
    """Returns all aliases with their routing configuration."""
    aliases = db.get_all_aliases()
    accounts = db.get_all_accounts()
    acc_map = {a["email"]: dict(a) for a in accounts}

    result = []
    for al in aliases:
        d = dict(al)
        master = acc_map.get(d.get("smtp_user"))
        d["master_status"] = "Active" if master and master.get("active") else ("Standalone" if d.get("routing_mode") in ("cloudflare_api", "external_smtp") else "Inactive")
        d["routing_mode"] = d.get("routing_mode") or "gmail_send_as"
        result.append(d)

    return {"success": True, "aliases": [mask_credentials(d) for d in result], "accounts": [mask_credentials(dict(a)) for a in accounts]}


@app.get("/api/aliases/saved-defaults")
async def get_alias_saved_defaults(domain: Optional[str] = Query(None)):
    """Returns remembered SES, Namecheap, and SMTP settings for a domain or globally."""
    res = {
        "ses": {
            "smtp_host": db.get_setting(f"ses_host_{domain}", "") if domain else "",
            "smtp_port": db.get_setting(f"ses_port_{domain}", "") if domain else "",
            "smtp_user": db.get_setting(f"ses_user_{domain}", "") if domain else "",
            "smtp_pass": db.get_setting(f"ses_pass_{domain}", "") if domain else "",
        },
        "namecheap": {
            "smtp_host": db.get_setting(f"namecheap_host_{domain}", "mail.privateemail.com") if domain else "mail.privateemail.com",
            "smtp_port": db.get_setting(f"namecheap_port_{domain}", "465") if domain else "465",
            "smtp_user": "",
            "smtp_pass": "",
        }
    }
    # Fallback to global defaults if domain-specific are empty
    if not res["ses"]["smtp_host"]:
        res["ses"]["smtp_host"] = db.get_setting("default_ses_host", "email-smtp.us-east-1.amazonaws.com")
        res["ses"]["smtp_port"] = db.get_setting("default_ses_port", "587")
        res["ses"]["smtp_user"] = db.get_setting("default_ses_user", "")
        res["ses"]["smtp_pass"] = db.get_setting("default_ses_pass", "")
    return {"success": True, "domain": domain, "defaults": res}


@app.post("/api/aliases/create")
async def create_alias_with_routing(request: Request):
    """Creates a custom domain alias with explicit routing mode and optional remembered settings."""
    b = await request.json()
    alias = b.get("alias", "").strip().lower()
    routing_mode = b.get("routing_mode", "gmail_send_as")
    smtp_user = b.get("smtp_user", "").strip().lower()
    disp = b.get("display_name", "")
    daily_limit = int(b.get("daily_limit", 20))
    smtp_host = b.get("smtp_host")
    smtp_port = int(b.get("smtp_port")) if b.get("smtp_port") else None
    custom_smtp_user = b.get("custom_smtp_user")
    custom_smtp_pass = b.get("custom_smtp_pass")
    forward_to = b.get("forward_to")
    remember_settings = b.get("remember_settings", False)

    if not alias:
        raise HTTPException(status_code=400, detail="Alias is required")

    domain = alias.split("@")[1] if "@" in alias else ""

    # Remember settings if requested by user
    if remember_settings and domain:
        if routing_mode in ("external_smtp", "amazon_ses"):
            if smtp_host:
                db.set_setting(f"ses_host_{domain}", smtp_host)
                db.set_setting("default_ses_host", smtp_host)
            if smtp_port:
                db.set_setting(f"ses_port_{domain}", str(smtp_port))
                db.set_setting("default_ses_port", str(smtp_port))
            if custom_smtp_user:
                db.set_setting(f"ses_user_{domain}", custom_smtp_user)
                db.set_setting("default_ses_user", custom_smtp_user)
            if custom_smtp_pass:
                db.set_setting(f"ses_pass_{domain}", custom_smtp_pass)
                db.set_setting("default_ses_pass", custom_smtp_pass)

        elif routing_mode == "namecheap_smtp":
            if smtp_host:
                db.set_setting(f"namecheap_host_{domain}", smtp_host)
            if smtp_port:
                db.set_setting(f"namecheap_port_{domain}", str(smtp_port))

    ok = db.add_alias(
        alias=alias,
        smtp_user=smtp_user or alias,
        display_name=disp,
        daily_limit=daily_limit,
        routing_mode=routing_mode,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        custom_smtp_user=custom_smtp_user,
        custom_smtp_pass=custom_smtp_pass,
        forward_to=forward_to,
        source="studio_routing"
    )
    return {"success": ok, "alias": alias, "routing_mode": routing_mode, "domain": domain}


@app.post("/api/aliases/update-routing")
async def update_alias_routing_api(request: Request):
    """Updates routing configuration for an alias."""
    b = await request.json()
    alias = b.get("alias")
    mode = b.get("routing_mode")
    if not alias or not mode:
        raise HTTPException(status_code=400, detail="alias and routing_mode required")

    db.update_alias_routing(
        alias=alias,
        routing_mode=mode,
        smtp_user=b.get("smtp_user"),
        smtp_host=b.get("smtp_host"),
        smtp_port=int(b.get("smtp_port")) if b.get("smtp_port") else None,
        custom_smtp_user=b.get("custom_smtp_user"),
        custom_smtp_pass=b.get("custom_smtp_pass"),
        forward_to=b.get("forward_to"),
    )
    return {"success": True, "alias": alias, "updated_routing_mode": mode}


@app.post("/api/aliases/test-route")
async def test_alias_route(request: Request):
    """Sends a test email specifically from this alias using its configured route."""
    b = await request.json()
    alias = b.get("alias")
    to_email = b.get("to_email", "rajdep.f12x@gmail.com")
    res = email_sender.send_test_email(to_email=to_email, target_account=alias)
    return res


# ── Custom API Endpoints ──────────────────────────────────────
@app.get("/api/endpoints")
async def list_endpoints():
    """Lists all custom OpenAI-compatible endpoints."""
    eps = db.get_custom_endpoints(active_only=False)
    return {"success": True, "endpoints": eps}


@app.post("/api/endpoints")
async def add_endpoint(request: Request):
    """Adds a custom LLM endpoint (Ollama, vLLM, DeepSeek, LocalAI, etc.)."""
    b = await request.json()
    eid = db.add_custom_endpoint(
        name=b.get("name"),
        base_url=b.get("base_url"),
        model_name=b.get("model_name"),
        api_key=b.get("api_key"),
        provider_type=b.get("provider_type", "openai_compatible"),
        temperature=float(b.get("temperature", 0.85)),
        max_tokens=int(b.get("max_tokens", 2048)),
    )
    return {"success": True, "endpoint_id": eid}


@app.delete("/api/endpoints/{endpoint_id}")
async def delete_endpoint(endpoint_id: int):
    """Deletes custom endpoint."""
    db.delete_custom_endpoint(endpoint_id)
    return {"success": True, "deleted_id": endpoint_id}


@app.post("/api/endpoints/{endpoint_id}/test")
async def test_endpoint(endpoint_id: int):
    """Pings custom endpoint with a probe prompt to verify latency."""
    res = ai_router.test_custom_endpoint(endpoint_id)
    return res


# ── Queue & Campaign Controls ─────────────────────────────────
@app.post("/api/queue/start")
async def start_queue_api():
    """Starts background email sending queue."""
    msg = email_queue.start_queue()
    return {"success": True, "message": msg}


@app.post("/api/queue/pause")
async def pause_queue_api():
    """Pauses or resumes queue."""
    if email_queue.is_paused():
        msg = email_queue.resume_queue()
    else:
        msg = email_queue.pause_queue()
    return {"success": True, "message": msg}


@app.post("/api/queue/stop")
async def stop_queue_api():
    """Stops sending queue."""
    msg = email_queue.stop_queue()
    return {"success": True, "message": msg}


@app.post("/api/testsend")
async def trigger_testsend(request: Request):
    """Sends a live test email with delivery diagnostics."""
    b = await request.json()
    to_email = b.get("to_email", "rajdep.f12x@gmail.com")
    account_email = b.get("account_email")
    res = email_sender.send_test_email(to_email, target_account=account_email)
    return res


# ── Campaign Control Routes (aliases for JS compatibility) ────────
@app.post("/api/campaign/testsend")
async def campaign_testsend(request: Request):
    """Alias: Sends a live test email (JS-compatible route)."""
    b = await request.json()
    to_email = b.get("to_email", "rajdep.f12x@gmail.com")
    account_email = b.get("account_email")
    import time
    start = time.time()
    res = email_sender.send_test_email(to_email, target_account=account_email)
    res["elapsed_ms"] = round((time.time() - start) * 1000)
    return res


@app.post("/api/campaign/launch")
async def campaign_launch(request: Request, background_tasks: BackgroundTasks):
    """Launches outreach campaign for all uncontacted leads."""
    b = await request.json()
    dry_run = b.get("dry_run", False)
    campaign_id = int(b.get("campaign_id", 1))
    result = outreach_engine.launch_campaign(campaign_id=campaign_id, dry_run=dry_run)
    if result.get("success") and result.get("queued_count", 0) > 0 and not dry_run:
        background_tasks.add_task(email_queue.start_queue)
    return result


@app.post("/api/campaign/pause")
async def campaign_pause():
    """Pauses the sending queue."""
    msg = email_queue.pause_queue()
    return {"success": True, "message": msg, "queue_status": "paused"}


@app.post("/api/campaign/resume")
async def campaign_resume():
    """Resumes the sending queue."""
    msg = email_queue.resume_queue()
    return {"success": True, "message": msg, "queue_status": "running"}


@app.get("/api/campaign/status")
async def campaign_status():
    """Returns live queue status, running state, and queued count."""
    is_running = email_queue.is_running()
    is_paused  = email_queue.is_paused()
    stats = db.get_stats()
    return {
        "success": True,
        "queue_status": "paused" if is_paused else ("running" if is_running else "idle"),
        "is_running": is_running,
        "is_paused": is_paused,
        "queued_count": stats.get("queued_count", 0),
        "sent_today": stats.get("sent_today", 0),
    }


# ── Warmup & Account Health ───────────────────────────────────────
@app.get("/api/warmup/stats")
async def warmup_stats():
    """Returns warmup health stats for all accounts."""
    stats = outreach_engine.get_account_warmup_stats()
    return {"success": True, "accounts": [mask_credentials(s) for s in stats]}


@app.post("/api/warmup/audit")
async def warmup_audit():
    """Scans accounts and auto-pauses those exceeding bounce/spam thresholds."""
    paused = outreach_engine.check_and_auto_pause_unhealthy_accounts()
    return {"success": True, "auto_paused": paused, "count": len(paused)}


# ── Deliverability Score ──────────────────────────────────────────
@app.post("/api/score")
async def deliverability_score(request: Request):
    """Scores an email subject + body for deliverability (0-100)."""
    b = await request.json()
    subject = b.get("subject", "")
    body = b.get("body", "")
    result = outreach_engine.score_email_deliverability(subject, body)
    return {"success": True, **result}


# ── A/B Spintax Preview ───────────────────────────────────────────
@app.post("/api/spintax/preview")
async def spintax_preview(request: Request):
    """Generates N resolved variants with lead personalization and entropy metrics."""
    b = await request.json()
    text = b.get("text", "")
    count = min(int(b.get("count", 5)), 10)
    mock_lead = b.get("mock_lead")
    result = outreach_engine.preview_spin_variants(text, count=count, mock_lead=mock_lead)
    return {"success": True, **result}


# ── Mailbox Pool Status ───────────────────────────────────────────
@app.get("/api/pool/status")
async def get_mailbox_pool_status():
    """Returns live fleet status, daily capacity, and active cooldowns."""
    return {"success": True, **outreach_engine.mailbox_pool.get_pool_status()}


# ── Zero-Bounce Lead Verification ─────────────────────────────────
@app.post("/api/leads/verify-all")
async def verify_all_leads():
    """Runs Zero-Bounce lead cleaning on all uncontacted leads."""
    leads = db.get_leads(stage="new", limit=500)
    if not leads:
        return {"success": True, "message": "No new leads to verify", "scanned": 0, "deliverable": 0, "dead_bounced": 0}
    result = email_verifier.clean_lead_batch(leads)
    for dead in result["undeliverable"]:
        db.update_lead_stage(dead["lead_id"], "bounced")
        db.add_to_blacklist(dead["email"], reason=f"Zero-Bounce audit: {dead['reason']}")
    return {
        "success": True,
        "scanned": result["total"],
        "deliverable": result["clean_count"],
        "dead_bounced": result["dead_count"],
        "dead_leads": [{"email": d["email"], "reason": d["reason"]} for d in result["undeliverable"]]
    }


# ── Open & Click Tracking Endpoints ───────────────────────────────
@app.get("/t/o/{token}")
@app.get("/t/o/{token}.png")
async def track_email_open(token: str, request: Request):
    """Invisible 1x1 transparent tracking pixel handler for email opens."""
    clean_token = token.replace(".png", "")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")
    img_bytes = tracking_server.handle_open(clean_token, user_agent=ua, ip=ip)
    return Response(content=img_bytes, media_type="image/png", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    })


@app.get("/t/c/{token}")
async def track_email_click(token: str, target: Optional[str] = Query(None), request: Request = None):
    """Redirect handler for tracking link clicks."""
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent", "") if request else ""
    dest = tracking_server.handle_click(token, target, user_agent=ua, ip=ip)
    return RedirectResponse(url=dest or target or "https://google.com")


# ── Luxury HTML Signature & Stealth Disguise Endpoints ───────────
@app.get("/api/signature")
async def get_signature():
    """Returns current HTML signature settings and rendered live preview."""
    cfg = signature_generator.get_signature_settings()
    html_preview = signature_generator.generate_glassmorphic_signature_html()
    return {"success": True, "settings": cfg, "preview_html": html_preview}


@app.post("/api/signature")
async def save_signature(request: Request):
    """Saves updated HTML signature configuration."""
    data = await request.json()
    signature_generator.save_signature_settings(data)
    preview = signature_generator.generate_glassmorphic_signature_html()
    return {"success": True, "settings": signature_generator.get_signature_settings(), "preview_html": preview}


@app.post("/api/signature/test-preview")
async def send_signature_test_preview(request: Request):
    """Sends a sample cold outreach email containing the live Glassmorphic signature to the user's test address."""
    b = await request.json()
    to_email = b.get("to_email", "rajdep.f12x@gmail.com")

    # Pick an active account
    accounts = db.get_active_accounts()
    if not accounts:
        raise HTTPException(status_code=400, detail="No active mailboxes configured to send preview.")

    acc = dict(accounts[0])
    sub = "⚡ [Live Preview] Flinza Executive Bulletin & Signature Demo"
    sample_body = (
        "Hey Alex,\n\n"
        "Here is the live demonstration of our executive marketing bulletin layout with the new Glassmorphic HTML signature attached below.\n\n"
        "Notice the high-deliverability headers (Feedback-ID, List-Unsubscribe, X-Precedence) and the rounded action button styled for 100% email client fidelity.\n\n"
        "— Flinza Engine"
    )
    res = email_sender.send_test_email(to_email, acc)
    return {"success": res.get("success", False), "result": res}


# ── Sent Emails History & Outbound Log ───────────────────────────
@app.get("/api/history")
async def get_history(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = "all",
    search: Optional[str] = None,
    from_account: Optional[str] = None
):
    """Returns outbound email dispatch history with sender, timestamp, and tracking metrics."""
    result = db.get_sent_emails_history(
        limit=min(limit, 200),
        offset=offset,
        status=status,
        search=search,
        from_account=from_account
    )
    return {"success": True, **result}


@app.get("/api/history/{email_id}")
async def get_history_detail(email_id: int):
    """Returns the full email content, headers, and transmission log for a sent email."""
    detail = db.get_sent_email_detail(email_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Email record not found")
    return {"success": True, "email": detail}


# ── 1-Click Unsubscribe Handler (RFC 8058 Compliant) ──────────────
@app.get("/u/{token}")
@app.post("/u/{token}")
async def one_click_unsubscribe(token: str, email: Optional[str] = Query(None)):
    """Google & Yahoo RFC 8058 compliant 1-click unsubscribe handler (token or email lookup)."""
    unsub_email = email
    if not unsub_email:
        lead = db.get_lead_by_unsub_token(token)
        if lead:
            unsub_email = lead.get("email")
            db.update_lead_stage(lead["id"], "opted_out")

    if unsub_email:
        lead_record = db.get_lead_by_email(unsub_email)
        if lead_record:
            db.update_lead_stage(lead_record["id"], "opted_out")
        db.add_to_blacklist(unsub_email, reason="1-Click Unsubscribe link")

    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Unsubscribed — Flinza</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #08090f; color: #fff; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #111219; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 40px; max-width: 440px; text-align: center; box-shadow: 0 20px 50px rgba(0,0,0,0.5); }
        h2 { color: #7ECECE; margin-top: 0; }
        p { color: #8b949e; line-height: 1.6; font-size: 14px; }
      </style>
    </head>
    <body>
      <div class="card">
        <h2>✓ Unsubscribed</h2>
        <p>You have been successfully removed from our outreach list. You will not receive any further automated emails.</p>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ── Reply Intent Classification ───────────────────────────────────
@app.post("/api/reply/classify")
async def classify_reply(request: Request):
    """Classifies a reply body for intent and generates an AI draft reply."""
    b = await request.json()
    body = b.get("body", "")
    subject = b.get("subject", "")
    lead_id = b.get("lead_id")
    lead = None
    if lead_id:
        lead = db.get_lead_by_id(lead_id)
        lead = dict(lead) if lead else None
    result = outreach_engine.ai_classify_reply_and_draft(body, subject, lead=lead)
    return {"success": True, **result}


# ── Terminal Command Runner ───────────────────────────────────────
@app.post("/api/terminal")
async def run_terminal_command(request: Request):
    """Executes a text terminal command and returns output (used by Terminal tab)."""
    b = await request.json()
    command = b.get("command", "").strip()
    if not command:
        return {"success": False, "output": "Empty command"}
    result = outreach_engine.dispatch_terminal_command(command)
    return result


@app.get("/api/terminal/help")
async def terminal_help():
    """Returns list of all available terminal commands."""
    cmds = sorted(outreach_engine.COMMAND_REGISTRY.keys())
    return {"success": True, "commands": cmds}


# ── Smartlead Webhook ─────────────────────────────────────────────
@app.post("/webhook/smartlead")
async def smartlead_webhook(request: Request):
    """Ingests Smartlead reply/open/bounce webhook events."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    result = outreach_engine.ingest_smartlead_webhook(payload)
    return result


# ── SMTP Verification ─────────────────────────────────────────────
@app.post("/api/smtp/verify")
async def smtp_verify(request: Request):
    """Tests SMTP credentials without sending. Returns latency + auth result."""
    b = await request.json()
    result = outreach_engine.verify_smtp_connection(
        smtp_host=b.get("smtp_host", "smtp.gmail.com"),
        smtp_port=int(b.get("smtp_port", 587)),
        smtp_user=b.get("smtp_user", ""),
        smtp_pass=b.get("smtp_pass", ""),
    )
    return result





# ── Analytics Endpoints ───────────────────────────────────────────
@app.get("/api/analytics")
async def get_analytics():
    """Returns detailed analytics: per-account stats, hourly send distribution, reply funnel."""
    try:
        stats     = db.get_stats()
        tracking  = db.get_tracking_stats()
        pipeline  = db.get_pipeline_breakdown()
        warmup    = outreach_engine.get_account_warmup_stats()
        return {
            "success": True,
            "stats": stats,
            "tracking": tracking,
            "pipeline": pipeline,
            "warmup": warmup,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Webmail Compose Alias ─────────────────────────────────────────
@app.post("/api/webmail/compose")
async def webmail_compose(request: Request):
    """Sends an email from the compose modal using smart routing."""
    b = await request.json()
    from_account = b.get("from_account", "").strip()
    to_email     = b.get("to_email", "").strip()
    subject      = b.get("subject", "")
    body         = b.get("body", "")
    reply_to_id  = b.get("reply_to_id")  # optional thread stitching

    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=400, detail="Valid to_email required")

    # Pick account
    account = None
    if from_account:
        accs = db.get_all_accounts()
        for a in accs:
            if a["email"].lower() == from_account.lower():
                account = {
                    "id": a["email"], "type": "gmail",
                    "from_email": a["email"], "smtp_user": a["email"],
                    "smtp_pass": a.get("app_password"), "proxy_url": a.get("proxy_url"),
                    "display_name": a.get("label") or "",
                    "provider": a.get("provider") or "gmail",
                }
                break
        if not account:
            aliases = db.get_all_aliases()
            for al in aliases:
                if al["alias"].lower() == from_account.lower():
                    master_accs = db.get_all_accounts()
                    master = next((x for x in master_accs if x["email"] == al.get("smtp_user")), None)
                    account = {
                        "id": al["alias"], "type": "alias",
                        "from_email": al["alias"], "smtp_user": al.get("smtp_user") or al["alias"],
                        "smtp_pass": master["app_password"] if master else al.get("smtp_pass"),
                        "display_name": al.get("display_name") or "",
                        "routing_mode": al.get("routing_mode", "gmail_send_as"),
                        "provider": al.get("routing_mode", "gmail_send_as"),
                    }
                    break

    if not account:
        account = outreach_engine.pick_best_account(lead_email=to_email)

    if not account:
        raise HTTPException(status_code=400, detail="No sending account available. Connect a Gmail account first.")

    # Build reply headers if this is a reply
    extra_headers = {}
    if reply_to_id:
        thread = db.get_reply_thread(reply_to_id)
        if thread:
            extra_headers = outreach_engine.build_reply_headers(dict(thread))

    res = email_sender.send_email_now(
        to_email=to_email,
        subject=subject,
        body=body,
        account=account,
    )
    return res


# ── Settings ──────────────────────────────────────────────────
@app.get("/api/settings")
async def get_all_settings():
    """Fetches all system configuration settings."""
    conn = db.get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    settings_dict = {r["key"]: r["value"] for r in rows}
    return {"success": True, "settings": settings_dict}


@app.post("/api/settings")
async def save_settings(request: Request):
    """Updates system settings."""
    b = await request.json()
    for k, v in b.items():
        db.set_setting(k, str(v))
    return {"success": True, "message": "Settings saved successfully"}


# ── Server Runner ─────────────────────────────────────────────
def run_studio_server():
    """Launches the Studio web server."""
    port = int(db.get_setting("studio_port", "8000"))
    logger.info(f"Starting Flinza Studio Web Application on http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run_studio_server()
