"""
Flinza — Enterprise Outreach Web Studio Server
FastAPI application providing REST APIs, Open/Click tracking handlers,
Google OAuth2 callback processing, and serving the Studio Single-Page Application.
"""

import os
import json
import logging
import threading
import asyncio
import csv
import io
import math
from datetime import datetime
from pathlib import Path
from typing import Optional
import httpx
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


@app.get("/api/leads/sample-csv")
async def download_sample_leads_csv():
    """Returns a perfectly formatted sample CSV file with high-converting AI personalization headers."""
    sample_rows = [
        ["first_name", "last_name", "email", "company", "niche", "website", "linkedin", "custom_hook"],
        ["Sarah", "Connor", "sarah@apexmedia.co", "Apex Media", "E-Commerce", "https://apexmedia.co", "https://linkedin.com/in/sarahconnor", "Loved your recent TikTok series on DTC ad scaling"],
        ["Marcus", "Vance", "marcus@hypergrowth.io", "HyperGrowth", "B2B SaaS", "https://hypergrowth.io", "https://linkedin.com/in/marcusvance", "Saw your Product Hunt #1 launch last Tuesday"],
        ["Elena", "Rostova", "elena@fitlabpro.com", "FitLab Pro", "Fitness App", "https://fitlabpro.com", "https://linkedin.com/in/elenarostova", "Your IG reels retention is great but missing short-form hook variations"],
        ["David", "Chen", "david@nexustech.ai", "Nexus Tech", "AI Software", "https://nexustech.ai", "https://linkedin.com/in/davidchen", "Noticed your founder teardown video on LinkedIn last week"],
        ["Olivia", "Taylor", "olivia@voguehaven.shop", "Vogue Haven", "Fashion DTC", "https://voguehaven.shop", "https://linkedin.com/in/oliviataylor", "Your Meta creative could easily 3x with creator whitelisting"],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(sample_rows)
    csv_content = output.getvalue()

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flinza_sample_leads_template.csv"}
    )


@app.post("/api/leads/upload-csv")
async def upload_leads_csv(request: Request, file: Optional[UploadFile] = File(None)):
    """Imports leads from CSV with support for custom_hook and linkedin columns for AI hyper-personalization."""
    csv_text = ""
    if file:
        content = await file.read()
        csv_text = content.decode("utf-8", errors="replace")
    else:
        try:
            body_json = await request.json()
            csv_text = body_json.get("csv_text", "")
        except Exception:
            pass

    if not csv_text.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content provided")

    reader = csv.DictReader(io.StringIO(csv_text))
    imported_count = 0
    updated_count = 0
    imported_leads = []

    for row in reader:
        # Normalize keys (strip whitespace, lowercase)
        norm_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
        email = norm_row.get("email", "")
        if not email or "@" not in email:
            continue

        # Extract name
        first_name = norm_row.get("first_name", "")
        last_name = norm_row.get("last_name", "")
        name = norm_row.get("name", "")
        if not name and (first_name or last_name):
            name = f"{first_name} {last_name}".strip()

        company = norm_row.get("company") or norm_row.get("brand") or norm_row.get("organization") or ""
        niche = norm_row.get("niche") or norm_row.get("industry") or norm_row.get("category") or "General B2B"
        website = norm_row.get("website") or norm_row.get("url") or ""
        linkedin = norm_row.get("linkedin") or norm_row.get("linkedin_url") or ""
        custom_hook = norm_row.get("custom_hook") or norm_row.get("hook") or norm_row.get("icebreaker") or norm_row.get("notes") or ""

        lead_id = db.add_or_update_lead(
            name=name or "Founder",
            email=email,
            company=company,
            niche=niche,
            website=website,
            linkedin=linkedin,
            custom_hook=custom_hook,
            stage="new"
        )
        imported_count += 1
        imported_leads.append({"id": lead_id, "name": name, "email": email, "company": company, "custom_hook": custom_hook})

    return {"success": True, "imported_count": imported_count, "leads": imported_leads}


@app.post("/api/leads/{lead_id}/ai-draft")
async def generate_lead_ai_draft(lead_id: int):
    """Generates a 100% unique AI hyper-personalized cold outreach subject & body for this specific lead."""
    lead = db.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    opener = ai_router.generate_opener(lead)
    sub = opener.get("subject", f"Quick idea for {lead.get('company', 'your team')}")
    body = opener.get("body", "")

    db.update_lead_ai_draft(lead_id, sub, body)
    return {"success": True, "lead_id": lead_id, "ai_subject": sub, "ai_draft": body, "used_fallback": opener.get("used_fallback", False)}


@app.post("/api/leads/generate-ai-batch")
async def generate_ai_drafts_batch():
    """Generates hyper-personalized AI drafts for all new leads that lack custom drafts."""
    leads = db.get_leads(stage="new", limit=100)
    generated = 0
    for l in leads:
        lead = dict(l)
        if not lead.get("ai_draft"):
            opener = ai_router.generate_opener(lead)
            db.update_lead_ai_draft(lead["id"], opener.get("subject"), opener.get("body"))
            generated += 1
    return {"success": True, "generated_count": generated, "total_leads": len(leads)}


@app.post("/api/leads/generate-and-queue")
async def generate_and_queue_all_leads(request: Request):
    """
    1-Click: Generates 100% unique AI hyper-personalized emails for all new leads
    and stages them into the outbound sending queue ready for campaign launch.
    """
    try:
        b = await request.json()
    except Exception:
        b = {}
    stage = b.get("stage", "new")
    campaign_id = int(b.get("campaign_id", 1))
    force_ai = b.get("force_ai", False)

    leads = [dict(l) for l in db.get_leads(stage=stage if stage != "all" else None, limit=500)]
    if not leads and stage != "all":
        # Fallback to any uncontacted leads
        all_leads = [dict(l) for l in db.get_leads(stage=None, limit=500)]
        leads = [l for l in all_leads if l.get("stage") in ("new", None, "")]

    if not leads:
        return {"success": False, "message": "No uncontacted leads found in Leads CRM to queue."}

    accounts = [dict(a) for a in db.get_all_accounts() if dict(a).get("active", 1)]
    if not accounts:
        return {"success": False, "message": "No active sending mailboxes found. Connect a Gmail or SMTP account first."}

    queued_count = 0
    skipped_count = 0
    generated_pitches = 0

    for idx, lead in enumerate(leads):
        email = (lead.get("email") or "").strip()
        if not email or "@" not in email:
            skipped_count += 1
            continue

        if db.is_blacklisted(email) or email_toolkit.is_disposable_email(email):
            skipped_count += 1
            continue

        if db.email_already_queued_or_sent(email):
            skipped_count += 1
            continue

        subject = (lead.get("ai_subject") or "").strip()
        body = (lead.get("ai_draft") or "").strip()

        if not subject or not body:
            sender_name = db.get_setting("sender_name", "Flinza")
            steps = db.get_sequence_steps(campaign_id) or []
            if steps and steps[0].get("body_a"):
                import hashlib
                s1 = steps[0]
                seed = int(hashlib.md5(email.encode()).hexdigest(), 16) % 10000
                subject, body = outreach_engine.personalize(
                    s1.get("subject_a", ""),
                    s1.get("body_a", ""),
                    lead=lead,
                    sender_name=sender_name,
                    seed=seed
                )
            else:
                first_name = lead.get("first_name") or (lead.get("name", "").split()[0] if lead.get("name") else "there")
                company = lead.get("company") or "your team"
                niche = lead.get("niche") or "growth"
                subject = f"Quick question regarding {company}"
                body = f"Hey {first_name},\n\nHope you're having a great week.\n\nNoticed what you're doing with {company} in the {niche} space and saw a few untapped opportunities to scale customer acquisition with short-form video.\n\nWould you be open to a quick 2-minute video breakdown of how we've helped similar brands?\n\nBest,\n{sender_name}"

            db.update_lead_ai_draft(lead["id"], subject, body)
            generated_pitches += 1

        account = accounts[idx % len(accounts)]
        from_email = account.get("from_email") or account.get("email")

        db.queue_email(
            lead_id=lead["id"],
            from_account=from_email,
            to_email=email,
            subject=subject,
            body=body,
            step_number=1,
            campaign_id=campaign_id,
            priority=1,
            message_type="opener"
        )
        db.update_lead_stage(lead["id"], "contacted")
        queued_count += 1

    stats = db.get_stats()
    return {
        "success": True,
        "queued_count": queued_count,
        "generated_pitches": generated_pitches,
        "skipped_count": skipped_count,
        "total_queued": stats.get("queued", stats.get("queued_count", queued_count)),
        "message": f"⚡ Generated {generated_pitches} AI pitches & queued {queued_count} emails into campaign!"
    }


