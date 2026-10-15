# Nexcloud.in VPS & Custom Domain Deployment Guide
## Deploying Flinza Bot & Web Studio to `dashboard.flinzamedia.com`

This guide walks you through deploying the complete Flinza platform on **Nexcloud.in** Linux VPS and connecting your domain **`dashboard.flinzamedia.com`** with free SSL/TLS encryption.

---

## 📋 Overview of What Runs on Your Server

| Service | Port / Process | Function |
|---|---|---|
| **FastAPI Web Studio** | `http://127.0.0.1:7880` (Uvicorn) | Visual CRM, leads table, email preview modal, analytics, campaign controls |
| **Telegram Bot** | `bot.py` background process | Full Telegram mobile remote control (/stats, /start_campaign, /daily_report, /test_send, /leads, etc.) |
| **Nginx Reverse Proxy** | Ports `80` (HTTP) & `443` (HTTPS) | Routes `https://dashboard.flinzamedia.com` to `127.0.0.1:7880` with SSL |
| **Certbot (Let's Encrypt)** | Automated SSL | Free auto-renewing SSL certificate |

---

## STEP 1: Point Your Domain DNS (dashboard.flinzamedia.com)

In your DNS provider (Cloudflare, Namecheap, GoDaddy, Hostinger, etc.):

1. Get your **Public IPv4 address** from the Nexcloud.in dashboard (e.g. `123.45.67.89`).
2. Add an **A Record**:
   - **Type**: `A`
   - **Name / Host**: `dashboard` (or `dashboard.flinzamedia.com`)
   - **IPv4 Address**: `YOUR_NEXCLOUD_SERVER_IP`
   - **TTL**: `Auto` or `300 seconds`
   - **Proxy status**: If using Cloudflare, set to **DNS Only** (grey cloud) during SSL generation, or **Proxied** (orange cloud) with SSL mode set to **Full**.

---

## STEP 2: Connect to Your Nexcloud.in VPS

Open your terminal or SSH client:

```bash
ssh root@YOUR_NEXCLOUD_SERVER_IP
```

Update your packages:

```bash
apt update && apt upgrade -y
apt install -y git python3 python3-pip python3-venv nginx certbot python3-certbot-nginx curl ufw
```

Configure firewall:

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

---

## STEP 3: Clone the Repository & Setup Virtual Environment

```bash
cd /opt
git clone https://github.com/rajdeep09-dev/flinza-bot.git flinza
cd /opt/flinza

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install all dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install uvicorn fastapi python-telegram-bot
```

---

## STEP 4: Configure Your Production Environment (.env)

Create your `/opt/flinza/.env` file:

```bash
nano /opt/flinza/.env
```

Paste your production variables:

```env
# ─── Server Configuration ───────────────────────────────────
PORT=7880
HOST=127.0.0.1
STUDIO_PORT=7880
DB_PATH=flinza.db
DASHBOARD_PUBLIC_URL=https://dashboard.flinzamedia.com
ALLOWED_ORIGINS=https://dashboard.flinzamedia.com,http://dashboard.flinzamedia.com,http://127.0.0.1:7880

# ─── Dashboard Authentication ───────────────────────────────
REQUIRE_AUTH=true
DASHBOARD_LOGIN_EMAIL=admin@flinzamedia.com
DASHBOARD_LOGIN_PASSWORD=YourSecurePassword123!
DASHBOARD_API_KEY=flinza_master_prod_key_9988

# ─── Telegram Bot Control ───────────────────────────────────
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ALLOWED_USER_ID=YOUR_TELEGRAM_NUMERIC_USER_ID

# ─── AI Engine API Keys ─────────────────────────────────────
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GROQ_API_KEY=YOUR_GROQ_API_KEY
OPENROUTER_API_KEY=

# ─── Spacemail Fleet ────────────────────────────────────────
SPACEMAIL_SMTP_HOST=mail.spacemail.com
SPACEMAIL_SMTP_PORT=465
SPACEMAIL_IMAP_HOST=mail.spacemail.com
SPACEMAIL_IMAP_PORT=993
```

---

## STEP 5: Seed All 406 Leads & Templates into the Database

Run the automated seeder inside the virtual environment:

```bash
cd /opt/flinza
source venv/bin/activate
python3 populate_real_leads_and_templates.py
```

You should see:
```text
🎯 ACCURATE DATA IMPORT COMPLETE
  • Total leads in CRM : 406
  • 100% Verified      : 406
  • ⭐ Tier 1 (Next Send): 141
  • Tier 2 (Secondary) : 215
  • Tier 3 (Backup)    : 50
```

---

## STEP 6: Configure Nginx Reverse Proxy

Create the Nginx site configuration for `dashboard.flinzamedia.com`:

```bash
nano /etc/nginx/sites-available/dashboard.flinzamedia.com
```

Paste this configuration:

```nginx
server {
    listen 80;
    server_name dashboard.flinzamedia.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:7880;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket & long-polling timeouts
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
```

Enable the configuration and reload Nginx:

```bash
ln -s /etc/nginx/sites-available/dashboard.flinzamedia.com /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

---

## STEP 7: Generate Free SSL with Certbot

Run Certbot to issue and install an SSL certificate:

```bash
certbot --nginx -d dashboard.flinzamedia.com --non-interactive --agree-tos -m admin@flinzamedia.com --redirect
```

Certbot will automatically update your Nginx config with HTTPS redirects and set up an automatic renewal timer.

---

## STEP 8: Create Systemd Background Services

### 1. Web Studio Service (`/etc/systemd/system/flinza-web.service`)

```bash
nano /etc/systemd/system/flinza-web.service
```

Paste:

```ini
[Unit]
Description=Flinza Web Studio & CRM Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/flinza
EnvironmentFile=/opt/flinza/.env
ExecStart=/opt/flinza/venv/bin/uvicorn web_server:app --host 127.0.0.1 --port 7880 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2. Telegram Bot Service (`/etc/systemd/system/flinza-bot.service`)

```bash
nano /etc/systemd/system/flinza-bot.service
```

Paste:

```ini
[Unit]
Description=Flinza Telegram Autonomous Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/flinza
EnvironmentFile=/opt/flinza/.env
ExecStart=/opt/flinza/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## STEP 9: Enable and Start All Services

```bash
# Reload systemd daemon
systemctl daemon-reload

# Enable to start on server boot
systemctl enable flinza-web flinza-bot

# Start both services
systemctl start flinza-web
systemctl start flinza-bot

# Check status
systemctl status flinza-web --no-pager
systemctl status flinza-bot --no-pager
```

---

## 📱 Telegram Bot Command Reference

You can control the entire CRM and sending engine from your phone via Telegram:

| Command | Action |
|---|---|
| `/stats` | View real-time leads, sent emails, remaining daily quota, fleet health |
| `/daily_report` | Executive daily summary (leads, sent, queued, replies, active engines) |
| `/start_campaign` | Starts outbound email sending queue |
| `/stop_campaign` | Stops / pauses sending queue |
| `/launch` | Launches campaign confirmation dialog with pending leads |
| `/leads` | Displays latest leads in CRM |
| `/leads new` | Filters and displays leads in `new` stage |
| `/pipeline` | Visual funnel breakdown by stage |
| `/test_send <email>` | Sends live test email from next mailbox rotation |
| `/add_lead <email> [Name] [Company]` | Quickly adds lead directly to the CRM (e.g. `/add_lead john@brand.com John BrandCo`) |
| `/blacklist <email_or_domain>` | Instantly blacklists lead/domain and aborts pending follow-ups |
| `/accounts` | Lists all 29 Spacemail accounts with daily quotas and health |
| `/replies` | Lists unhandled prospect replies |
| `/checkreplies` | Forces an immediate IMAP check for new prospect replies |
