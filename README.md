# ⚡ Flinza Enterprise Cold Email Outreacher & Infrastructure Suite

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-2CA5E0?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Cloudflare Ready](https://img.shields.io/badge/Cloudflare-Email%20Routing%20%26%20Tunnels-F38020?logo=cloudflare&logoColor=white)](https://www.cloudflare.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Flinza** is a production-grade, AI-driven Cold Email Outreach Infrastructure & Telegram Bot Suite designed specifically for agencies (SMMA) and high-volume outreach teams. It pairs a **conversational Telegram Bot** with a **Mailflare-inspired Webmail Mini App Studio**, enabling multi-inbox rotation, dynamic dispatch routing, autonomous reply triage, and deliverability safeguarding.

---

## 🌟 Key Features

### 1. 📬 Mailflare Priority Webmail Client
- **Pill Compose Modal**: Modern quick-compose dialog with sender selection and instant dispatch.
- **Priority Inbox**: Clean list of inbound replies, AI drafts, sent campaigns, and suppressed threads.
- **AI Negotiation Drawer**: Automatically reads incoming prospect questions, crafts context-aware objection-handling replies, and allows 1-click dispatch.
- **Dual-Theme Engine**: Seamless switching between clean Mailflare Light Mode and dark mode.

### 2. 🔀 Flexible Outbound Dispatch Routing Architecture
Every custom domain alias can be individually routed to any sending provider:
- **Mode 1: ✉️ Gmail Send-As Relay**: Route alias through a master Gmail mailbox using verified `Sender` headers. Zero additional costs.
- **Mode 2: ⚡ Cloudflare Native Sending API**: Send directly through Cloudflare Workers Edge REST API ($5/mo Workers Paid plan).
- **Mode 3: 🚀 Amazon SES / Dedicated SMTP**: High-volume agency scale ($0.10 / 1,000 emails) via AWS SES or any external SMTP server.

### 3. 🤖 Intelligent Telegram Bot
- **Full Remote Management**: Control campaigns, monitor stats, test delivery, and triage replies directly from Telegram.
- **Beginner Quick-Start Guide**: Interactive 3-step onboarding tutorial inside the bot keyboard.
- **Mini App Integration**: Launch the Web Studio directly inside Telegram using Telegram Web Apps (`/studio`).
- **Real-Time Reply Notifications**: Instant Telegram alerts whenever a prospect responds.

### 4. 🛡️ Enterprise Cold Email Deliverability
- **SPF, DKIM & DMARC Auditing**: 1-click health check for your sending domains.
- **Warmup Velocity Curve**: Gradually ramps up sending limits to protect domain reputation.
- **Humanized Jitter & Delays**: Configurable delays (e.g. 120s–420s) with natural jitter to mimic human sending patterns.
- **Open & Click Tracking**: Built-in 1x1 transparent tracking pixel and redirect engine.

---

## 🚀 Quick Start Guide

### 1. Clone the Repository
```bash
git clone https://github.com/rajdeep09-dev/flinza-bot.git
cd flinza-bot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your values:
```bash
cp .env.example .env
```

Key variables:
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token from [@BotFather](https://t.me/BotFather)
- `ALLOWED_USER_ID`: Your Telegram numeric User ID
- `GEMINI_API_KEY` (or `GROQ_API_KEY`, etc.): AI engine for personalization and autonomous reply drafts
- `CF_API_TOKEN`: Cloudflare API token (optional, for alias generation and DNS audits)

### 4. Run the Web Studio & Telegram Bot
```bash
# Start Webmail & Studio Server (port 8000)
python web_server.py

# In a separate terminal, start the Telegram Bot
python bot.py
```

Open `http://localhost:8000` in your browser to access the Studio.

---

## 🌐 100% Free Hosting with Cloudflare Tunnels

To host Flinza 100% free with unlimited bandwidth and automatic SSL for Telegram Mini App usage, see:
📖 **[CLOUDFLARE_DOMAIN_SETUP.md](CLOUDFLARE_DOMAIN_SETUP.md)**

Quick 1-command temporary HTTPS tunnel:
```bash
npx cloudflared tunnel --url http://localhost:8000
```
Then run `/seturl <your-https-tunnel-url>` in the Telegram Bot!

---

## 📁 Project Structure

```
flinza-bot/
├── bot.py                     # Telegram Bot controller & keyboards
├── web_server.py              # FastAPI Web Studio & REST API
├── database.py                # SQLite schema, migrations & CRM queries
├── email_sender.py            # Outbound sender (Gmail, CF API, SES/SMTP)
├── email_queue.py             # Asynchronous dispatch queue with jitter
├── followup_scheduler.py      # Automated drip follow-up scheduler
├── reply_watcher.py           # Inbound IMAP polling & AI reply triaging
├── ai_router.py               # AI provider hub (Gemini, Groq, Mistral, Ollama)
├── cloudflare_aliases.py      # Cloudflare Email Routing & DNS auditor
├── templates/
│   └── index.html             # Mailflare-inspired Single Page Webmail App
├── static/
│   ├── css/studio.css         # Modern Light/Dark design system
│   └── js/app.js              # Reactive SPA client
├── CLOUDFLARE_DOMAIN_SETUP.md # Free hosting & custom domain setup guide
└── requirements.txt           # Python package requirements
```

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