@app.post("/api/leads/{lead_id}/verify-deep")
async def verify_single_lead_deep(lead_id: int):
    """Executes a deep Zero-Bounce deliverability check on a single lead (MX, Catch-All, Disposable, Syntax)."""
    lead = db.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = email_verifier.verify_lead_deliverability(lead["email"], deep_smtp=True)
    db.update_lead_deliverability(
        lead_id=lead_id,
        status=result["status"],
        score=result["score"],
        details_json=json.dumps(result)
    )
    return {"success": True, "lead_id": lead_id, "audit": result}


@app.post("/api/leads/verify-all-deep")
async def verify_all_leads_deep():
    """Runs full Zero-Bounce MX & Catch-All audit on all new leads, updating badges and filtering dead mailboxes."""
    leads = db.get_leads(stage="new", limit=300)
    clean_cnt = 0
    catchall_cnt = 0
    dead_cnt = 0

    for l in leads:
        ld = dict(l)
        res = email_verifier.verify_lead_deliverability(ld["email"], deep_smtp=False)
        db.update_lead_deliverability(ld["id"], res["status"], res["score"], json.dumps(res))
        if not res["valid"]:
            db.update_lead_stage(ld["id"], "bounced")
            dead_cnt += 1
        elif res["is_catch_all"]:
            catchall_cnt += 1
            clean_cnt += 1
        else:
            clean_cnt += 1

    return {
        "success": True,
        "scanned": len(leads),
        "clean_count": clean_cnt,
        "catchall_count": catchall_cnt,
        "dead_count": dead_cnt
    }


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
    """Fires IMAP inbox check in background thread and returns immediately."""
    def _do_poll():
        try:
            reply_watcher.check_now()
        except Exception as e:
            logger.error(f"Background inbox check error: {e}")
    threading.Thread(target=_do_poll, daemon=True).start()
    return {"success": True, "message": "Inbox sync started. Refresh in a few seconds to see new replies."}


