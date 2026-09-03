"""
Flinza — Google OAuth 2.0 & Gmail API Client
Handles Google sign-in, OAuth token exchange, automatic token refresh,
and direct sending via Gmail REST API.
"""

import base64
import json
import logging
import urllib.parse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
import requests

import config
import database as db

logger = logging.getLogger(__name__)

GOOGLE_AUTH_BASE   = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL   = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_SEND_URL     = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_google_auth_url(redirect_uri: str = None, state: str = "flinza_auth") -> str:
    """Generates the Google OAuth consent URL with offline access to get refresh token."""
    client_id = db.get_setting("google_client_id") or config.GOOGLE_CLIENT_ID
    if not client_id:
        return ""

    redirect = redirect_uri or db.get_setting("google_redirect_uri") or config.GOOGLE_REDIRECT_URI

    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, redirect_uri: str = None) -> dict:
    """
    Exchanges authorization code for access & refresh tokens,
    retrieves user email, and saves credentials in database.
    """
    client_id = db.get_setting("google_client_id") or config.GOOGLE_CLIENT_ID
    client_secret = db.get_setting("google_client_secret") or config.GOOGLE_CLIENT_SECRET
    redirect = redirect_uri or db.get_setting("google_redirect_uri") or config.GOOGLE_REDIRECT_URI

    if not client_id or not client_secret:
        return {"success": False, "error": "Google Client ID or Secret is not configured in settings."}

    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }

    try:
        resp = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=15)
        if resp.status_code != 200:
            return {"success": False, "error": f"Token exchange failed: {resp.text}"}

        tokens = resp.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        expiry = (datetime.now() + timedelta(seconds=expires_in)).isoformat()

        # Fetch user's email address
        headers = {"Authorization": f"Bearer {access_token}"}
        user_resp = requests.get(GOOGLE_USERINFO_URL, headers=headers, timeout=10)
        if user_resp.status_code != 200:
            return {"success": False, "error": "Failed to fetch Google user profile."}

        user_info = user_resp.json()
        email = user_info.get("email", "").lower().strip()
        google_id = user_info.get("id", "")

        if not email:
            return {"success": False, "error": "No email address associated with Google account."}

        # Save tokens in database
        db.save_oauth_token(
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            expiry=expiry,
            client_id=client_id,
            client_secret=client_secret,
            scopes=" ".join(SCOPES),
            provider="google",
        )

        # Auto-create or activate Gmail account in database
        db.add_account(email=email, app_password="[OAUTH2_MANAGED]", daily_limit=50)
        conn = db.get_db()
        conn.execute("UPDATE gmail_accounts SET active=1 WHERE email=?", (email,))
        conn.commit()
        conn.close()

        db.log_activity("oauth_connected", f"Google account connected: {email}")
        return {
            "success": True,
            "email": email,
            "name": user_info.get("name", ""),
            "picture": user_info.get("picture", ""),
            "google_id": google_id,
        }

    except Exception as e:
        logger.error(f"Error exchanging OAuth code: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def get_valid_access_token(account_email: str) -> str | None:
    """
    Retrieves a valid access token for the given account.
    If expired or close to expiry, automatically refreshes it using the refresh token.
    """
    token_record = db.get_oauth_token(account_email)
    if not token_record:
        return None

    expiry_str = token_record.get("token_expiry")
    needs_refresh = True
    if expiry_str:
        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if expiry_dt > datetime.now() + timedelta(minutes=5):
                needs_refresh = False
        except Exception:
            needs_refresh = True

    if not needs_refresh:
        return token_record.get("access_token")

    # Refresh the token
    refresh_token = token_record.get("refresh_token")
    if not refresh_token:
        logger.warning(f"No refresh token available for {account_email}")
        return token_record.get("access_token")

    client_id = token_record.get("client_id") or db.get_setting("google_client_id") or config.GOOGLE_CLIENT_ID
    client_secret = token_record.get("client_secret") or db.get_setting("google_client_secret") or config.GOOGLE_CLIENT_SECRET

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        resp = requests.post(GOOGLE_TOKEN_URL, data=data, timeout=15)
        if resp.status_code != 200:
            logger.error(f"Failed to refresh OAuth token for {account_email}: {resp.text}")
            return None

        new_tokens = resp.json()
        new_access = new_tokens.get("access_token")
        new_refresh = new_tokens.get("refresh_token") or refresh_token
        expires_in = new_tokens.get("expires_in", 3600)
        new_expiry = (datetime.now() + timedelta(seconds=expires_in)).isoformat()

        db.save_oauth_token(
            email=account_email,
            access_token=new_access,
            refresh_token=new_refresh,
            expiry=new_expiry,
            client_id=client_id,
            client_secret=client_secret,
            provider="google",
        )
        return new_access
    except Exception as e:
        logger.error(f"Exception refreshing OAuth token for {account_email}: {e}")
        return None


def send_via_gmail_api(from_email: str, to_email: str, subject: str, body: str,
                       display_name: str = None, message_id: str = None) -> dict:
    """
    Sends an email directly through the official Gmail REST API using OAuth2 access token.
    Fast, reliable, and bypasses SMTP port blocking.
    """
    access_token = get_valid_access_token(from_email)
    if not access_token:
        return {"success": False, "error": f"No valid OAuth2 token found for {from_email}. Sign in with Google first."}

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr((display_name or from_email.split("@")[0], from_email))
        msg["To"] = to_email
        msg["Subject"] = subject

        domain = from_email.split("@")[1] if "@" in from_email else "gmail.com"
        mid = message_id or make_msgid(domain=domain)
        msg["Message-ID"] = mid

        msg.attach(MIMEText(body, "plain", "utf-8"))

        raw_bytes = msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {"raw": raw_b64}

        resp = requests.post(GMAIL_SEND_URL, headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            res_json = resp.json()
            return {
                "success": True,
                "account_used": from_email,
                "message_id": mid,
                "gmail_msg_id": res_json.get("id"),
                "thread_id": res_json.get("threadId"),
            }
        elif resp.status_code == 401:
            # Token might be expired, force refresh once
            logger.info(f"Gmail API 401 for {from_email}, forcing token refresh and retry...")
            token_record = db.get_oauth_token(from_email)
            if token_record and token_record.get("refresh_token"):
                conn = db.get_db()
                conn.execute("UPDATE oauth_tokens SET token_expiry='2000-01-01' WHERE account_email=?", (from_email.lower(),))
                conn.commit()
                conn.close()
                fresh_token = get_valid_access_token(from_email)
                if fresh_token:
                    headers["Authorization"] = f"Bearer {fresh_token}"
                    retry_resp = requests.post(GMAIL_SEND_URL, headers=headers, json=payload, timeout=20)
                    if retry_resp.status_code == 200:
                        return {
                            "success": True,
                            "account_used": from_email,
                            "message_id": mid,
                            "gmail_msg_id": retry_resp.json().get("id"),
                        }

        return {
            "success": False,
            "error": f"Gmail API error ({resp.status_code}): {resp.text}",
            "account_used": from_email,
        }

    except Exception as e:
        logger.error(f"Error sending email via Gmail API: {e}", exc_info=True)
        return {"success": False, "error": str(e), "account_used": from_email}
