"""
Flinza — Self-Hosted Free Email Tracking Engine
Handles 1x1 transparent open pixel generation, link click redirection,
and instant Telegram notifications upon lead activity.
"""

import base64
import logging
import re
import urllib.parse
from datetime import datetime

import config
import database as db

logger = logging.getLogger(__name__)

# 1x1 transparent PNG bytes
TRANSPARENT_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def get_tracking_base_url() -> str:
    return db.get_setting("tracking_base_url") or config.TRACKING_BASE_URL or "http://localhost:8000"


def generate_tracking_pixel_tag(tracking_token: str) -> str:
    """Generates the HTML <img> tag with the 1x1 tracking pixel."""
    base_url = get_tracking_base_url()
    pixel_url = f"{base_url}/t/o/{tracking_token}.png"
    return f'<img src="{pixel_url}" width="1" height="1" alt="" style="display:none !important;width:1px;height:1px;border:0;opacity:0;" />'


def wrap_links_in_body(body_html: str, tracking_token: str) -> str:
    """
    Wraps standard URLs in email HTML body with click tracking redirect links.
    Skips unsubscribe/mailto links.
    """
    base_url = get_tracking_base_url()

    def _replace_href(match):
        full_url = match.group(1)
        if "mailto:" in full_url.lower() or "unsubscribe" in full_url.lower() or "/t/c/" in full_url:
            return f'href="{full_url}"'
        encoded = urllib.parse.quote(full_url, safe="")
        tracking_url = f"{base_url}/t/c/{tracking_token}?target={encoded}"
        return f'href="{tracking_url}"'

    return re.sub(r'href=["\'](https?://[^"\']+)["\']', _replace_href, body_html, flags=re.IGNORECASE)


def handle_open(tracking_token: str, user_agent: str = None, ip: str = None, notify_cb=None) -> bytes:
    """
    Records an open event and optionally fires a Telegram notification.
    Returns the transparent PNG bytes.
    """
    try:
        data = db.record_email_open(tracking_token, user_agent=user_agent, ip=ip)
        if data and notify_cb:
            # Check if this is the first open to avoid spamming
            open_count = data.get("open_count", 1)
            if open_count == 1:
                notify_cb({
                    "type": "email_opened",
                    "to_email": data.get("to_email"),
                    "subject": data.get("subject"),
                    "lead_name": data.get("name") or "Unknown",
                    "company": data.get("company") or "Prospect",
                    "open_count": open_count,
                    "timestamp": datetime.now().strftime("%I:%M %p"),
                })
    except Exception as e:
        logger.error(f"Error recording email open: {e}")

    return TRANSPARENT_PNG_1X1


def handle_click(tracking_token: str, target_url: str, user_agent: str = None, ip: str = None, notify_cb=None) -> str:
    """
    Records a click event and returns the original target URL for redirection.
    """
    try:
        data = db.record_email_click(tracking_token, user_agent=user_agent, ip=ip)
        if data and notify_cb:
            click_count = data.get("click_count", 1)
            if click_count == 1:
                notify_cb({
                    "type": "email_clicked",
                    "to_email": data.get("to_email"),
                    "subject": data.get("subject"),
                    "lead_name": data.get("name") or "Unknown",
                    "company": data.get("company") or "Prospect",
                    "target_url": target_url,
                    "timestamp": datetime.now().strftime("%I:%M %p"),
                })
    except Exception as e:
        logger.error(f"Error recording email click: {e}")

    return target_url or "https://google.com"