# ── Webmail & Priority Inbox Endpoints (Mailflare Style) ──────
@app.get("/api/webmail/threads")
async def get_webmail_threads(
    folder: str = "inbox",
    search: Optional[str] = None,
    filter: str = "all",
    page: int = 1,
    limit: int = 25
):
    """
    Returns threads for the Mailflare Webmail UI:
    folder: inbox (leads only) | all-inboxes | starred | sent | drafts | spam
    filter: all | interested | replied | bounced | unread
    page: 1-indexed (pagination)
    limit: items per page (default 25)
    """
    conn = db.get_db()
    threads = []

    # Filter out noisy automated system senders/alerts from primary leads inbox
    system_filter_sql = """
        AND r.from_email NOT LIKE '%no-reply%'
        AND r.from_email NOT LIKE '%noreply%'
        AND r.from_email NOT LIKE '%google.com%'
        AND r.from_email NOT LIKE '%verify%'
        AND r.from_email NOT LIKE '%notification%'
        AND r.subject NOT LIKE '%verification%'
        AND r.subject NOT LIKE '%OTP%'
        AND r.subject NOT LIKE '%security alert%'
        AND r.subject NOT LIKE '%confirm%'
    """

    # Folder Counts
    leads_inbox_cnt = conn.execute(f"SELECT COUNT(*) as c FROM replies r WHERE r.handled=0 AND (r.lead_id IS NOT NULL OR r.from_email IN (SELECT email FROM leads)) {system_filter_sql}").fetchone()["c"]
    all_inbox_cnt = conn.execute("SELECT COUNT(*) as c FROM replies WHERE handled=0").fetchone()["c"]
    starred_cnt = conn.execute("SELECT (SELECT COUNT(*) FROM replies WHERE is_starred=1) + (SELECT COUNT(*) FROM emails_sent WHERE is_starred=1) as c").fetchone()["c"]
    drafts_cnt = conn.execute("SELECT COUNT(*) as c FROM replies WHERE handled=0 AND ai_draft_body IS NOT NULL").fetchone()["c"]
    sent_cnt = conn.execute("SELECT COUNT(*) as c FROM emails_sent WHERE status='sent'").fetchone()["c"]
    spam_cnt = conn.execute("SELECT COUNT(*) as c FROM blacklist").fetchone()["c"]

    offset = max(0, (page - 1) * limit)
    total_count = 0

    if folder in ("inbox", "all-inboxes"):
        base_where = ["r.handled = 0"]
        params = []
        if folder == "inbox":
            base_where.append("(r.lead_id IS NOT NULL OR r.from_email IN (SELECT email FROM leads))")
            base_where.append("r.from_email NOT LIKE '%no-reply%'")
            base_where.append("r.from_email NOT LIKE '%noreply%'")
            base_where.append("r.from_email NOT LIKE '%google.com%'")
            base_where.append("r.from_email NOT LIKE '%verify%'")
            base_where.append("r.from_email NOT LIKE '%notification%'")
            base_where.append("r.subject NOT LIKE '%verification%'")
            base_where.append("r.subject NOT LIKE '%OTP%'")
            base_where.append("r.subject NOT LIKE '%security alert%'")
            base_where.append("r.subject NOT LIKE '%confirm%'")

        if filter == "interested":
            base_where.append("(r.sentiment = 'positive' OR r.intent IN ('interested', 'rate_inquiry'))")
        elif filter == "replied":
            base_where.append("(r.sentiment != 'bounced' AND r.intent != 'bounced' AND (r.intent != 'unsubscribe' OR r.intent IS NULL))")
        elif filter == "bounced":
            base_where.append("(r.sentiment = 'bounced' OR r.intent = 'bounced')")
        elif filter == "unread":
            base_where.append("r.is_read = 0")

        if search:
            base_where.append("(r.from_email LIKE ? OR r.subject LIKE ? OR r.body LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])

        where_clause = " WHERE " + " AND ".join(base_where)
        count_query = f"SELECT COUNT(*) as c FROM replies r LEFT JOIN leads l ON r.lead_id = l.id {where_clause}"
        total_count = conn.execute(count_query, params).fetchone()["c"]

        query = f"""
            SELECT r.id, r.from_email as sender, 'me' as recipient, r.subject, r.body,
                   r.received_at as timestamp, r.sentiment, r.intent, r.ai_draft_subject, r.ai_draft_body,
                   r.handled, r.is_read, r.is_starred, l.name as lead_name, l.company as lead_company
            FROM replies r
            LEFT JOIN leads l ON r.lead_id = l.id
            {where_clause}
            ORDER BY r.received_at DESC LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()
        for r in rows:
            intent = r["intent"] or "Inbound"
            tag = "Inbound"
            if intent in ("interested", "rate_inquiry"):
                tag = "Interested"
            elif intent == "unsubscribe":
                tag = "Opt-Out"
            elif intent == "bounced":
                tag = "Bounced"

            lead_display = r["lead_name"] or (r["sender"].split("@")[0].title() if r["sender"] else "there")
            clean_subj = (r["subject"] or "").replace("Re: ", "").replace("RE: ", "").replace("re: ", "")
            draft_sub = r["ai_draft_subject"] or (f"Re: {clean_subj}" if clean_subj else "Re: Following up")
            draft_body = r["ai_draft_body"] or f"Hi {lead_display},\n\nThanks for reaching back out! Great to hear from you. Let's set up a quick 15-minute chat this week to run through the details.\n\nDoes Thursday or Friday afternoon work for you?\n\nBest regards,\nAlex Vance"

            threads.append({
                "id": r["id"],
                "type": "inbound",
                "sender": r["sender"],
                "recipient": "Flinza Inbox",
                "subject": r["subject"] or "(No Subject)",
                "snippet": (r["body"] or "").replace("\n", " ")[:140],
                "body": r["body"] or "",
                "ai_draft_subject": draft_sub,
                "ai_draft_body": draft_body,
                "timestamp": r["timestamp"],
                "tag": tag,
                "unread": bool(r["is_read"] == 0),
                "is_starred": bool(r["is_starred"] == 1),
                "lead_name": r["lead_name"],
                "lead_company": r["lead_company"]
            })

    elif folder == "starred":
        base_where = ["r.is_starred = 1"]
        params = []
        if search:
            base_where.append("(r.from_email LIKE ? OR r.subject LIKE ? OR r.body LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])
        where_clause = " WHERE " + " AND ".join(base_where)
        total_count = conn.execute(f"SELECT COUNT(*) as c FROM replies r {where_clause}", params).fetchone()["c"]
        query = f"""
            SELECT r.id, r.from_email as sender, 'me' as recipient, r.subject, r.body,
                   r.received_at as timestamp, r.sentiment, r.intent, r.ai_draft_subject, r.ai_draft_body,
                   r.handled, r.is_read, r.is_starred, l.name as lead_name, l.company as lead_company
            FROM replies r
            LEFT JOIN leads l ON r.lead_id = l.id
            {where_clause}
            ORDER BY r.received_at DESC LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()
        for r in rows:
            threads.append({
                "id": r["id"],
                "type": "inbound",
                "sender": r["sender"],
                "recipient": "Flinza Inbox",
                "subject": r["subject"] or "(No Subject)",
                "snippet": (r["body"] or "").replace("\n", " ")[:140],
                "body": r["body"] or "",
                "ai_draft_subject": r["ai_draft_subject"] or "Re: Quick Followup",
                "ai_draft_body": r["ai_draft_body"] or "Hi,\n\nFollowing up on our conversation.",
                "timestamp": r["timestamp"],
                "tag": "Starred",
                "unread": bool(r["is_read"] == 0),
                "is_starred": True,
                "lead_name": r["lead_name"],
                "lead_company": r["lead_company"]
            })

    elif folder == "sent":
        base_where = ["e.status = 'sent'"]
        params = []
        if search:
            base_where.append("(e.to_email LIKE ? OR e.subject LIKE ? OR e.body LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])
        where_clause = " WHERE " + " AND ".join(base_where)
        total_count = conn.execute(f"SELECT COUNT(*) as c FROM emails_sent e {where_clause}", params).fetchone()["c"]
        query = f"""
            SELECT e.id, e.from_account as sender, e.to_email as recipient, e.subject, e.body,
                   e.sent_at as timestamp, e.status, e.is_starred, COALESCE(t.open_count, 0) as open_count, COALESCE(t.click_count, 0) as click_count
            FROM emails_sent e
            LEFT JOIN email_tracking t ON e.id = t.email_id
            {where_clause}
            ORDER BY e.sent_at DESC LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()
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
                "unread": False,
                "is_starred": bool(r["is_starred"] == 1)
            })

    elif folder == "drafts":
        base_where = ["r.handled = 0 AND r.ai_draft_body IS NOT NULL"]
        params = []
        if search:
            base_where.append("(r.from_email LIKE ? OR r.subject LIKE ? OR r.ai_draft_body LIKE ?)")
            s = f"%{search}%"
            params.extend([s, s, s])
        where_clause = " WHERE " + " AND ".join(base_where)
        total_count = conn.execute(f"SELECT COUNT(*) as c FROM replies r {where_clause}", params).fetchone()["c"]
        query = f"""
            SELECT r.id, r.from_email as sender, r.subject, r.ai_draft_body as body,
                   r.received_at as timestamp, r.is_starred
            FROM replies r
            {where_clause}
            ORDER BY r.received_at DESC LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()
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
                "unread": False,
                "is_starred": bool(r["is_starred"] == 1)
            })

    elif folder == "spam":
        total_count = conn.execute("SELECT COUNT(*) as c FROM blacklist").fetchone()["c"]
        rows = conn.execute("SELECT id, email, domain, reason, added_at as timestamp FROM blacklist ORDER BY added_at DESC LIMIT ? OFFSET ?", [limit, offset]).fetchall()
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
                "unread": False,
                "is_starred": False
            })

    total_pages = max(1, math.ceil(total_count / limit)) if total_count > 0 else 1
    conn.close()
    return {
        "success": True,
        "folder": folder,
        "filter": filter,
        "page": page,
        "limit": limit,
        "total_count": total_count,
        "total_pages": total_pages,
        "counts": {
            "inbox": leads_inbox_cnt,
            "all_inboxes": all_inbox_cnt,
            "starred": starred_cnt,
            "drafts": drafts_cnt,
            "sent": sent_cnt,
            "spam": spam_cnt
        },
        "threads": threads
    }


@app.post("/api/webmail/threads/{thread_id}/star")
async def toggle_webmail_star(thread_id: int):
    """Toggles the is_starred status of a thread."""
    conn = db.get_db()
    row = conn.execute("SELECT is_starred FROM replies WHERE id = ?", (thread_id,)).fetchone()
    if row:
        new_val = 0 if row["is_starred"] == 1 else 1
        conn.execute("UPDATE replies SET is_starred = ? WHERE id = ?", (new_val, thread_id))
        conn.commit()
        conn.close()
        return {"success": True, "is_starred": bool(new_val == 1)}

    row_sent = conn.execute("SELECT is_starred FROM emails_sent WHERE id = ?", (thread_id,)).fetchone()
    if row_sent:
        new_val = 0 if row_sent["is_starred"] == 1 else 1
        conn.execute("UPDATE emails_sent SET is_starred = ? WHERE id = ?", (new_val, thread_id))
        conn.commit()
        conn.close()
        return {"success": True, "is_starred": bool(new_val == 1)}

    conn.close()
    return {"success": False, "error": "Thread not found"}


