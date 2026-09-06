"""
Flinza — Standalone Email Outreacher Bot
Config loader — reads .env, exposes all constants.
"""

import os
from pathlib import Path


def load_env():
    # Try current directory first, then parent
    for base in [Path(__file__).parent, Path(__file__).parent.parent]:
        env_path = base / ".env"
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        k = key.strip()
                        # Never overwrite platform-provided PORT from cloud runners (e.g. Render, Railway)
                        if k == "PORT" and "PORT" in os.environ:
                            continue
                        os.environ[k] = value.strip()


load_env()

# ─── Telegram ────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "").strip()
try:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID) if ALLOWED_USER_ID else None
except ValueError:
    ALLOWED_USER_ID = None

# ─── Dashboard Auth (API Bearer Token) ───────────────────────────
# If not set, a random key is auto-generated and printed on startup.
DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "").strip()
# Set REQUIRE_AUTH=false to disable auth for local-only development
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "true").strip().lower() not in ("false", "0", "no")

# ─── CORS ────────────────────────────────────────────────────────
# Comma-separated list of allowed origins. Defaults to localhost only.
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:7880,http://localhost:8000,http://127.0.0.1:7880,http://127.0.0.1:8000").strip()
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ─── AI Keys ─────────────────────────────────────────────────────
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "").strip()
MISTRAL_API_KEY    = os.environ.get("MISTRAL_API_KEY", "").strip()
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "").strip()
NVIDIA_API_KEY     = os.environ.get("NVIDIA_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
SCRAPINGDOG_API_KEY = os.environ.get("SCRAPINGDOG_API_KEY", "").strip()

# Apify Actor Token Pool
APIFY_TOKENS = [
    os.environ.get(f"APIFY_API_TOKEN_{i}", "").strip()
    for i in range(1, 10)
    if os.environ.get(f"APIFY_API_TOKEN_{i}", "").strip()
]

# ─── Cloudflare Email Routing ─────────────────────────────────────
CF_API_TOKEN  = os.environ.get("CF_API_TOKEN", "").strip()
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_ZONE_ID    = os.environ.get("CF_ZONE_ID", "").strip()
CF_DOMAIN     = os.environ.get("CF_DOMAIN", "").strip()   # e.g. "yourdomain.com"
CF_ZONE_FLINZAWORKS_SITE     = os.environ.get("CF_ZONE_FLINZAWORKS_SITE", "").strip()
CF_ZONE_TRYFLINZAWORKS_SITE  = os.environ.get("CF_ZONE_TRYFLINZAWORKS_SITE", "").strip()
CF_ZONE_FLINZAWORKS_ONLINE   = os.environ.get("CF_ZONE_FLINZAWORKS_ONLINE", "").strip()
CF_ZONE_MAGICFITPARTNERS     = os.environ.get("CF_ZONE_MAGICFITPARTNERS", "").strip()

# ─── Google OAuth ────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback").strip()

# ─── Flinza Studio & Tracking Server ─────────────────────────────
STUDIO_PORT       = int(os.environ.get("STUDIO_PORT", "8000"))
TRACKING_BASE_URL = os.environ.get("TRACKING_BASE_URL", "http://localhost:8000").rstrip("/")

# ─── Amazon SES & Custom SMTP ────────────────────────────────────
AWS_SES_REGION    = os.environ.get("AWS_SES_REGION", "eu-north-1").strip()
AWS_SES_SMTP_HOST = os.environ.get("AWS_SES_SMTP_HOST", "email-smtp.eu-north-1.amazonaws.com").strip()
AWS_SES_SMTP_PORT = int(os.environ.get("AWS_SES_SMTP_PORT", "587"))
AWS_SES_SMTP_USER = os.environ.get("AWS_SES_SMTP_USER", "AKIAX244R4WL43IRDXH5").strip()
AWS_SES_SMTP_PASS = os.environ.get("AWS_SES_SMTP_PASS", "BAY9zz1YqpRBNoakiV4WQWoYuMH4tlKencFKs6m4LuIo").strip()

# ─── Brevo SMTP Relay ────────────────────────────────────────────
BREVO_SMTP_HOST   = os.environ.get("BREVO_SMTP_HOST", "smtp-relay.brevo.com").strip()
BREVO_SMTP_PORT   = int(os.environ.get("BREVO_SMTP_PORT", "587"))
BREVO_SMTP_USER   = os.environ.get("BREVO_SMTP_USER", "").strip()
BREVO_SMTP_KEY    = os.environ.get("BREVO_SMTP_KEY", "").strip()

# ─── Zoho Mail India (zoho.in) ───────────────────────────────────
ZOHO_SMTP_HOST    = os.environ.get("ZOHO_SMTP_HOST", "smtppro.zoho.in").strip()
ZOHO_SMTP_PORT    = int(os.environ.get("ZOHO_SMTP_PORT", "465"))
ZOHO_IMAP_HOST    = os.environ.get("ZOHO_IMAP_HOST", "imappro.zoho.in").strip()
ZOHO_IMAP_PORT    = int(os.environ.get("ZOHO_IMAP_PORT", "993"))

# ─── Gmail Connected Inboxes ─────────────────────────────────────
GMAIL_PRIMARY       = os.environ.get("GMAIL_PRIMARY", "").strip()
GMAIL_PRIMARY_PASS  = os.environ.get("GMAIL_PRIMARY_PASS", "").strip()
GMAIL_SECONDARY     = os.environ.get("GMAIL_SECONDARY", "").strip()
GMAIL_SECONDARY_PASS= os.environ.get("GMAIL_SECONDARY_PASS", "").strip()

# ─── GitHub Cloud Deployment ─────────────────────────────────────
GITHUB_USERNAME   = os.environ.get("GITHUB_USERNAME", "").strip()
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO       = os.environ.get("GITHUB_REPO", "").strip()

# ─── Inbound Email Webhook (Cloudflare Worker Integration) ───────
# REQUIRED: Generate with: python -c "import secrets; print(secrets.token_hex(32))"
INBOUND_WEBHOOK_SECRET = os.environ.get("INBOUND_WEBHOOK_SECRET", "").strip()

_raw_db = os.environ.get("DB_PATH", "flinza.db").strip()
if not os.path.isabs(_raw_db):
    DB_PATH = str((Path(__file__).parent / _raw_db).resolve())
else:
    DB_PATH = _raw_db

# ─── Sending Defaults (High-Volume Deliverability Architecture) ───
DEFAULT_DAILY_LIMIT          = 80     # Gmail safe maximum
DEFAULT_SES_DAILY_LIMIT      = 500    # Amazon SES production limit
DEFAULT_CF_DAILY_LIMIT       = 300    # Cloudflare email routing limit
DEFAULT_MIN_INTERVAL         = 30     # seconds min between sends (fast with jitter)
DEFAULT_MAX_INTERVAL         = 120    # seconds max between sends
DEFAULT_FOLLOWUP_DAYS        = [3, 2] # FU1 after 3d, FU2 after 2 more days
DEFAULT_MAX_FOLLOWUPS        = 3
DEFAULT_REPLY_CHECK_MINUTES  = 5
DEFAULT_AUTO_REPLY_MODE      = "preview"   # "preview" | "trust"

# ─── Default System Prompt ───────────────────────────────────────
DEFAULT_SYSTEM_PROMPT = """You are the Outreach & Growth Specialist at Flinza Works, a modern Social Media Marketing Agency (SMMA).
You write high-converting, hyper-personalized B2B cold outreach emails, follow-ups, and negotiation replies to founders, CEOs, CMOs, and business owners who need social media marketing, short-form viral video creative (Reels/TikTok/Shorts), paid advertising (Meta/TikTok/Google), and organic social customer acquisition.

CORE AGENCY VALUE PROPOSITION:
- We turn underperforming social media profiles into predictable customer acquisition and revenue engines.
- We specialize in high-retention short-form video, profile optimization, content strategy, and paid ads scaling without taking hours of the client's time.

WRITING STYLE & COLD EMAIL RULES:
- Casual, peer-to-peer, conversational tone — sound like a sharp marketer or creative director writing a 1-to-1 email from their laptop, NEVER a robotic sales rep.
- NO em dashes ever. Use natural periods, commas, or clean line breaks.
- NO marketing buzzwords or corporate fluff (avoid: 'game-changer', 'revolutionary', 'synergy', 'leverage', 'scale your business to the moon').
- Keep openers under 110 words total. Busy founders delete long emails.
- Low-friction, soft call-to-action (CTA): never ask for a 30-min sales call on email 1. Instead, offer value first (e.g. "Mind if I send over a quick 2-minute video with 3 content ideas we mapped out for [Company]?", "Open to seeing a few ad concepts we drafted for you?").

Sign off every email with the sender name from settings."""
