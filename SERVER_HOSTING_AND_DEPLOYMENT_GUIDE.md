# Flinza Outreach OS — Universal Server Hosting & Deployment Guide

This guide details everything required to host and run **Flinza Outreach OS** on any cloud server or panel featuring a **"Start Server"** button (Nexcloud, Pterodactyl, cPanel Python App, Docker, or traditional Linux VPS).

---

## 1. Hosting Architecture Overview

When you deploy Flinza on your server:
1. The server panel executes a single entrypoint: `python app.py`.
2. **`app.py`** automatically:
   - Checks and runs SQLite database migrations (`flinza.db`).
   - Detects the server's public IP address via Cloudflare/ipify API.
   - Spawns the Telegram Bot daemon thread (with remote VPS execution via `/runcmd`).
   - Starts the Uvicorn Web Server on `0.0.0.0:7880` (memory footprint: ~150MB RAM).
   - **Immediately sends a Telegram confirmation alert to your phone** with the live dashboard URL: `http://<server-ip>:7880`.

---

## 2. Server Requirements

- **Recommended Plan**: **GR Silver** (₹150/mo, 2GB RAM, 4GB SSD, 1.5v CPU) or standard 1GB/2GB Linux Python instance.
- **Python Version**: Python 3.10, 3.11, or 3.12.
- **Outbound Network**: Standard HTTP/HTTPS (ports 80, 443) and SMTP (ports 587, 465).

---

## 3. Step-by-Step Server Panel Deployment

### Step 1: Upload Project Files to Server
Upload the project files to the root directory of your server panel using File Manager, SFTP, or Git:
```
flinza/
├── app.py                     <-- Main 1-Click Entrypoint
├── web_server.py              <-- FastAPI Outreach Studio
├── database.py                <-- SQLite Database Engine & Multi-Relay Logic
├── email_sender.py            <-- SES & Brevo Dispatch Engine
├── config.py                  <-- Environment & Key Loader
├── requirements.txt           <-- Python Package Dependencies
├── .env                       <-- Production Environment Variables & Secrets
├── flinza.db                  <-- Active SQLite Database (21 Aliases & Routing)
├── static/                    <-- CSS, JS, Assets
└── templates/                 <-- Studio Dashboard HTML
```

### Step 2: Configure Environment Variables (`.env`)
Create or edit `.env` in the root folder of your server with your API keys and tokens:
```env
# ─── Telegram Bot & Admin ───────────────────────────────────────
TELEGRAM_BOT_TOKEN=8915115375:AAEwLYIoeKTNmuZa6rZrXFe4-AcOnlYXSyk
ALLOWED_USER_ID=6642913680

# ─── Server Port & Host ─────────────────────────────────────────
PORT=7880
HOST=0.0.0.0

# ─── Amazon SES Production Credentials (Stockholm eu-north-1) ───
AWS_SES_REGION=eu-north-1
AWS_SES_SMTP_HOST=email-smtp.eu-north-1.amazonaws.com
AWS_SES_SMTP_PORT=587
AWS_SES_SMTP_USER=AKIAX244R4WL43IRDXH5
AWS_SES_SMTP_PASS=BAY9zz1YqpRBNoakiV4WQWoYuMH4tlKencFKs6m4LuIo

# ─── AI Intent & Reply Models ───────────────────────────────────
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

### Step 3: Install Dependencies
In the panel's terminal or package manager, run:
```bash
pip install -r requirements.txt
```

### Step 4: Configure the "Start Server" Button
In your server panel settings:
- **Startup File / Main Script**: Set to `app.py`.
- **Startup Command**: `python app.py` (or `python3 app.py`).
- **Port**: `7880`.

### Step 5: Click "Start Server"
Click the green **"Start"** button on your hosting panel!

---

## 4. What Happens When the Server Starts

Within 3 seconds of clicking **Start**:
1. You will receive an instant Telegram message on your phone (`6642913680`):
   ```
   🚀 FLINZA OUTREACH OS IS ONLINE
   ━━━━━━━━━━━━━━━━━━━━━━
   🌐 Live Dashboard URL:
   http://123.45.67.89:7880

   📊 Active Outbound Fleet:
   • Amazon SES: Stockholm (eu-north-1) Active
   • 21 Aliases Ready: 7 per domain across:
     — flinzaworks.online
     — flinzaworks.site
     — tryflinzaworks.site
   • Brevo Fallback & Rotation: Ready (awaiting passwords)
   • Auto-Failover: ON (SES Quota Limit → Brevo)
   • Batch Rotation: ON (5 SES ↔ 5 Brevo)
   ```

2. Open the link `http://<server-ip>:7880` in your browser.