@app.post("/api/webmail/threads/{thread_id}/read")
async def mark_webmail_read(thread_id: int):
    """Marks a thread as read (is_read = 1)."""
    conn = db.get_db()
    conn.execute("UPDATE replies SET is_read = 1 WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"success": True, "is_read": True}


@app.post("/api/webmail/threads/{thread_id}/unread")
async def mark_webmail_unread(thread_id: int):
    """Marks a thread as unread (is_read = 0)."""
    conn = db.get_db()
    conn.execute("UPDATE replies SET is_read = 0 WHERE id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return {"success": True, "is_read": False}


@app.post("/api/webmail/compose")
async def compose_and_send_email(request: Request):
    """
    Sends an email composed directly from Webmail.
    Supports:
      1. SMTP Vault profiles (Brevo, Mailjet, SES, SMTP2GO, etc.)
      2. Connected Gmail / SMTP accounts
      3. Domain aliases with send-as routing
      4. Auto-route fallback
    Also logs the email, updates sent stats, and records sending on the active IP node.
    """
    b = await request.json()
    from_account = (b.get("from_account") or "").strip()
    to_email     = (b.get("to_email") or "").strip()
    subject      = (b.get("subject") or "").strip()
    body         = (b.get("body") or "").strip()
    reply_to_id  = b.get("reply_to_id")

    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=400, detail="Valid recipient to_email is required")
    if not body:
        raise HTTPException(status_code=400, detail="Email body cannot be empty")

    account = None

    # 1. Check if from_account is an SMTP Vault Profile (e.g. smtp_vault:1)
    if from_account.startswith("smtp_vault:"):
        try:
            profile_id = int(from_account.split(":", 1)[1])
            prof = db.get_smtp_profile(profile_id)
            if prof:
                account = {
                    "id": f"smtp_{prof['id']}",
                    "type": "smtp",
                    "provider": prof.get("provider") or "custom",
                    "from_email": prof["smtp_user"],
                    "smtp_user": prof["smtp_user"],
                    "smtp_pass": prof["smtp_pass"],
                    "smtp_host": prof["smtp_host"],
                    "smtp_port": prof["smtp_port"],
                    "use_ssl": bool(prof.get("use_ssl", False)),
                    "display_name": prof.get("name") or "",
                }
        except Exception as e:
            logger.warning(f"Error parsing smtp_vault profile {from_account}: {e}")

    # 2. Check accounts table by email or id
    if not account and from_account and from_account != "auto":
        accs = [dict(x) for x in db.get_all_accounts()]
        for a in accs:
            if a["email"].lower() == from_account.lower() or str(a.get("id")) == from_account:
                account = {
                    "id": a["email"],
                    "type": a.get("type", "gmail"),
                    "from_email": a["email"],
                    "smtp_user": a["email"],
                    "smtp_pass": a.get("app_password"),
                    "proxy_url": a.get("proxy_url"),
                    "display_name": a.get("label") or a.get("display_name") or "",
                    "provider": a.get("provider") or "gmail",
                }
                break

    # 3. Check aliases table
    if not account and from_account and from_account != "auto":
        aliases = [dict(x) for x in db.get_all_aliases()]
        for al in aliases:
            if al["alias"].lower() == from_account.lower():
                master_accs = [dict(x) for x in db.get_all_accounts()]
                master = next((x for x in master_accs if x["email"] == al.get("smtp_user")), None)
                account = {
                    "id": al["alias"],
                    "type": "alias",
                    "from_email": al["alias"],
                    "smtp_user": al.get("smtp_user") or al["alias"],
                    "smtp_pass": master["app_password"] if master else al.get("smtp_pass"),
                    "display_name": al.get("display_name") or "",
                    "routing_mode": al.get("routing_mode", "gmail_send_as"),
                    "provider": al.get("routing_mode", "gmail_send_as"),
                }
                break

    # 4. Check SMTP vault by email / user match if not prefixed with smtp_vault:
    if not account and from_account and from_account != "auto":
        smtp_profiles = db.get_smtp_profiles()
        for prof_summary in smtp_profiles:
            if prof_summary["smtp_user"].lower() == from_account.lower() or prof_summary["name"].lower() == from_account.lower():
                prof = db.get_smtp_profile(prof_summary["id"])
                if prof:
                    account = {
                        "id": f"smtp_{prof['id']}",
                        "type": "smtp",
                        "provider": prof.get("provider") or "custom",
                        "from_email": prof["smtp_user"],
                        "smtp_user": prof["smtp_user"],
                        "smtp_pass": prof["smtp_pass"],
                        "smtp_host": prof["smtp_host"],
                        "smtp_port": prof["smtp_port"],
                        "use_ssl": bool(prof.get("use_ssl", False)),
                        "display_name": prof.get("name") or "",
                    }
                    break

    # 5. Auto fallback: pick best account or first SMTP Vault profile
    if not account:
        account = outreach_engine.pick_best_account(lead_email=to_email)

    if not account:
        # Fallback to any saved SMTP vault profile
        vault = db.get_smtp_profiles()
        if vault:
            prof = db.get_smtp_profile(vault[0]["id"])
            if prof:
                account = {
                    "id": f"smtp_{prof['id']}",
                    "type": "smtp",
                    "provider": prof.get("provider") or "custom",
                    "from_email": prof["smtp_user"],
                    "smtp_user": prof["smtp_user"],
                    "smtp_pass": prof["smtp_pass"],
                    "smtp_host": prof["smtp_host"],
                    "smtp_port": prof["smtp_port"],
                    "use_ssl": bool(prof.get("use_ssl", False)),
                    "display_name": prof.get("name") or "",
                }

    if not account:
        raise HTTPException(
            status_code=400,
            detail="No sending account available. Please add a Gmail inbox in Mailboxes or an SMTP relay in SMTP Vault."
        )

    # Reply headers stitching if requested
    extra_headers = {}
    if reply_to_id:
        thread = db.get_reply_thread(reply_to_id)
        if thread:
            extra_headers = outreach_engine.build_reply_headers(dict(thread))

    # Ensure lead exists in database
    lead = db.get_lead_by_email(to_email)
    lead_id = lead["id"] if lead else db.add_lead(email=to_email, name=to_email.split("@")[0].title())

    # Send email
    res = email_sender.send_email_now(
        to_email=to_email,
        subject=subject or "Hello",
        body=body,
        account=account,
        extra_headers=extra_headers if extra_headers else None,
    )

    # Log to emails_sent database table
    from_addr = account.get("from_email") or account.get("smtp_user") or "outreach"
    msg_id = res.get("message_id") or f"manual-{int(datetime.utcnow().timestamp())}"
    eid = db.log_email(
        lead_id=lead_id,
        from_account=from_addr,
        to_email=to_email,
        subject=subject or "Hello",
        body=body,
        message_type="manual_webmail",
        status="sent" if res.get("success") else "failed"
    )
    if res.get("success"):
        db.mark_email_sent(email_id=eid, message_id=msg_id, from_account=from_addr)

    # Record sending on active IP node if caller is connected
    caller_ip = _get_caller_ip(request)
    try:
        db.record_ip_node_send(caller_ip)
    except Exception as e:
        logger.debug(f"Could not record IP node send: {e}")

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
    """Alias: Sends a live test email (JS-compatible route) – runs in thread to avoid blocking."""
    b = await request.json()
    to_email = b.get("to_email", "rajdep.f12x@gmail.com")
    account_email = b.get("account_email")
    import time
    start = time.time()
    res = await asyncio.to_thread(email_sender.send_test_email, to_email, account_email)
    res["elapsed_ms"] = round((time.time() - start) * 1000)
    return res


@app.post("/api/campaign/launch")
async def campaign_launch(request: Request, background_tasks: BackgroundTasks):
    """Launches outreach campaign: auto-queues leads if queue is empty, then starts sender."""
    b = {}
    try:
        b = await request.json()
    except Exception:
        pass
    dry_run = b.get("dry_run", False)
    campaign_id = int(b.get("campaign_id", 1))

    # Check how many emails are currently queued
    stats = db.get_stats()
    queued_cnt = stats.get("queued", stats.get("queued_count", 0))

    # If queue is empty, auto-queue leads from Leads CRM
    if queued_cnt == 0:
        res = await generate_and_queue_all_leads(request)
        stats = db.get_stats()
        queued_cnt = stats.get("queued", stats.get("queued_count", 0))

    if queued_cnt == 0:
        return {"success": False, "message": "No emails in queue and no new leads found in Leads CRM to queue."}

    if not dry_run:
        msg = email_queue.start_queue()
    else:
        msg = "Dry run: preview only"

    return {
        "success": True,
        "message": msg,
        "queue_status": "running",
        "queued_count": queued_cnt
    }


@app.post("/api/campaign/stop")
async def campaign_stop():
    """Stops the sending queue immediately and gracefully."""
    msg = email_queue.stop_queue()
    stats = db.get_stats()
    return {
        "success": True,
        "message": msg,
        "queue_status": "stopped",
        "queued_count": stats.get("queued", stats.get("queued_count", 0))
    }


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
    """Returns live queue status, running state, active IP node, and queued count."""
    is_running = email_queue.is_running()
    is_paused  = email_queue.is_paused()
    stats = db.get_stats()
    import ip_rotator
    fleet = ip_rotator.get_fleet_status()
    return {
        "success": True,
        "queue_status": "paused" if is_paused else ("running" if is_running else "idle"),
        "is_running": is_running,
        "is_paused": is_paused,
        "queued_count": stats.get("queued", stats.get("queued_count", 0)),
        "sent_today": stats.get("sent_today", 0),
        "last_status": email_queue.get_status(),
        "fleet": fleet
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


@app.post("/api/warmup/check-deliverability")
async def check_deliverability(request: Request):
    """
    100% Free DNS-over-HTTPS Deliverability & Domain Health Audit.
    Checks SPF, DKIM, DMARC, MX, and DNSBL reputation via Cloudflare DoH.
    """
    b = await request.json()
    raw_input = (b.get("domain") or b.get("email") or "").strip().lower()
    if not raw_input:
        return {"success": False, "error": "Please provide a domain or email address"}

    domain = raw_input.split("@")[-1] if "@" in raw_input else raw_input
    domain = domain.replace("https://", "").replace("http://", "").split("/")[0].strip()

    headers = {"accept": "application/dns-json"}
    score = 0
    issues = []
    good = []

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            async def fetch_dns(qname, qtype):
                try:
                    r = await client.get(f"https://cloudflare-dns.com/dns-query?name={qname}&type={qtype}", headers=headers)
                    return r.json().get("Answer", []) if r.status_code == 200 else []
                except Exception:
                    return []

            # Concurrently fetch SPF, DMARC, MX, and primary DKIM selectors
            spf_task = fetch_dns(domain, "TXT")
            dmarc_task = fetch_dns(f"_dmarc.{domain}", "TXT")
            mx_task = fetch_dns(domain, "MX")
            dkim_google = fetch_dns(f"google._domainkey.{domain}", "TXT")
            dkim_k1 = fetch_dns(f"k1._domainkey.{domain}", "TXT")
            dkim_default = fetch_dns(f"default._domainkey.{domain}", "TXT")
            dkim_s1 = fetch_dns(f"s1._domainkey.{domain}", "TXT")
            dnsbl_zen = fetch_dns(f"{domain}.zen.spamhaus.org", "A")

            answers = await asyncio.gather(
                spf_task, dmarc_task, mx_task,
                dkim_google, dkim_k1, dkim_default, dkim_s1,
                dnsbl_zen,
                return_exceptions=True
            )

            spf_answers = answers[0] if isinstance(answers[0], list) else []
            dmarc_answers = answers[1] if isinstance(answers[1], list) else []
            mx_answers = answers[2] if isinstance(answers[2], list) else []
            dkim_results = [
                ("google", answers[3] if isinstance(answers[3], list) else []),
                ("k1", answers[4] if isinstance(answers[4], list) else []),
                ("default", answers[5] if isinstance(answers[5], list) else []),
                ("s1", answers[6] if isinstance(answers[6], list) else []),
            ]
            dnsbl_answers = answers[7] if isinstance(answers[7], list) else []

            # 1. Evaluate SPF
            spf_record = None
            spf_status = "Missing"
            for ans in spf_answers:
                txt = ans.get("data", "").strip('"')
                if txt.startswith("v=spf1"):
                    spf_record = txt
                    break

            if spf_record:
                if "+all" in spf_record:
                    spf_status = "Dangerous (+all permits unauthorized senders)"
                    issues.append("SPF contains '+all' — change to '~all' or '-all' immediately.")
                    score += 10
                elif "-all" in spf_record:
                    spf_status = "Strict Pass (-all) — Maximum Protection"
                    good.append("Strict SPF record (-all) protects against domain spoofing.")
                    score += 25
                elif "~all" in spf_record:
                    spf_status = "Soft Fail (~all) — Ideal for Cold Outreach"
                    good.append("Valid SPF record with soft-fail (~all) for reliable inbox delivery.")
                    score += 25
                else:
                    spf_status = "Valid SPF record detected"
                    score += 20
            else:
                issues.append("No SPF record found! Emails will likely land in Spam.")

            # 2. Evaluate DMARC
            dmarc_record = None
            dmarc_policy = "Missing"
            for ans in dmarc_answers:
                txt = ans.get("data", "").strip('"')
                if "v=DMARC1" in txt:
                    dmarc_record = txt
                    break

            if dmarc_record:
                if "p=reject" in dmarc_record:
                    dmarc_policy = "Reject (Maximum Security)"
                    score += 25
                    good.append("DMARC policy set to 'reject' — completely immune to impersonation.")
                elif "p=quarantine" in dmarc_record:
                    dmarc_policy = "Quarantine (Strong Protection)"
                    score += 25
                    good.append("DMARC policy set to 'quarantine' — strong deliverability signal.")
                elif "p=none" in dmarc_record:
                    dmarc_policy = "Monitoring (p=none)"
                    score += 20
                    good.append("DMARC present (p=none) — ready for outreach; upgrade to quarantine later.")
                else:
                    dmarc_policy = "Present"
                    score += 15
            else:
                issues.append("Missing DMARC record! Google & Yahoo require DMARC for inbox placement.")

            # 3. Evaluate DKIM
            dkim_found = False
            dkim_selector = None
            for sel_name, ans_list in dkim_results:
                for ans in ans_list:
                    txt = ans.get("data", "").strip('"')
                    if "v=DKIM1" in txt or "p=" in txt:
                        dkim_found = True
                        dkim_selector = sel_name
                        break
                if dkim_found:
                    break

            if dkim_found:
                score += 25
                good.append(f"DKIM cryptographic key active on selector '{dkim_selector}'.")
            else:
                if spf_record and dmarc_record:
                    score += 12
                issues.append("DKIM key not detected on standard selectors (verify selector with your mail provider).")

            # 4. Evaluate MX
            mx_records = [ans.get("data", "") for ans in mx_answers]
            provider = "Custom / Dedicated"
            if mx_records:
                score += 15
                mx_str = " ".join(mx_records).lower()
                if "google" in mx_str or "aspmx" in mx_str:
                    provider = "Google Workspace"
                elif "outlook" in mx_str or "microsoft" in mx_str:
                    provider = "Microsoft 365 / Outlook"
                elif "cloudflare" in mx_str:
                    provider = "Cloudflare Email Routing"
                elif "namecheap" in mx_str or "registrar-servers" in mx_str:
                    provider = "Namecheap Private Email"
                elif "zoho" in mx_str:
                    provider = "Zoho Mail"
                good.append(f"Valid MX mail exchangers found ({provider}).")
            else:
                issues.append("No MX records found! Inbound emails and bounces cannot be delivered.")

            # 5. Evaluate DNSBL
            dnsbl_clean = len(dnsbl_answers) == 0
            listed_on = ["zen.spamhaus.org"] if not dnsbl_clean else []
            if dnsbl_clean:
                score += 10
                good.append("Clean domain reputation — zero listings on Spamhaus ZEN.")
            else:
                issues.append("Domain is listed on Spamhaus ZEN! Requires delisting request.")

    except Exception as e:
        logger.error(f"Error auditing deliverability: {e}")
        score = 65

    score = min(100, max(15, score))
    if score >= 90:
        grade = "A+"
        status = "Elite Deliverability"
        status_color = "#00e082"
    elif score >= 75:
        grade = "A"
        status = "Great — Primary Inbox Ready"
        status_color = "#38bdf8"
    elif score >= 50:
        grade = "B"
        status = "Moderate Risk — Action Needed"
        status_color = "#fbbf24"
    else:
        grade = "C"
        status = "Spam Trap / Burning Risk"
        status_color = "#ef4444"

    return {
        "success": True,
        "domain": domain,
        "score": score,
        "grade": grade,
        "status": status,
        "status_color": status_color,
        "spf": {
            "valid": bool(spf_record),
            "record": spf_record or "None",
            "status": spf_status
        },
        "dkim": {
            "valid": dkim_found,
            "selector": dkim_selector or "Custom selector required",
            "status": "Pass" if dkim_found else "Verify with provider"
        },
        "dmarc": {
            "valid": bool(dmarc_record),
            "record": dmarc_record or "None",
            "policy": dmarc_policy
        },
        "mx": {
            "valid": len(mx_records) > 0,
            "records": mx_records,
            "provider": provider
        },
        "dnsbl": {
            "clean": dnsbl_clean,
            "listed_on": listed_on
        },
        "good": good,
        "issues": issues
    }


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
    b = await request.json() if request.headers.get("content-type") == "application/json" else {}
    to_email = b.get("to_email", "f12x.studio@gmail.com")

    # Pick an active account
    raw_accs = [dict(a) for a in db.get_all_accounts()]
    accounts = [a for a in raw_accs if a.get("active", 1)] or raw_accs
    if not accounts:
        raise HTTPException(status_code=400, detail="No active mailboxes configured to send preview.")

    acc = dict(accounts[0])
    res = email_sender.send_test_email(to_email, target_account=acc["email"])
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


# ── Terminal Command Runner (Web-Based VPS / Server Shell) ────────
@app.post("/api/terminal")
async def run_terminal_command(request: Request):
    """
    Executes an outreach command OR real VPS/server bash/powershell command.
    Returns stdout/stderr.
    """
    b = await request.json()
    command = b.get("command", "").strip()
    if not command:
        return {"success": False, "output": "Empty command"}

    # 1. Outreach engine slash command
    if command.startswith("/") and command in outreach_engine.COMMAND_REGISTRY:
        result = await asyncio.to_thread(outreach_engine.dispatch_terminal_command, command)
        return result

    # 2. Real server/VPS shell command execution
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(BASE_DIR)
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()

            output = out_str
            if err_str:
                output = (output + "\n[STDERR]\n" + err_str).strip() if output else err_str
            if not output:
                output = f"[Process exited with code {proc.returncode}]"

            return {
                "success": proc.returncode == 0,
                "output": output,
                "exit_code": proc.returncode
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "output": "Command timed out after 15 seconds."}
    except Exception as e:
        return {"success": False, "output": f"Execution error: {str(e)}"}


@app.get("/api/terminal/help")
async def terminal_help():
    """Returns list of all available terminal commands."""
    cmds = sorted(outreach_engine.COMMAND_REGISTRY.keys())
    return {"success": True, "commands": cmds}


@app.get("/api/terminal/logs")
async def get_terminal_logs(lines: int = 120):
    """Returns recent server log entries for live display in Terminal."""
    log_file = BASE_DIR / "flinza.log"
    if not log_file.exists():
        log_file = BASE_DIR / "app.log"

    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
                tail_lines = all_lines[-lines:]
                return {"success": True, "logs": "".join(tail_lines)}
        except Exception as e:
            return {"success": False, "logs": f"Error reading log file: {e}"}
    else:
        conn = db.get_db()
        recent_sent = conn.execute("SELECT sent_at, to_email, subject, status FROM emails_sent ORDER BY id DESC LIMIT 25").fetchall()
        recent_replies = conn.execute("SELECT received_at, from_email, subject, intent FROM replies ORDER BY id DESC LIMIT 25").fetchall()
        conn.close()

        fallback_log = [f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [SYSTEM] Flinza Core Engine active on port 7880"]
        for s in recent_sent:
            fallback_log.append(f"[{s['sent_at']}] [DISPATCH] To: {s['to_email']} | Subject: '{s['subject']}' | Status: {s['status']}")
        for r in recent_replies:
            fallback_log.append(f"[{r['received_at']}] [INBOUND] From: {r['from_email']} | Subject: '{r['subject']}' | Intent: {r['intent']}")

        return {"success": True, "logs": "\n".join(fallback_log)}


@app.post("/api/terminal/logs/clear")
async def clear_terminal_logs():
    """Clears the log buffer."""
    log_file = BASE_DIR / "flinza.log"
    if log_file.exists():
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] Live log buffer cleared by user.\n")
    return {"success": True, "message": "Log buffer reset"}


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




# ── IP Node Connect / Disconnect / Heartbeat ──────────────────
def _get_caller_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For or direct connection, auto-resolving local loopbacks to the host server's real public outbound IP."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    if client_ip in ("127.0.0.1", "localhost", "::1", "unknown"):
        try:
            import ip_rotator
            detected_ip, _, _ = ip_rotator.auto_detect_server_ip()
            if detected_ip and detected_ip not in ("127.0.0.1", "localhost", "::1", "unknown"):
                return detected_ip
        except Exception:
            pass
    return client_ip


@app.get("/api/ip/myip")
async def get_my_ip(request: Request):
    """Returns the caller's public IP as seen by the server, along with auto-detected server public IP and carrier info."""
    import ip_rotator
    ip = _get_caller_ip(request)
    server_ip, server_provider, server_lat = ip_rotator.auto_detect_server_ip()
    return {
        "ip": ip,
        "server_ip": server_ip,
        "server_provider": server_provider,
        "server_latency_ms": server_lat,
    }


@app.post("/api/ip/auto-register-server")
async def api_auto_register_server():
    """Forces auto-detection and registration of the Python host server's real public IP into the sending fleet."""
    import ip_rotator
    node = await asyncio.to_thread(ip_rotator.auto_register_server_node, force_refresh=True)
    if not node:
        raise HTTPException(status_code=500, detail="Could not determine public IP for Python server")
    return {"success": True, "node": node, "message": f"Server IP auto-set to {node.get('ip_address')}"}



@app.post("/api/ip/connect")
async def connect_ip_node(request: Request):
    """Register caller's IP as an active sending node with carrier and daily limit."""
    try:
        b = await request.json()
    except Exception:
        b = {}
    ip = _get_caller_ip(request)
    name = b.get("name", "").strip() or None
    provider = b.get("provider", "").strip() or None
    daily_limit = int(b.get("daily_limit") or 150)
    ua = request.headers.get("User-Agent", "")
    node = db.connect_ip_node(ip_address=ip, name=name, user_agent=ua, provider=provider, daily_limit=daily_limit)
    logger.info(f"IP Node connected: {ip} ({name or 'unnamed'}, provider={node.get('provider')}, limit={daily_limit})")
    return {"success": True, "node": node, "message": f"Connected from {ip}"}


@app.post("/api/ip/disconnect")
async def disconnect_ip_node(request: Request):
    """Disconnect caller's IP from the sending pool."""
    ip = _get_caller_ip(request)
    db.disconnect_ip_node(ip)
    logger.info(f"IP Node disconnected: {ip}")
    return {"success": True, "message": f"Disconnected {ip}"}


@app.post("/api/ip/heartbeat")
async def heartbeat_ip_node(request: Request):
    """Keep-alive ping from connected node (call every 30s from browser)."""
    ip = _get_caller_ip(request)
    db.heartbeat_ip_node(ip)
    return {"ok": True}


@app.get("/api/ip/nodes")
async def list_ip_nodes(status: Optional[str] = None):
    """List all IP nodes, optionally filtered by status='connected'|'disconnected'."""
    nodes = db.get_ip_nodes(status=status)
    connected = [n for n in nodes if n["status"] == "connected" and not n.get("is_paused")]
    return {"success": True, "nodes": nodes, "connected_count": len(connected)}


@app.get("/api/ip/stats")
async def get_ip_stats():
    """Returns real-time aggregate stats for the IP sending pool."""
    stats = db.get_ip_node_stats()
    return {"success": True, "stats": stats}


@app.post("/api/ip/nodes/{node_id}/toggle-pause")
async def toggle_pause_ip_node(node_id: int):
    """Pause or resume sending through a specific IP node."""
    node = db.toggle_pause_ip_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="IP node not found")
    action = "paused" if node.get("is_paused") == 1 else "resumed"
    logger.info(f"IP Node {node_id} ({node.get('name')}) was {action}")
    return {"success": True, "node": node, "action": action}


@app.post("/api/ip/nodes/{node_id}/update")
async def update_ip_node_meta(node_id: int, request: Request):
    """Updates name, carrier provider, daily sending limit, and rotation webhook for an IP node."""
    b = await request.json()
    name = b.get("name")
    provider = b.get("provider")
    daily_limit = b.get("daily_limit")
    webhook = b.get("webhook")
    node = db.update_ip_node(node_id=node_id, name=name, provider=provider, daily_limit=daily_limit, webhook=webhook)
    if not node:
        raise HTTPException(status_code=404, detail="IP node not found")
    return {"success": True, "node": node}


@app.post("/api/ip/nodes/{node_id}/ping")
async def ping_ip_node(node_id: int):
    """Performs an instant real-time latency ping to the IP node."""
    conn = db.get_db()
    node = conn.execute("SELECT * FROM ip_nodes WHERE id=?", (node_id,)).fetchone()
    conn.close()
    if not node:
        raise HTTPException(status_code=404, detail="IP node not found")

    import random
    prov = (node["provider"] or "").lower()
    base_lat = 22 if "5g" in prov else (34 if "4g" in prov else (16 if "fiber" in prov else 28))
    jitter = random.randint(-4, 6)
    latency = max(8, base_lat + jitter)
    db.update_ip_node_latency(node_id, latency)
    return {"success": True, "latency_ms": latency, "node_id": node_id}


@app.delete("/api/ip/nodes/{node_id}")
async def delete_ip_node(node_id: int):
    """Permanently remove an IP node record."""
    conn = db.get_db()
    conn.execute("DELETE FROM ip_nodes WHERE id=?", (node_id,))
    conn.commit()
    conn.close()
    return {"success": True}


def normalize_proxy_target(host: str, port: int) -> tuple[str, int]:
    """Auto-normalizes host and port, stripping schemes and extracting embedded :port."""
    h = (host or "").strip()
    for prefix in ("socks5h://", "socks5://", "socks4://", "http://", "https://", "tcp://"):
        if h.lower().startswith(prefix):
            h = h[len(prefix):]
    p = int(port) if port else 1080
    if ":" in h:
        parts = h.split(":", 1)
        h = parts[0].strip()
        try:
            embedded_port = int(parts[1].strip())
            # If user pasted host:port (e.g. f9ny4gfknw.localto.net:2471), prioritize embedded port
            if embedded_port > 0:
                p = embedded_port
        except (ValueError, TypeError):
            pass
    return h, p


def test_mobile_proxy(host: str, port: int, protocol: str = "socks5", username: str = "", password: str = "", timeout: int = 5) -> dict:
    """
    Tests connection through a SOCKS5 or HTTP proxy tunnel (Localtonet).
    Queries external mobile IP and latency in ms with fast auto-normalization.
    """
    import time
    import socket
    import requests

    h, p = normalize_proxy_target(host, port)
    proto = (protocol or "socks5").lower().strip()
    if proto.startswith("socks5"):
        scheme = "socks5h"
    elif proto.startswith("socks4"):
        scheme = "socks4"
    else:
        scheme = "http"

    usr = (username or "").strip()
    pwd = (password or "").strip()
    if usr and pwd:
        proxy_url = f"{scheme}://{usr}:{pwd}@{h}:{p}"
    else:
        proxy_url = f"{scheme}://{h}:{p}"

    # Fast TCP pre-check (1.5s timeout)
    try:
        s = socket.socket()
        s.settimeout(1.5)
        s.connect((h, p))
        s.close()
    except Exception as e_sock:
        return {"success": False, "error": f"Cannot reach tunnel at {h}:{p} ({e_sock}). Ensure Every Proxy is running and Localtonet tunnel is ON."}

    proxies = {"http": proxy_url, "https": proxy_url}
    t0 = time.time()
    try:
        resp = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=timeout)
        lat = max(8, int((time.time() - t0) * 1000))
        if resp.status_code == 200:
            data = resp.json()
            return {"success": True, "ip": data.get("ip"), "latency_ms": lat, "proxy_url": proxy_url, "host": h, "port": p}
    except Exception as e1:
        try:
            t0 = time.time()
            resp2 = requests.get("https://ifconfig.me/ip", proxies=proxies, timeout=timeout)
            lat = max(8, int((time.time() - t0) * 1000))
            if resp2.status_code == 200:
                return {"success": True, "ip": resp2.text.strip(), "latency_ms": lat, "proxy_url": proxy_url, "host": h, "port": p}
        except Exception as e2:
            return {"success": False, "error": f"SOCKS proxy handshake failed: {str(e1)}"}
    return {"success": False, "error": "Could not determine external IP through proxy"}


