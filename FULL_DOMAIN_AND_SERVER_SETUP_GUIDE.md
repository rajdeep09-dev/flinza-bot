# 🌐 Master Domain, Server Deployment & Cold Outreach Setup Guide
### For `flinzaworks.site` · `tryflinzaworks.site` · `flinzaworks.online`

This master guide walks you through the complete, step-by-step setup procedure from **deploying the Python server**, **pointing your Hostinger domains to Cloudflare**, **configuring 10/10 deliverability DNS (SPF, DKIM, DMARC, MX)**, **setting up free Cloudflare email aliases**, and **connecting SMTP in Flinza** for cold outreach.

---

## 📑 Table of Contents
1. [Architecture Overview: Cold Email Pipeline](#1-architecture-overview-cold-email-pipeline)
2. [Step 1: Pointing Hostinger Domains to Cloudflare (Free DNS)](#step-1-pointing-hostinger-domains-to-cloudflare-free-dns)
3. [Step 2: DNS Authentication (SPF, DKIM, DMARC, MX)](#step-2-dns-authentication-spf-dkim-dmarc-mx)
4. [Step 3: Setting Up Free Inbound Email Aliases (Cloudflare Email Routing)](#step-3-setting-up-free-inbound-email-aliases-cloudflare-email-routing)
5. [Step 4: SMTP Relay Setup for Outbound Sending](#step-4-smtp-relay-setup-for-outbound-sending)
6. [Step 5: Deploying the Python Server (2 Options)](#step-5-deploying-the-python-server-2-options)
   - [Option A: Local PC / Windows + Free Cloudflare Tunnel (Zero Cost)](#option-a-local-pc--windows--free-cloudflare-tunnel-zero-cost)
   - [Option B: 24/7 Cloud VPS (Ubuntu / Hetzner / DigitalOcean)](#option-b-247-cloud-vps-ubuntu--hetzner--digitalocean)
7. [Step 6: Connecting Domains & SMTP Profiles inside Flinza](#step-6-connecting-domains--smtp-profiles-inside-flinza)
8. [Step 7: Pre-Flight DNS Audit & Campaign Launch](#step-7-pre-flight-dns-audit--campaign-launch)

---

## 1. Architecture Overview: Cold Email Pipeline

You have 3 dedicated outreach domains on Hostinger:
- **`flinzaworks.site`** (Primary Agency / Domain 1)
- **`tryflinzaworks.site`** (Secondary Outreach / Domain 2)
- **`flinzaworks.online`** (Tertiary Outreach / Domain 3)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FLINZA OUTREACH OS                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [Outbound Sending]                                                         │
│  Flinza Engine  ──► Smart IP Rotator  ──► SMTP Relay (Brevo / SES / Custom) │
│                          │                         │                        │
│                          ├─► Python Server IP      ▼                        │
│                          │   (42.105.183.147)    Inbox                      │
│                          └─► Mobile 5G Proxy     (Gmail, Outlook)           │
│                              (Airplane Toggle)                              │
│                                                                             │
│  [Inbound Replies]                                                          │
│  Lead Replies   ──► Cloudflare Email Routing ──► Forwarded to Gmail /       │
│                     (Free Unlimited Aliases)     Flinza Priority Inbox      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why 3 separate domains?**
By spreading your cold email volume across 3 secondary domains, you protect your primary brand, avoid spam filters, and can send 3× the daily volume safely.

---

## Step 1: Pointing Hostinger Domains to Cloudflare (Free DNS)

Cloudflare gives you:
- **Free Email Routing**: Unlimited custom aliases (e.g. `alex@flinzaworks.site`, `nabir@tryflinzaworks.site`) forwarding to your main Gmail with $0 monthly cost.
- **Instant DNS Propagation**: Changes apply in under 5 seconds globally.
- **DNS-over-HTTPS Security**: Automated SPF/DKIM verification.

### Instructions:
1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/) and create a free account if you haven't already.
2. Click **Add a Domain** and add each domain one by one:
   - `flinzaworks.site`
   - `tryflinzaworks.site`
   - `flinzaworks.online`
3. Choose the **Free Plan ($0)** and click Continue.
4. Cloudflare will scan existing DNS records, then provide you with **2 Nameservers**, for example:
   - `alina.ns.cloudflare.com`
   - `kurt.ns.cloudflare.com`
   *(Note down the exact nameservers Cloudflare gives you).*
5. Open your [Hostinger Control Panel](https://hpanel.hostinger.com/):
   - Go to **Domains** -> Click **Manage** next to `flinzaworks.site`.
   - In the left menu, select **DNS / Nameservers**.
   - Click **Change Nameservers**.
   - Select **Use Custom Nameservers** and replace Hostinger's default nameservers with Cloudflare's two nameservers.
   - Click **Save**.
6. Repeat Step 5 for `tryflinzaworks.site` and `flinzaworks.online`.
7. Return to Cloudflare and click **Check Nameservers**. Within 2 to 10 minutes, Cloudflare will show:
   `Great news! Cloudflare is now protecting your site`.

---

## Step 2: DNS Authentication (SPF, DKIM, DMARC, MX)

For 100% inbox landing in Gmail and Outlook without landing in Spam, every domain must have 4 core DNS records:

Open **Cloudflare** -> Select your domain -> Go to **DNS** -> **Records** -> **Add Record**:

### Record 1: MX Records (For Inbound Cloudflare Email Routing)
When you enable Cloudflare Email Routing (Step 3), Cloudflare will automatically prompt you to add these 3 MX records with 1 click:
| Type | Name | Content / Mail Server | Priority | Proxy Status |
| :--- | :--- | :--- | :--- | :--- |
| **MX** | `@` | `route1.mx.cloudflare.net` | `13` | DNS only (Grey Cloud) |
| **MX** | `@` | `route2.mx.cloudflare.net` | `47` | DNS only (Grey Cloud) |
| **MX** | `@` | `route3.mx.cloudflare.net` | `85` | DNS only (Grey Cloud) |

### Record 2: SPF (Sender Policy Framework)
SPF tells recipient mail servers (Google/Microsoft) which IPs and SMTP services are authorized to send emails on behalf of your domain.

Add this **TXT** record:
- **Type**: `TXT`
- **Name**: `@`
- **TTL**: `Auto`
- **Content**:
  ```text
  v=spf1 include:_spf.mx.cloudflare.net include:spf.brevo.com ip4:42.105.183.147 ~all
  ```
> **Explanation**:
> - `include:_spf.mx.cloudflare.net`: Authorizes Cloudflare Email Routing for inbound forwarding.
> - `include:spf.brevo.com`: Authorizes Brevo SMTP (or replace with your SMTP provider e.g. `include:smtp2go.com` or `include:amazonses.com`).
> - `ip4:42.105.183.147`: Authorizes your Python server's direct outbound IP.
> - `~all`: Soft-fail policy (recommended by Google & Yahoo post-2024 updates).

### Record 3: DKIM (DomainKeys Identified Mail)
DKIM cryptographically signs every outbound email with a private key.
- If using **Brevo**:
  1. Go to Brevo -> **Settings** -> **Senders, Domains & Dedicated IPs** -> **Domains**.
  2. Click **Add a Domain** -> Enter `flinzaworks.site`.
  3. Brevo will generate a DKIM record like:
     - **Type**: `TXT`
     - **Name**: `mail._domainkey` (or `brevo._domainkey`)
     - **Content**: `k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD...`
  4. Paste this record into Cloudflare DNS with **Proxy status: DNS only** (Grey Cloud).
  5. Click **Verify Domain** in Brevo.
- If using **SMTP2GO**:
  - Add the 3 CNAME DKIM records provided in the SMTP2GO dashboard.

### Record 4: DMARC (Domain-based Message Authentication)
DMARC protects your domain from spoofing and is mandatory for Gmail/Yahoo delivery.

Add this **TXT** record:
- **Type**: `TXT`
- **Name**: `_dmarc`
- **TTL**: `Auto`
- **Content**:
  ```text
  v=DMARC1; p=none; sp=none; pct=100; rua=mailto:dmarc-reports@flinzaworks.site
  ```

---

## Step 3: Setting Up Free Inbound Email Aliases (Cloudflare Email Routing)

Cloudflare Email Routing is 100% free and allows you to create unlimited custom email aliases that automatically forward replies into your master personal inbox.

1. In Cloudflare, go to **Email** -> **Email Routing**.
2. Click **Get Started**.
3. Under **Destination addresses**:
   - Enter your personal Gmail or work inbox (e.g. `yourname@gmail.com`).
   - Cloudflare will send a confirmation email. Open your Gmail, click the **Verify email address** link.
4. Under **Routing rules**:
   - Create custom alias rules for each personality:
     - `alex@flinzaworks.site` ──► Forward to `yourname@gmail.com`
     - `nabir@tryflinzaworks.site` ──► Forward to `yourname@gmail.com`
     - `growth@flinzaworks.online` ──► Forward to `yourname@gmail.com`
   - **Optional (Catch-All Rule)**: Enable **Catch-all address** ──► Forward to `yourname@gmail.com`. Any email sent to `anything@flinzaworks.site` will now land in your inbox!
5. Test it: Send an email from your phone or another email to `alex@flinzaworks.site`. You will receive it in your Gmail within 3 seconds!

---

## Step 4: SMTP Relay Setup for Outbound Sending

While Cloudflare handles *inbound forwarding*, outbound cold emails must be sent via an SMTP relay or your direct Python server socket.

### Recommended Providers:
| Provider | Free Tier / Cost | Sending Limit | Best For |
| :--- | :--- | :--- | :--- |
| **Brevo (Sendinblue)** | **Free forever** | 300 emails / day | Zero cost, great deliverability |
| **SMTP2GO** | **Free forever** | 1,000 emails / month | Ultra-fast delivery, real-time analytics |
| **Amazon SES** | **$0.10 / 1,000 emails** | 50,000+ / day | High volume scaling |
| **Google Workspace / Gmail** | $6 / mo per mailbox | 500-2,000 / day | Native Google reputation |

### Getting Brevo SMTP Credentials:
1. Sign up at [Brevo.com](https://www.brevo.com/).
2. Go to **SMTP & API** -> Click **Generate a new SMTP key**.
3. Copy your details:
   - **SMTP Server**: `smtp-relay.brevo.com`
   - **Port**: `587`
   - **Login / Username**: Your Brevo account email
   - **Password**: Your generated Master SMTP Key

---

## Step 5: Deploying the Python Server (2 Options)

### Option A: Local PC / Windows + Free Cloudflare Tunnel (Zero Cost)
Run Flinza on your Windows computer or laptop 100% free with automatic SSL and zero port forwarding.

1. Ensure Flinza is running:
   ```powershell
   cd "c:\Users\Nabir Hossain\OneDrive\antigravity tele\flinza"
   python -m uvicorn web_server:app --host 0.0.0.0 --port 7880
   ```
2. Install Cloudflare Tunnel CLI (`cloudflared`):
   ```powershell
   winget install --id Cloudflare.cloudflared
   ```
3. Expose Flinza securely to your custom domain (e.g. `app.flinzaworks.site`):
   ```powershell
   cloudflared tunnel login
   cloudflared tunnel create flinza-outreach
   cloudflared tunnel route dns flinza-outreach app.flinzaworks.site
   ```
4. Run the tunnel:
   ```powershell
   cloudflared tunnel run --url http://localhost:7880 flinza-outreach
   ```
   Now you can open **`https://app.flinzaworks.site`** from anywhere in the world!

---

### Option B: 24/7 Cloud VPS (Ubuntu / Hetzner / DigitalOcean)
For always-on 24/7 sending without keeping your laptop open.

1. Launch a $4/mo Ubuntu 22.04 or 24.04 VPS.
2. Connect via SSH:
   ```bash
   ssh root@<YOUR_VPS_IP>
   ```
3. Install Python 3.10+, git, and virtual environment:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git uvicorn nginx
   ```
4. Clone the repository:
   ```bash
   git clone https://github.com/rajdeep09-dev/flinza-bot.git /opt/flinza
   cd /opt/flinza
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
5. Create a background `systemd` service to keep Flinza running 24/7:
   ```bash
   sudo nano /etc/systemd/system/flinza.service
   ```
   Paste:
   ```ini
   [Unit]
   Description=Flinza Outreach OS Web Server
   After=network.target

   [Service]
   User=root
   WorkingDirectory=/opt/flinza
   ExecStart=/opt/flinza/venv/bin/python -m uvicorn web_server:app --host 0.0.0.0 --port 7880
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
6. Enable and start Flinza:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable flinza
   sudo systemctl start flinza
   sudo systemctl status flinza
   ```

---

## Step 6: Connecting Domains & SMTP Profiles inside Flinza

1. Open Flinza in your browser: `http://localhost:7880` (or `https://app.flinzaworks.site`).
2. Go to **SMTP Vault** (or **Mailboxes** -> **+ Add SMTP Profile**).
3. Add an entry for each of your sending personalities:

#### Profile 1 (`flinzaworks.site`):
- **Profile Name**: `Alex - Flinza Works Primary`
- **From Email**: `alex@flinzaworks.site`
- **Sender Name**: `Alex | Flinza Works`
- **SMTP Host**: `smtp-relay.brevo.com`
- **SMTP Port**: `587`
- **SMTP Username**: `your-brevo-login@gmail.com`
- **SMTP Password**: `your-brevo-smtp-key`
- Click **⚡ Test Connection** -> You will see `✓ SMTP Authenticated Successfully!`.
- Click **Save to Vault**.

#### Profile 2 (`tryflinzaworks.site`):
- **Profile Name**: `Nabir - TryFlinza Secondary`
- **From Email**: `nabir@tryflinzaworks.site`
- **Sender Name**: `Nabir | TryFlinza`
- **SMTP Host**: `smtp-relay.brevo.com`
- **SMTP Port**: `587`
- Click **⚡ Test Connection** -> Click **Save to Vault**.

#### Profile 3 (`flinzaworks.online`):
- **Profile Name**: `Growth Team - Flinza Online`
- **From Email**: `growth@flinzaworks.online`
- **Sender Name**: `Growth @ Flinza`
- **SMTP Host**: `smtp-relay.brevo.com`
- **SMTP Port**: `587`
- Click **⚡ Test Connection** -> Click **Save to Vault**.

---

## Step 7: Pre-Flight DNS Audit & Campaign Launch

Before firing outreach, verify that your DNS authentication scores 100%:

1. In Flinza, go to **Warmup Monitor** -> **Deliverability & Health Audit**.
2. Enter your domain: `flinzaworks.site` and click **Run Audit**.
3. The engine uses Cloudflare DNS-over-HTTPS (DoH) to check:
   - ✅ **SPF Record**: Verified valid
   - ✅ **DKIM Signature**: Verified valid
   - ✅ **DMARC Policy**: Verified valid
   - ✅ **MX Records**: Pointed to Cloudflare Email Routing
   - ✅ **DNSBL Blacklist**: Clean across 25+ global spam databases
4. Go to **Leads CRM**:
   - Check the Campaign Control Bar:
     `Active Fleet: My 5G Phone + Python Server (Balanced Pool)`
   - Click **⚡ Generate All & Queue** to generate high-converting AI personalized pitches for all leads.
   - Click **🚀 Launch Campaign**.
5. The campaign will now automatically balance sending between your **direct Python server host IP** and **mobile 5G rotating proxy**, with all replies forwarding directly to your personal inbox!
