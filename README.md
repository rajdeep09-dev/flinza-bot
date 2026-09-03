# ⚡ Flinza — The God-Mode AI Cold Email Machine in Your Pocket

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-2CA5E0?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Cloudflare Ready](https://img.shields.io/badge/Cloudflare-Tunnels%20%26%20Email%20Routing-F38020?logo=cloudflare&logoColor=white)](https://www.cloudflare.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Self-Hosted](https://img.shields.io/badge/100%25-Free%20%26%20Open%20Source-purple.svg)](#)

**Scale your agency cold email outreach to thousands of verified leads with zero monthly subscription fees.**  
*Operate everything 100% remotely from Telegram or the Mailflare-inspired Webmail Mini App.*

[🚀 Quick Start](#-beginner-quick-start-3-minutes) • [✨ Superpowers](#-what-makes-flinza-so-insanely-powerful) • [🔀 Outbound Routing](#-the-3-tier-outbound-dispatch-architecture) • [📖 Telegram Commands](#-telegram-bot-command-cheat-sheet) • [🌐 Free Cloudflare Hosting](#-100-free-hosting-on-cloudflare)

</div>

---

## 💡 What is Flinza?

Most outreach platforms (Instantly, Lemlist, Smartlead) charge **$40 to $150+ every single month** just for basic sending caps and limited inboxes.

**Flinza flips the script.** It is a complete, self-hosted cold outreach engine that you run locally or on a free server. It connects to your Telegram account, meaning **you can manage, launch, inspect, and reply to client acquisition campaigns right from your phone while drinking coffee.**

```
       ┌───────────────────────────────────────────────────────────┐
       │              YOU (Telegram Mobile App)                   │
       └─────────────────────────────┬─────────────────────────────┘
                                     │ (Commands & Mini App)
                                     ▼
       ┌───────────────────────────────────────────────────────────┐
       │                  ⚡ FLINZA ENGINE CORE                    │
       │                                                           │
       │  ┌────────────────────┐          ┌─────────────────────┐  │
       │  │  AI Smart Brain    │          │ Mailflare Web Studio│  │
       │  │ (Gemini, Groq, LLM)│          │  (Priority Inbox)   │  │
       │  └─────────┬──────────┘          └──────────┬──────────┘  │
       └────────────┼────────────────────────────────┼─────────────┘
                    │                                │
                    ▼                                ▼
       ┌───────────────────────────────────────────────────────────┐
       │             MULTI-ROUTE OUTBOUND DISPATCH                 │
       │                                                           │
       │  [Mode 1: Free Gmail]  [Mode 2: Cloudflare]  [Mode 3: SES]│
       │   alex@domain.com       team@domain.com      ops@domain   │
       │     (via Gmail SMTP)      (Edge REST API)     (AWS SMTP)  │
       └─────────────────────────────┬─────────────────────────────┘
                                     │
                                     ▼
                            📬 Prospect Inbox
```

---

## 🌟 What Makes Flinza So Insanely Powerful?

### 1. 📱 100% Telegram Remote Control
You don't need to sit glued to a laptop. Your entire cold email operation is managed through an interactive, button-based Telegram bot:
- **Instant Reply Alerts**: As soon as a prospect replies, Flinza pings your phone with the full message.
- **One-Tap Actions**: Launch campaigns, pause the queue, test inbox deliverability, or view analytics directly from chat keyboards.
- **Embedded Web Studio**: Type `/studio` in Telegram, and the full Mailflare Webmail interface opens natively inside Telegram as a Telegram Mini App!

---

### 2. 🔀 Dynamic Multi-Provider Routing (Never Get Burned)
Unlike other tools that lock you into one sending method, Flinza lets you create **unlimited custom domain aliases** (e.g. `alex@yourdomain.com`, `sarah@yourdomain.com`) and choose how each one sends:

| Mode | Provider | Cost | Why Use It? |
|---|---|---|---|
| **Mode 1** | **✉️ Gmail Send-As Relay** | **100% Free** | Connect one master Gmail account and send emails disguised as any custom domain alias. Zero extra setup. |
| **Mode 2** | **⚡ Cloudflare Native API** | **$5/month (Flat)** | Sends through Cloudflare Workers Edge API. No SMTP credentials needed, ultra-fast, and completely separate from Google. |
| **Mode 3** | **🚀 Amazon SES / Dedicated SMTP** | **$0.10 / 1,000 emails** | Enterprise tier. Scale to 50,000+ emails per day at penny-level costs with domain-level DKIM verification. |

> 💡 **You can mix and match!** Have 5 aliases sending through Gmail, 5 through Cloudflare, and 10 through Amazon SES all in the same campaign.

---

### 3. 🤖 Autonomous AI Negotiation & Objection Handler
Flinza doesn't just send emails—it handles the conversation for you:
- Powered by your choice of **Google Gemini, Groq, Mistral, OpenRouter, or Local Ollama/vLLM**.
- Detects prospect intent automatically: `Interested`, `Meeting Requested`, `Not Right Now`, `Price Objection`, or `Unsubscribe`.
- When a prospect asks a question (e.g. *"How much do you charge?"* or *"Can you send a portfolio?"*), Flinza **pre-drafts a persuasive, tailored reply**.
- You can review the AI draft in Telegram or Webmail and click **🚀 Send This Reply** with a single tap!

---

### 4. 📬 Mailflare Priority Webmail Client
Inspired by modern interfaces like Mailflare and Superhuman:
- **Pill Compose Modal**: Quick email compose dialog with custom sender dropdown and rich formatting.
- **Priority Inbox**: Clean, clutter-free list separating positive prospect responses from auto-replies and bounces.
- **Dual Theme Switcher**: 1-click toggle between ultra-clean Mailflare Light Mode (`#f3f6fc`) and sleek Dark Mode.
- **Live Search**: Instant keyword filtering across prospect names, emails, and conversation history.

---

### 5. 🛡️ Bulletproof Deliverability Shield
Stop landing in the dreaded spam folder. Flinza protects your sender reputation with:
- **SPF, DKIM & DMARC Auditor**: Checks your DNS health before you send a single message.
- **Humanized Jitter**: Randomized delays between sends (e.g. 120–420 seconds) to perfectly mimic human behavior.
- **Smart Sending Hours**: Automatically restricts sending to business hours (9:00 AM – 6:00 PM) in your target timezone.
- **Warmup Velocity Ramp**: Gradually scales up sending caps so new mailboxes never trigger provider spam filters.

---

## ⏱️ Beginner Quick Start (3 Minutes)

You don't need to be a developer to get Flinza running. Just follow these 3 simple steps:

### Step 1: Clone the Repo & Install
```bash
git clone https://github.com/rajdeep09-dev/flinza-bot.git
cd flinza-bot
pip install -r requirements.txt
```

### Step 2: Configure Your `.env`
Copy the example file:
```bash
cp .env.example .env
```
Open `.env` in any text editor and fill in your details:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
ALLOWED_USER_ID=your_telegram_numeric_id
GEMINI_API_KEY=your_free_gemini_api_key
```
*(Need a free Gemini key? Grab one in 30 seconds at [aistudio.google.com](https://aistudio.google.com/))*

### Step 3: Start the Bot & Web Studio
Open two terminal windows:

**Terminal 1 (Web Studio on port 8000):**
```bash
python web_server.py
```

**Terminal 2 (Telegram Bot):**
```bash
python bot.py
```

Open your Telegram app, message your bot, and send `/start`. **You're in! 🎉**

---

## 📱 Telegram Bot Command Cheat-Sheet

| Command | Action | Description |
|---|---|---|
| `/start` | 🏠 Main Dashboard | Opens the interactive main menu with quick-action buttons |
| `/studio` | 🖥️ Open Web Studio | Opens the Mailflare Webmail Mini App inside Telegram |
| `/seturl <url>` | 🔗 Set Mini App URL | Binds your public HTTPS domain (e.g. Cloudflare tunnel) to the bot |
| `/help` | 📖 Help & Guides | Shows the complete command list and beginner tutorial |
| `/stats` | 📊 Real-Time Metrics | Displays emails sent today, open rate %, click rate %, and unhandled replies |
| `/leads` | 👥 Leads CRM | View leads count, import prospects, or filter by funnel stage |
| `/mailboxes` | 📬 Mailbox Fleet | Inspect connected Gmail accounts and custom domain aliases |
| `/campaign` | 🚀 Campaign Hub | Launch campaign, pause queue, or test sending speed |
| `/unibox` | 💬 Inbound Triage | Review prospect replies and dispatch AI-crafted responses |
| `/settings` | ⚙️ Agency Settings | Adjust sending intervals, humanized jitter, and sender names |

---

## 🌐 100% Free Hosting on Cloudflare

Want your Web Studio accessible everywhere with a real custom domain (e.g. `studio.yourdomain.com`) and zero server costs?

Flinza includes full support for **Cloudflare Tunnels (`cloudflared`)**:
- **$0 forever** (unlimited bandwidth).
- **Free Automatic SSL** (valid HTTPS certificate required for Telegram Mini Apps).
- **Zero open ports** or port forwarding needed on your router.

👉 **Read the full step-by-step tutorial**: [CLOUDFLARE_DOMAIN_SETUP.md](CLOUDFLARE_DOMAIN_SETUP.md)

---

## 📁 Project Architecture

```
flinza-bot/
├── bot.py                     # Telegram Bot logic, conversational menus & handlers
├── web_server.py              # FastAPI Web Studio & REST API backend (Port 7880/8000)
├── outreach_engine.py         # Billion-Dollar Outreach Engine (Spintax, Warmup, Deliverability, CLI)
├── database.py                # SQLite database engine, migrations & CRM queries
├── email_sender.py            # Universal outbound sender (Gmail, CF API, AWS SES)
├── email_queue.py             # Dispatch queue with randomized delay & jitter
├── followup_scheduler.py      # Multi-step drip campaign scheduler
├── reply_watcher.py           # Inbound IMAP poller & AI intent classifier
├── ai_router.py               # AI engine (Gemini, Groq, Mistral, Ollama, DeepSeek)
├── cloudflare_aliases.py      # Cloudflare Email Routing & DNS deliverability auditor
├── test_verification.py       # Full automated E2E test verification suite
├── templates/
│   └── index.html             # Billion-Dollar Web Studio SPA (Warmup, Lab, Terminal, CRM)
├── static/
│   ├── css/studio.css         # Dark & Light Glassmorphism Studio Design System
│   └── js/app.js              # Reactive SPA engine, tabs, & live terminal runner
├── CLOUDFLARE_DOMAIN_SETUP.md # Free Cloudflare Tunnel & custom domain setup guide
└── requirements.txt           # Python dependencies
```

---

## ⚡ Billion-Dollar Growth Architecture (Smartlead-Grade Power)

| Tool | Capability | How It Works |
|---|---|---|
| **🔥 Auto-Warmup Ramp** | Smart Mailbox Health | Automated ramp curve (5 → 50/day), health scoring (A-F), bounce rate guardrail |
| **🧪 Spintax & A/B Lab** | High Reply Rates | `{Hi\|Hello} {name}` permutation tester with live combinatorial analysis |
| **🛡️ Deliverability Scorer** | Zero Spam Inboxes | Real-time spam word detector, SPF/DKIM/DMARC auditor, deliverability dial (0-100) |
| **💻 Interactive Web Terminal** | Remote Dev Control | Execute commands directly in browser (`/stats`, `/warmup`, `/leads`, `/queue`) |
| **⚡ Smartlead Webhook** | Sync Outreach | Direct bi-directional integration (`/webhook/smartlead`) for external campaigns |

---

## 🤝 Need Help or Want to Contribute?

- **Issues & Suggestions**: Feel free to open an issue or pull request!
- **Star the Repo**: If Flinza helps your agency close more deals, drop a ⭐️ on the repository!

---

<div align="center">
  <sub>Built with ❤️ for modern agencies, founders, and outreach assassins.</sub>
</div>