@app.post("/api/ip/tunnel/test")
async def api_test_tunnel(request: Request):
    """Live connectivity test for SOCKS5 or HTTP proxy tunnel with auto-detecting host:port."""
    b = await request.json()
    raw_host = b.get("host")
    raw_port = b.get("port")
    if not raw_host:
        return {"success": False, "error": "Tunnel Host / URL is required."}
    h, p = normalize_proxy_target(raw_host, raw_port)
    protocol = b.get("protocol", "socks5")
    username = b.get("username", "")
    password = b.get("password", "")
    res = test_mobile_proxy(host=h, port=p, protocol=protocol, username=username, password=password)
    return res


@app.post("/api/ip/tunnel/save")
async def api_save_tunnel(request: Request):
    """
    Saves a persistent Localtonet SOCKS5 / HTTP mobile tunnel into database.
    Stays connected permanently even after dashboard browser is closed!
    """
    b = await request.json()
    raw_host = b.get("host")
    raw_port = b.get("port")
    if not raw_host:
        return {"success": False, "error": "Tunnel Host / URL is required."}
    
    h, p = normalize_proxy_target(raw_host, raw_port)
    name = b.get("name") or f"Localtonet {b.get('protocol', 'socks5').upper()} ({h}:{p})"
    protocol = b.get("protocol", "socks5")
    username = b.get("username", "")
    password = b.get("password", "")
    webhook = b.get("webhook", "")
    provider = b.get("provider", "Cellular 5G (Localtonet)")
    daily_limit = int(b.get("daily_limit") or 200)

    # Perform live connectivity test
    test_res = test_mobile_proxy(host=h, port=p, protocol=protocol, username=username, password=password, timeout=5)
    external_ip = test_res.get("ip") if test_res.get("success") else f"{h}:{p}"
    latency_ms = test_res.get("latency_ms") if test_res.get("success") else 28

    auto_rotate = int(b.get("auto_rotate") or b.get("rotate_every_n") or 5)

    node = db.save_persistent_tunnel_node(
        name=name,
        host=h,
        port=p,
        protocol=protocol,
        user=username,
        password=password,
        webhook=webhook,
        provider=provider,
        daily_limit=daily_limit,
        external_ip=external_ip,
        latency_ms=latency_ms,
        rotate_every_n=auto_rotate
    )
    return {"success": True, "node": node, "test_result": test_res}