---

## 5. How to Connect Custom Domain (`studio.flinzaworks.online`)

If you cannot access the server directly via `http://<server-ip>:7880` (for example, if your hosting provider blocks port 7880 behind a firewall, or you want a clean HTTPS SSL domain link):

### Step A: Add DNS A Record in Cloudflare
1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com) and select `flinzaworks.online`.
2. Go to **DNS** → **Records** → Click **Add Record**.
3. Fill in:
   - **Type**: `A`
   - **Name**: `studio`
   - **IPv4 Address**: `<Your_Server_Public_IP>` (e.g. `123.45.67.89`)
   - **Proxy status**: **Proxied (Orange Cloud ON)**
4. Click **Save**.

### Step B: Create Cloudflare Origin Rule (Port 443 → Port 7880)
Because Cloudflare proxies standard traffic over HTTPS (port 443), tell Cloudflare to deliver the traffic to your server on port 7880:
1. In Cloudflare for `flinzaworks.online`, go to **Rules** → **Origin Rules**.
2. Click **Create Rule**.
3. Name the rule: `Flinza Studio Port Forward`.
4. Under **Field**: Select `Hostname`.
5. Under **Operator**: Select `equals`.
6. Under **Value**: Enter `studio.flinzaworks.online`.
7. Under **Destination Port**:
   - Select **Rewrite to...**
   - Enter `7880`.
8. Click **Deploy**.

**That is all!** You can now open:
👉 **`https://studio.flinzaworks.online`**
It will automatically connect to your server securely with full HTTPS SSL!

---

## 6. Inputting the 3 Brevo Passwords (After Phone Verification)

Once you verify the phone numbers on your 3 Brevo accounts, enter the SMTP passwords using any of the 3 methods below:

### Method 1: Via the Web Dashboard (Easiest)
1. Go to `http://<server-ip>:7880` or `https://studio.flinzaworks.online`.
2. Navigate to **Infrastructure → SMTP Vault** or **Aliases & Routing**.
3. Select your domain (`flinzaworks.online`, `flinzaworks.site`, or `tryflinzaworks.site`).
4. Enter the Brevo SMTP login email and Master SMTP Password.
5. Click **Save**.

### Method 2: Via Telegram Bot Remote Terminal (`/runcmd`)
Send this command directly to your Telegram bot:
```text
/runcmd python -c "import database as db; db.set_setting('brevo_user_flinzaworks_online', 'user1@brevo.com'); db.set_setting('brevo_pass_flinzaworks_online', 'xsmtpsib-...'); print('Saved!')"
```

### Method 3: Via Fast HTTP API
Send a POST request to your server:
```bash
curl -X POST http://<server-ip>:7880/api/smtp/brevo-credentials \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "flinzaworks.online",
    "smtp_user": "user1@brevo.com",
    "smtp_pass": "xsmtpsib-YOUR-KEY-HERE",
    "batch_size": 5
  }'
```

---

## 7. How the Failover & Batch Rotation Operates

1. **Primary Send**: All emails default to Amazon SES (Stockholm Ingress) using the verified DKIM/SPF domain keys.
2. **Quota Failover**: If Amazon SES daily quota is exceeded (or AWS returns a `554` rejection):
   - The engine triggers `db.trigger_ses_quota_exceeded()`.
   - Dispatch instantly and automatically switches to Brevo SMTP for that domain.
   - Zero emails will be dropped or queued unnecessarily.
3. **Batch Rotation**: When enabled, the engine sends $X$ emails (default 5) via Amazon SES, then $X$ emails via Brevo, and rotates back.
4. **Safety Net**: If Brevo has no password configured yet, the engine safely dispatches 100% via Amazon SES without interruption.
