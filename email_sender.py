"""
Flinza — Email Sender
SMTP send with Gmail account + alias rotation, optional SOCKS5/HTTP proxy per account,
daily limit tracking, bounce detection.
"""

import smtplib
import socket
import logging
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid, formatdate
from urllib.parse import urlparse

from datetime import datetime
import time

import config
import email_toolkit
import requests
import database as db
import email_verifier
import outreach_engine

logger = logging.getLogger(__name__)

import google_auth
import tracking_server
import signature_generator

# Known bounce/block SMTP codes
BOUNCE_CODES = {550, 551, 552, 553, 554, 450, 421}


def send_via_cloudflare_api(from_email: str, to_email: str, subject: str, body: str, html_body: str = None, display_name: str = None) -> dict:
    """
    Dispatches outbound email directly via Cloudflare's Native Email Sending REST API.
    Available with Cloudflare Workers Paid tier ($5/month).
    Endpoint: POST https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send
    """
    account_id = config.CF_ACCOUNT_ID or db.get_setting("cf_account_id", "")
    api_token  = config.CF_API_TOKEN or db.get_setting("cf_api_token", "")

    if not account_id or not api_token:
        return {
            "success": False,
            "error": "Cloudflare CF_ACCOUNT_ID or CF_API_TOKEN is not configured in settings/.env"
        }

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    from_addr = f"{display_name} <{from_email}>" if display_name else from_email
    payload = {
        "from": from_addr,
        "to": [to_email] if isinstance(to_email, str) else to_email,
        "subject": subject,
        "text": body,
        "html": html_body or body.replace("\n", "<br />\n")
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        data = resp.json()
        if data.get("success"):
            msg_id = data.get("result", {}).get("id") or make_msgid(domain=from_email.split("@")[-1] if "@" in from_email else "cloudflare.com")
            return {
                "success": True,
                "message_id": msg_id,
                "account_used": from_email,
                "provider": "cloudflare_api"
            }
        else:
            errors = data.get("errors", [])
            err_msg = errors[0].get("message") if errors else resp.text
            return {
                "success": False,
                "error": f"Cloudflare Email API error: {err_msg}",
                "status_code": resp.status_code
            }
    except Exception as e:
        logger.error(f"Cloudflare email send exception: {e}")
        return {"success": False, "error": str(e)}


def send_via_smtp2go_api(api_key: str, from_email: str, to_email: str, subject: str, body: str, html_body: str = None, display_name: str = None) -> dict:
    """Dispatches outbound email via SMTP2GO REST API v3."""
    url = "https://api.smtp2go.com/v3/email/send"
    headers = {"Content-Type": "application/json"}
    from_addr = f"{display_name} <{from_email}>" if display_name else from_email
    payload = {
        "api_key": api_key,
        "to": [to_email] if isinstance(to_email, str) else to_email,
        "sender": from_addr,
        "subject": subject,
        "text_body": body,
        "html_body": html_body or body.replace("\n", "<br />\n")
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        data = resp.json()
        if data.get("data", {}).get("succeeded", 0) > 0:
            email_id = data.get("data", {}).get("email_id") or make_msgid(domain="smtp2go.com")
            return {"success": True, "provider": "smtp2go_api", "message_id": email_id, "account_used": from_email}
        err = data.get("data", {}).get("error") or resp.text
        return {"success": False, "error": f"SMTP2GO API error: {err}", "account_used": from_email}
    except Exception as e:
        return {"success": False, "error": str(e), "account_used": from_email}


def send_via_mailjet_api(api_key: str, secret_key: str, from_email: str, to_email: str, subject: str, body: str, html_body: str = None, display_name: str = None) -> dict:
    """Dispatches outbound email via Mailjet REST API v3.1."""
    url = "https://api.mailjet.com/v3.1/send"
    from_payload = {"Email": from_email}
    if display_name:
        from_payload["Name"] = display_name
    payload = {
        "Messages": [
            {
                "From": from_payload,
                "To": [{"Email": to_email}],
                "Subject": subject,
                "TextPart": body,
                "HTMLPart": html_body or body.replace("\n", "<br />\n")
            }
        ]
    }
    try:
        resp = requests.post(url, json=payload, auth=(api_key, secret_key), timeout=20)
        data = resp.json()
        messages = data.get("Messages", [])
        if messages and messages[0].get("Status") == "success":
            to_info = messages[0].get("To", [{}])
            msg_id = str(to_info[0].get("MessageID")) if to_info else make_msgid(domain="mailjet.com")
            return {"success": True, "provider": "mailjet_api", "message_id": msg_id, "account_used": from_email}
        err = resp.text
        return {"success": False, "error": f"Mailjet API error: {err}", "account_used": from_email}
    except Exception as e:
        return {"success": False, "error": str(e), "account_used": from_email}


def send_email_now(to_email: str, subject: str, body: str, account: dict, tracking_token: str = None, extra_headers: dict = None) -> dict:
    """
    Send an email immediately using the given account dict.
    Supports:
      1. Cloudflare Native Email Sending REST API ($5/mo Workers Paid)
      2. Google OAuth 2.0 Gmail REST API
      3. SMTP2GO & Mailjet REST APIs
      4. Brevo, Amazon SES, Gmail, Namecheap, Zoho, Outlook SMTP relays
    """
    from_email   = account["from_email"]
    provider     = account.get("provider") or ("gmail" if account.get("type") == "gmail" else "smtp")
    smtp_user    = account.get("smtp_user", from_email)
    smtp_pass    = account.get("smtp_pass")
    proxy_url    = account.get("proxy_url")
    display_name = account.get("display_name") or _make_display_name(from_email)
    acct_type    = account.get("type", "gmail")

    # 1. Resolve Spintax in subject and body for unique fingerprinting
    subject = email_toolkit.resolve_spintax(subject)
    body = email_toolkit.resolve_spintax(body)

    # 2. Append opt-out footer if enabled
    if db.get_setting("optout_footer_enabled", "0") == "1":
        optout_text = db.get_setting("optout_text", "")
        if optout_text and optout_text not in body:
            body = body + optout_text

    # 3. Build message body — plain text ONLY for cold outreach (no HTML = no spam triggers)
    sig_cfg  = signature_generator.get_signature_settings()
    use_html = db.get_setting("html_email_enabled", "0") == "1"

    plain_text_body = body

    # Append plain-text signature
    if sig_cfg.get("sig_enabled", "1") == "1":
        sig_name    = sig_cfg.get("sig_name", display_name)
        sig_title   = sig_cfg.get("sig_title", "")
        sig_company = sig_cfg.get("sig_company", "")
        sig_phone   = sig_cfg.get("sig_phone", "")
        plain_signoff = f"\n\n--\n{sig_name}"
        if sig_title:
            plain_signoff += f"\n{sig_title}"
        if sig_company:
            plain_signoff += f" · {sig_company}"
        if sig_phone:
            plain_signoff += f"\n{sig_phone}"
        if plain_signoff.strip() not in plain_text_body:
            plain_text_body = plain_text_body + plain_signoff

    html_body = None
    if use_html:
        html_content = plain_text_body.replace("\n", "<br />\n")
        html_body = f'<div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333;">{html_content}</div>'

    body = plain_text_body

    # 4. Mode 1: Cloudflare Native Email Sending REST API (only when enabled and configured)
    cf_account_id = config.CF_ACCOUNT_ID or db.get_setting("cf_account_id", "")
    cf_api_token  = config.CF_API_TOKEN or db.get_setting("cf_api_token", "")
    if provider == "cloudflare_api" and cf_account_id and cf_api_token:
        logger.info(f"Dispatching via Cloudflare Email Sending API for {from_email}")
        res = send_via_cloudflare_api(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body=body,
            html_body=html_body,
            display_name=display_name
        )
        if res.get("success"):
            db.increment_account_sent(account["id"], is_alias=(acct_type == "alias"))
            return res
        else:
            logger.warning(f"Cloudflare API dispatch failed for {from_email}: {res.get('error')}. Falling back to SMTP.")

    # 5. Mode 2: SMTP2GO REST API
    if provider == "smtp2go_api" and smtp_pass:
        logger.info(f"Dispatching via SMTP2GO API for {from_email}")
        res = send_via_smtp2go_api(
            api_key=smtp_pass,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body=body,
            html_body=html_body,
            display_name=display_name
        )
        if res.get("success"):
            db.increment_account_sent(account["id"], is_alias=(acct_type == "alias"))
            return res

    # 6. Mode 3: Mailjet REST API
    if provider == "mailjet_api" and smtp_user and smtp_pass:
        logger.info(f"Dispatching via Mailjet API for {from_email}")
        res = send_via_mailjet_api(
            api_key=smtp_user,
            secret_key=smtp_pass,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body=body,
            html_body=html_body,
            display_name=display_name
        )
        if res.get("success"):
            db.increment_account_sent(account["id"], is_alias=(acct_type == "alias"))
            return res

    # 7. Mode 4: Google OAuth 2.0 Gmail API dispatch
    if (provider in ("gmail", "oauth") or acct_type == "gmail") and db.get_oauth_token(from_email):
        logger.info(f"Dispatching via Google OAuth2 Gmail API for {from_email}")
        res = google_auth.send_via_gmail_api(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body=body,
            display_name=display_name,
        )
        if res.get("success"):
            db.increment_account_sent(account["id"], is_alias=False)
            return res
        else:
            logger.warning(f"Google OAuth dispatch failed for {from_email}: {res.get('error')}. Falling back to SMTP.")

    # 8. Mode 5: SMTP dispatch (Brevo, Amazon SES, SMTP2GO, Mailjet, Gmail, Custom)
    default_hosts = {
        "brevo": "smtp-relay.brevo.com",
        "smtp2go": "mail.smtp2go.com",
        "mailjet": "in-v3.mailjet.com",
        "amazon_ses": db.get_setting("aws_ses_smtp_host", "email-smtp.us-east-1.amazonaws.com"),
        "gmail": "smtp.gmail.com",
        "namecheap": "mail.privateemail.com",
        "zoho": "smtp.zoho.com",
        "outlook": "smtp.office365.com",
        "sendgrid": "smtp.sendgrid.net",
    }
    target_host = account.get("smtp_host") or default_hosts.get(provider, "smtp.gmail.com")
    target_port = int(account.get("smtp_port") or (465 if provider == "namecheap" else 587))

    try:
        # Proper MIME formatting: use pure text/plain if no HTML, multipart/alternative only if HTML is present
        if html_body:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        else:
            msg = MIMEText(body, "plain", "utf-8")

        msg["From"]         = formataddr((display_name, from_email))
        msg["To"]           = to_email
        msg["Subject"]      = subject
        msg["Reply-To"]     = formataddr((display_name, from_email))
        msg["MIME-Version"] = "1.0"
        msg["Date"]         = formatdate(localtime=True)

        # If sending via alias — add Sender header only if smtp_user is a valid email and not external relay/API
        if from_email.lower() != smtp_user.lower() and "@" in smtp_user and provider not in ("amazon_ses", "brevo", "smtp2go", "mailjet", "sendgrid"):
            msg["Sender"] = formataddr((display_name, smtp_user))

        domain = from_email.split("@")[1] if "@" in from_email else "gmail.com"
        message_id = make_msgid(domain=domain)
        msg["Message-ID"] = message_id

        if extra_headers:
            for hk, hv in extra_headers.items():
                if hk not in msg:
                    msg[hk] = hv

        # Build SMTP connection (with optional proxy, port 465 SSL vs port 587 STARTTLS)
        active_node = None
        if not proxy_url and provider not in ("amazon_ses", "brevo", "smtp2go", "mailjet", "cloudflare_api"):
            # Route outbound outreach through smart IP rotator fleet pool (multi-node balancing)
            try:
                import ip_rotator
                active_node = ip_rotator.select_next_node()
                if active_node:
                    proxy_url = ip_rotator.build_proxy_url(active_node)
                    if proxy_url:
                        logger.info(f"🔄 Routing outreach email via IP Node #{active_node.get('id')} '{active_node.get('name')}' ({proxy_url})")
            except Exception as e:
                logger.warning(f"Failed resolving active IP node from rotator: {e}")

        smtp_conn = _make_smtp_connection(proxy_url, target_host=target_host, target_port=target_port)

        with smtp_conn as server:
            if target_port == 465:
                # Direct SSL connection (e.g. Namecheap Private Email or Amazon SES SSL)
                pass
            else:
                # STARTTLS connection (e.g. port 587 or 2525)
                server.ehlo()
                server.starttls()
                server.ehlo()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            # Determine proper envelope sender (MAIL FROM) for strict DMARC/SPF compliance
            envelope_sender = from_email if ("@" not in smtp_user or provider in ("amazon_ses", "brevo", "smtp2go", "mailjet", "sendgrid", "namecheap") or acct_type == "alias") else smtp_user
            server.sendmail(envelope_sender, [to_email], msg.as_string())

        if active_node and active_node.get("id"):
            try:
                import ip_rotator
                ip_rotator.record_send_and_maybe_rotate(active_node["id"])
            except Exception as e_rot:
                logger.warning(f"Error recording IP node send / auto-rotate: {e_rot}")

        db.increment_account_sent(account["id"], is_alias=(acct_type == "alias"))
        return {"success": True, "account_used": from_email, "message_id": message_id, "provider": provider}

    except smtplib.SMTPAuthenticationError as e:
        err_str = str(e)
        if "525" in err_str or "Unauthorized IP" in err_str:
            return {"success": False, "error": f"Brevo IP Security: Your sending IP is not authorized in Brevo dashboard. Add this IP under Brevo → Settings → Authorized IPs.", "account_used": from_email}
        return {"success": False, "error": f"Auth failed for {smtp_user}. Check SMTP password / API key.", "account_used": from_email}

    except smtplib.SMTPRecipientsRefused as e:
        code = list(e.recipients.values())[0][0] if e.recipients else 550
        error = f"Recipient refused ({code}): {to_email}"
        if code in BOUNCE_CODES and db.get_setting("bounce_blacklist", "1") == "1":
            db.add_to_blacklist(email=to_email, reason=f"SMTP bounce code {code}")
            lead = db.get_lead_by_email(to_email)
            if lead:
                db.blacklist_lead(lead["id"], f"SMTP bounce {code}")
            logger.warning(f"Auto-blacklisted {to_email} due to bounce {code}")
        return {"success": False, "error": error, "account_used": from_email, "bounce": True}

    except smtplib.SMTPException as e:
        return {"success": False, "error": f"SMTP error: {str(e)}", "account_used": from_email}

    except Exception as e:
        return {"success": False, "error": f"Send error: {str(e)}", "account_used": from_email}


def send_test_email(to_email: str, from_account_email: str = None, target_account: str = None) -> dict:
    """
    Sends a test email to verify mailbox deliverability, headers, and credentials.
    """
    import time
    start_t = time.time()

    from_account = from_account_email or target_account

    # Find account or pick next available
    account = None
    if from_account:
        target = from_account.strip().lower()
        # Check gmail accounts
        accs = db.get_all_accounts()
        for a in accs:
            if a["email"].lower() == target:
                account = {
                    "id": a["email"],
                    "type": "gmail",
                    "from_email": a["email"],
                    "smtp_user": a["email"],
                    "smtp_pass": a["app_password"],
                    "proxy_url": a["proxy_url"],
                    "display_name": a["label"] or _make_display_name(a["email"])
                }
                break

        # Check aliases
        if not account:
            aliases = db.get_all_aliases()
            for al in aliases:
                if al["alias"].lower() == target:
                    al_d = dict(al)
                    account = {
                        "id": al_d["alias"],
                        "type": "alias",
                        "from_email": al_d["alias"],
                        "smtp_user": al_d.get("custom_smtp_user") or al_d.get("smtp_user"),
                        "smtp_pass": al_d.get("custom_smtp_pass") or al_d.get("smtp_pass"),
                        "provider": al_d.get("routing_mode", "gmail_send_as"),
                        "routing_mode": al_d.get("routing_mode", "gmail_send_as"),
                        "smtp_host": al_d.get("smtp_host"),
                        "smtp_port": al_d.get("smtp_port"),
                        "proxy_url": None,
                        "display_name": al_d.get("display_name") or _make_display_name(al_d["alias"])
                    }
                    break

    if not account:
        account = db.get_next_available_account()

    if not account:
        return {"success": False, "error": "No active Gmail accounts or aliases available in database."}

    # Ultra-natural subject and body — mimics a real 1:1 human email
    # Ultra-natural subject and body — mimics a genuine 1:1 direct email
    import random
    subjects = [
        "Quick hello from Alex",
        "Quick question regarding your setup",
        "Connecting / brief note",
        "Introduction & hello",
    ]
    openers = [
        "Hi there,\n\nHope you're having a great week so far.",
        "Hello,\n\nHope all is well on your side.",
        "Hi,\n\nWanted to send a quick note your way.",
    ]
    closers = [
        "Looking forward to staying in touch.\n\nBest regards,",
        "Would love to connect when you have a moment.\n\nAll the best,",
        "Have a great rest of your day.\n\nWarmly,",
    ]
    subject = random.choice(subjects)
    body = (
        f"{random.choice(openers)}\n\n"
        f"Just wanted to reach out directly to say hello and see how things are going with your current projects.\n\n"
        f"{random.choice(closers)}"
    )

    email_id = db.log_email(None, account["from_email"], to_email, subject, body, "quick_test", "queued")
    tracking_token = db.create_tracking_token(email_id)
    result = send_email_now(to_email, subject, body, account, tracking_token=tracking_token)
    elapsed = round((time.time() - start_t) * 1000, 1)
    result["elapsed_ms"] = elapsed
    if result.get("success"):
        db.mark_email_sent(email_id, result.get("message_id"), account["from_email"])
        db.log_activity("test_email_sent", f"To: {to_email} | From: {account['from_email']}")
    else:
        db.mark_email_failed(email_id, result.get("error", "Test send error"))
    return result


def send_with_logging(lead_id: int, to_email: str, subject: str, body: str,
                      message_type: str = "opener", email_id: int = None) -> dict:
    """
    Pick account → send → log result.
    If email_id is given, updates existing queued record. Otherwise logs new.
    Returns: {success, email_id, account_used, message_id, queued, error}
    """
    # 0. Zero-Bounce Pre-Send Verification Shield
    try:
        verify_res = email_verifier.verify_lead_email(to_email, deep_smtp=False)
        if not verify_res["valid"]:
            db.update_lead_stage(lead_id, "bounced")
            db.add_to_blacklist(to_email, reason=f"Zero-Bounce shield: {verify_res.get('reason')}")
            logger.warning(f"Zero-Bounce shield blocked invalid email: {to_email} ({verify_res.get('reason')})")
            return {
                "success": False,
                "error": f"Zero-Bounce shield blocked: {verify_res.get('reason')}",
                "bounce": True,
                "suppressed": True
            }
    except Exception as e:
        logger.debug(f"Pre-check bypassed on exception: {e}")

    # 1. Mailbox Selection via MailboxPoolRouter
    account = outreach_engine.mailbox_pool.select_next_mailbox()
    if not account:
        account = db.get_next_available_account()

    if not account:
        # No capacity — just log as queued if not already logged
        if not email_id:
            email_id = db.log_email(lead_id, None, to_email, subject, body, message_type, "queued")
        return {
            "success": False,
            "queued": True,
            "email_id": email_id,
            "message": "All mailboxes at daily limit. Queued for tomorrow.",
        }

    # Normalize account dict (mailbox pool uses 'email', but send_email_now expects 'from_email')
    if account and "from_email" not in account:
        account["from_email"] = account.get("email", "")
        account["smtp_user"]  = account.get("smtp_user") or account.get("email", "")
        account["smtp_pass"]  = account.get("smtp_pass") or account.get("app_password", "")
        account["display_name"] = account.get("display_name") or account.get("label") or _make_display_name(account["from_email"])
        account["type"]       = account.get("type", "gmail")

    # Log as queued first (idempotent if already exists)
    if not email_id:
        email_id = db.log_email(lead_id, account["from_email"], to_email, subject, body, message_type, "queued")

    tracking_token = db.create_tracking_token(email_id)
    result = send_email_now(to_email, subject, body, account, tracking_token=tracking_token)

    # 2. Automatic Failover to backup mailbox if temporary SMTP rate-limit or auth failure
    if not result.get("success") and not result.get("bounce"):
        err_msg = result.get("error", "SMTP send error")
        outreach_engine.mailbox_pool.trigger_cooldown(account["from_email"], minutes=15, reason=err_msg)
        backup_account = outreach_engine.mailbox_pool.select_next_mailbox()
        if backup_account and backup_account["email"] != account["from_email"]:
            logger.info(f"Failing over dispatch from {account['from_email']} to backup {backup_account['email']}")
            result = send_email_now(to_email, subject, body, backup_account, tracking_token=tracking_token)
            if result.get("success"):
                account = backup_account

    if result["success"]:
        db.mark_email_sent(email_id, result.get("message_id"), account["from_email"])
        db.add_conversation_message(lead_id, "us", f"[{message_type.upper()}] Subject: {subject}\n\n{body}")
        db.log_activity("email_sent", f"To: {to_email} | Type: {message_type} | From: {account['from_email']}")
        return {
            "success": True,
            "email_id": email_id,
            "account_used": result["account_used"],
            "message_id": result.get("message_id"),
        }
    else:
        db.mark_email_failed(email_id, result.get("error", "Unknown error"))
        db.log_activity("email_failed", f"To: {to_email} | Error: {result.get('error')}")
        return {
            "success": False,
            "email_id": email_id,
            "error": result.get("error"),
        }


# ═══════════════════════════════════════════════════════════════
#                    PROXY SOCKET SUPPORT
# ═══════════════════════════════════════════════════════════════

def _make_smtp_connection(proxy_url: str | None, target_host: str = "smtp.gmail.com", target_port: int = 587) -> smtplib.SMTP:
    """Create SMTP connection, optionally routed through a proxy, supporting both SSL (465) and STARTTLS (587)."""
    if not proxy_url:
        if target_port == 465:
            return smtplib.SMTP_SSL(target_host, target_port, timeout=30)
        return smtplib.SMTP(target_host, target_port, timeout=30)

    parsed = urlparse(proxy_url)
    scheme = (parsed.scheme or "").lower()

    if scheme in ("socks5", "socks5h", "socks4"):
        try:
            import socks

            proxy_type = socks.SOCKS5 if scheme.startswith("socks5") else socks.SOCKS4
            host = parsed.hostname
            port = parsed.port or 1080
            username = parsed.username
            password = parsed.password

            # Create a custom socket via PySocks
            sock = socks.create_connection(
                (target_host, target_port),
                proxy_type=proxy_type,
                proxy_addr=host,
                proxy_port=port,
                proxy_username=username,
                proxy_password=password,
                timeout=30,
            )
            if target_port == 465:
                import ssl
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=target_host)
                conn = smtplib.SMTP_SSL(timeout=30)
                conn.sock = sock
                conn._host = target_host
                return conn
            else:
                conn = smtplib.SMTP(timeout=30)
                conn.sock = sock
                conn._host = target_host
                return conn
        except ImportError:
            logger.warning("PySocks not installed — ignoring SOCKS proxy, falling back to direct connection.")
            return smtplib.SMTP_SSL(target_host, target_port, timeout=30) if target_port == 465 else smtplib.SMTP(target_host, target_port, timeout=30)
        except Exception as e_sock:
            logger.warning(f"SOCKS proxy connect to {host}:{port} failed ({e_sock}) — falling back to direct connection.")
            return smtplib.SMTP_SSL(target_host, target_port, timeout=30) if target_port == 465 else smtplib.SMTP(target_host, target_port, timeout=30)

    elif scheme in ("http", "https"):
        # HTTP proxy via CONNECT tunnel
        try:
            proxy_host = parsed.hostname
            proxy_port = parsed.port or 3128
            sock = _http_proxy_connect(proxy_host, proxy_port, target_host, target_port,
                                       parsed.username, parsed.password)
            conn = smtplib.SMTP(timeout=30)
            conn.sock = sock
            conn._host = target_host
            return conn
        except Exception as e:
            logger.warning(f"HTTP proxy connect failed ({e}) — using direct connection")
            return smtplib.SMTP(target_host, target_port, timeout=30)

    # Unknown scheme — direct
    return smtplib.SMTP(target_host, target_port, timeout=30)


def _http_proxy_connect(proxy_host, proxy_port, target_host, target_port,
                        proxy_user=None, proxy_pass=None):
    """Establish CONNECT tunnel through HTTP proxy."""
    sock = socket.create_connection((proxy_host, proxy_port), timeout=30)
    connect_str = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n"
    if proxy_user and proxy_pass:
        import base64
        creds = base64.b64encode(f"{proxy_user}:{proxy_pass}".encode()).decode()
        connect_str += f"Proxy-Authorization: Basic {creds}\r\n"
    connect_str += "\r\n"
    sock.sendall(connect_str.encode())

    response = b""
    while True:
        chunk = sock.recv(4096)
        response += chunk
        if b"\r\n\r\n" in response:
            break

    status_line = response.split(b"\r\n")[0].decode()
    if "200" not in status_line:
        sock.close()
        raise ConnectionError(f"HTTP proxy CONNECT failed: {status_line}")

    return sock


# ═══════════════════════════════════════════════════════════════
#                         HELPERS
# ═══════════════════════════════════════════════════════════════

def _make_display_name(email: str) -> str:
    """Derive a display name from email address."""
    local = email.split("@")[0]
    # Clean up common patterns
    name = re.sub(r"[._\-+]", " ", local).title()
    return name.strip() or "Flinza"


def test_account_connection(email: str, app_password: str, smtp_host: str = "smtp.gmail.com", smtp_port: int = 587) -> dict:
    """Quick SMTP auth test without sending. Returns {success, error}."""
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email, app_password)
        return {"success": True}
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": f"Authentication failed for {email} on {smtp_host}. Check credentials."}
    except Exception as e:
        return {"success": False, "error": str(e)}