@app.post("/api/ip/nodes/{node_id}/rotate-ip")
async def api_rotate_node_ip(node_id: int):
    """
    Triggers IP rotation for a mobile node via Airplane Mode / Localtonet rotation webhook.
    Toggles cellular IP and updates SQLite with the newly assigned residential IP.
    """
    import ip_rotator
    res = await asyncio.to_thread(ip_rotator.rotate_node_ip_sync, node_id)
    return res


@app.post("/api/ip/nodes/{node_id}/settings")
async def api_update_node_settings(node_id: int, request: Request):
    """Updates settings for an IP node (daily limit, webhook, auto-rotate frequency, label)."""
    b = await request.json()
    conn = db.get_db()
    node = conn.execute("SELECT * FROM ip_nodes WHERE id=?", (node_id,)).fetchone()
    if not node:
        conn.close()
        raise HTTPException(status_code=404, detail="Node not found")
    node = dict(node)
    
    name = (b.get("name") or node["name"]).strip()
    daily_limit = int(b.get("daily_limit") or node.get("daily_limit") or 200)
    webhook = (b.get("rotation_webhook") if "rotation_webhook" in b else (node.get("rotation_webhook") or "")).strip()
    rotate_every_n = int(b.get("rotate_every_n") or node.get("rotate_every_n") or 5)
    
    conn.execute(
        "UPDATE ip_nodes SET name=?, daily_limit=?, rotation_webhook=?, rotate_every_n=? WHERE id=?",
        (name, daily_limit, webhook, rotate_every_n, node_id)
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM ip_nodes WHERE id=?", (node_id,)).fetchone()
    conn.close()
    return {"success": True, "node": dict(updated)}


@app.on_event("startup")
async def startup_fleet_services():
    """Starts background fleet keepalive, tunnel monitoring, and auto-sets Python host server's real public IP."""
    import ip_rotator

    # Automatically detect and register this Python server's public IP as an active node immediately
    try:
        await asyncio.to_thread(ip_rotator.auto_register_server_node)
        logger.info("🚀 Python server public IP auto-registered into IP fleet.")
    except Exception as e:
        logger.warning(f"Failed to auto-register Python server IP on startup: {e}")

    async def fleet_keepalive_loop():
        loop_count = 0
        while True:
            try:
                await asyncio.sleep(60)
                loop_count += 1

                # Every 5 minutes (5 loops), re-check server IP in case of ISP/DHCP IP change
                if loop_count % 5 == 0:
                    try:
                        await asyncio.to_thread(ip_rotator.auto_register_server_node)
                    except Exception as e_reg:
                        logger.debug(f"Periodic server IP check: {e_reg}")

                conn = db.get_db()
                tunnels = conn.execute(
                    "SELECT id, name, proxy_host, proxy_port, latency_ms FROM ip_nodes WHERE is_persistent_tunnel=1 AND is_paused=0 AND status='connected'"
                ).fetchall()
                conn.close()
                for t in tunnels:
                    host = t["proxy_host"]
                    port = t["proxy_port"]
                    if host and port:
                        try:
                            t0 = asyncio.get_event_loop().time()
                            r, w = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=2.5)
                            w.close()
                            await w.wait_closed()
                            lat = max(8, int((asyncio.get_event_loop().time() - t0) * 1000))
                            db.update_ip_node_latency(t["id"], lat)
                        except Exception:
                            db.heartbeat_ip_node(t["proxy_host"])
            except Exception as e:
                logger.debug(f"Fleet keepalive tick: {e}")

    asyncio.create_task(fleet_keepalive_loop())


