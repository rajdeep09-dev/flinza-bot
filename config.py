"""
Flinza — Standalone Email Outreacher Bot
Config loader — reads .env, exposes all constants.
"""

import os
from pathlib import Path


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


load_env()

# ─── Telegram ────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "").strip()
try:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID) if ALLOWED_USER_ID else None
except ValueError:
    ALLOWED_USER_ID = None

# ─── AI Keys ─────────────────────────────────────────────────────
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "").strip()
MISTRAL_API_KEY    = os.environ.get("MISTRAL_API_KEY", "").strip()
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "").strip()
NVIDIA_API_KEY     = os.environ.get("NVIDIA_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# ─── Cloudflare Email Routing ─────────────────────────────────────
CF_API_TOKEN  = os.environ.get("CF_API_TOKEN", "").strip()
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_ZONE_ID    = os.environ.get("CF_ZONE_ID", "").strip()
CF_DOMAIN     = os.environ.get("CF_DOMAIN", "").strip()   # e.g. "yourdomain.com"

# ─── Google OAuth ────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback").strip()

# ─── Flinza Studio & Tracking Server ─────────────────────────────
STUDIO_PORT       = int(os.environ.get("STUDIO_PORT", "8000"))
TRACKING_BASE_URL = os.environ.get("TRACKING_BASE_URL", "http://localhost:8000").rstrip("/")

# ─── Amazon SES & Custom SMTP ────────────────────────────────────
AWS_SES_REGION    = os.environ.get("AWS_SES_REGION", "us-east-1").strip()
AWS_SES_SMTP_HOST = os.environ.get("AWS_SES_SMTP_HOST", "email-smtp.us-east-1.amazonaws.com").strip()
AWS_SES_SMTP_PORT = int(os.environ.get("AWS_SES_SMTP_PORT", "587"))
AWS_SES_SMTP_USER = os.environ.get("AWS_SES_SMTP_USER", "").strip()
AWS_SES_SMTP_PASS = os.environ.get("AWS_SES_SMTP_PASS", "").strip()

# ─── Inbound Email Webhook (Cloudflare Worker Integration) ───────
INBOUND_WEBHOOK_SECRET = os.environ.get("INBOUND_WEBHOOK_SECRET", "flinza_cf_inbound_secret_2026").strip()

# ─── Database ────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "flinza.db")

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