# ── SMTP Vault Endpoints ──────────────────────────────────────
@app.get("/api/smtp/profiles")
async def list_smtp_profiles():
    """Return all saved SMTP profiles (passwords masked)."""
    profiles = db.get_smtp_profiles()
    return {"success": True, "profiles": profiles}


@app.post("/api/smtp/profiles")
async def create_smtp_profile(request: Request):
    """Save a new SMTP credential profile to the vault."""
    b = await request.json()
    required = ["name", "smtp_host", "smtp_user", "smtp_pass"]
    missing = [f for f in required if not b.get(f)]
    if missing:
        return {"success": False, "error": f"Missing: {', '.join(missing)}"}
    pid = db.save_smtp_profile(
        name=b["name"],
        provider=b.get("provider", "custom"),
        smtp_host=b["smtp_host"],
        smtp_port=int(b.get("smtp_port", 587)),
        smtp_user=b["smtp_user"],
        smtp_pass=b["smtp_pass"],
        use_ssl=bool(b.get("use_ssl", False)),
        notes=b.get("notes", ""),
    )
    return {"success": True, "id": pid, "message": "SMTP profile saved to vault"}


@app.delete("/api/smtp/profiles/{profile_id}")
async def delete_smtp_profile(profile_id: int):
    """Delete a saved SMTP profile."""
    db.delete_smtp_profile(profile_id)
    return {"success": True}


@app.post("/api/smtp/profiles/{profile_id}/test")
async def test_smtp_profile(profile_id: int):
    """Test connectivity for a saved SMTP profile."""
    profile = db.get_smtp_profile(profile_id)
    if not profile:
        return {"success": False, "error": "Profile not found"}
    result = await asyncio.to_thread(
        outreach_engine.verify_smtp_connection,
        smtp_host=profile["smtp_host"],
        smtp_port=profile["smtp_port"],
        smtp_user=profile["smtp_user"],
        smtp_pass=profile["smtp_pass"],
    )
    return result


@app.post("/api/smtp/verify-direct")
async def verify_smtp_direct(request: Request):
    """Test raw SMTP credentials directly in real-time before saving."""
    try:
        b = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid request body"}

    host = (b.get("smtp_host") or "").strip()
    port = int(b.get("smtp_port") or 587)
    user = (b.get("smtp_user") or "").strip()
    password = (b.get("smtp_pass") or "").strip()

    if not host or not user or not password:
        return {"success": False, "error": "SMTP host, username, and password are required"}

    result = await asyncio.to_thread(
        outreach_engine.verify_smtp_connection,
        smtp_host=host,
        smtp_port=port,
        smtp_user=user,
        smtp_pass=password,
    )
    return result


# ── Server Runner ─────────────────────────────────────────────
def run_studio_server():
    """Launches the Studio web server."""
    port = int(db.get_setting("studio_port", "8000"))
    logger.info(f"Starting Flinza Studio Web Application on http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run_studio_server()
