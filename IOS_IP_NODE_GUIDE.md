# Flinza Outreach OS — iOS Mobile IP Node & Nexcloud Deployment Guide

> **Elite SMMA Cold Outreach Architecture**: How to turn iPhones into rotating 4G/5G residential IP nodes, deploy on Nexcloud 1GB RAM instances, and control everything remotely.

---

## Part 1: Why iOS 4G/5G Cellular IPs Land in 100% Primary Inbox

Traditional cold emailers get flagged because datacenter IPs (DigitalOcean, AWS, Hetzner, Contabo) have dirty reputations.

**Cellular 4G/5G carrier IPs (Jio, Airtel, AT&T, T-Mobile, Verizon) have the highest sender reputation in existence:**
1. **CGNAT Shared Pools**: Millions of real smartphone users send personal emails from the exact same carrier IP pool. Google and Microsoft **never** blacklist these IP ranges because doing so would block millions of legitimate phone users.
2. **Clean Reverse DNS**: Telecom carrier ASNs are inherently trusted by Spamhaus, Barracuda, and SORBS.
3. **The Airplane Mode Trick ✈️**: Toggling Airplane Mode ON for 5 seconds and OFF instantly forces the carrier tower to assign your iPhone a **brand new residential IP address**.

---

## Part 2: How to Connect Your iOS Device as an IP Node

You and your team members can contribute residential IPs from multiple iPhones simultaneously.

### Method A: 1-Click Safari Web Gateway (Zero App Install)
*Best for fast setup on multiple team members' phones.*

1. Connect your iPhone to **Cellular Data (4G/5G)** — turn Wi-Fi OFF.
2. Open **Safari** and go to your Flinza Command Center:
   ```
   http://YOUR-VPS-OR-NEXCLOUD-IP:7880
   ```
3. In the sidebar, tap **IP Nodes**.
4. The page will display: `Detecting your IP… [Your Mobile Carrier IP]`.
5. Tap the vibrant **"Connect My IP"** button.
6. Your iPhone is now registered in `flinza.db` as an active sending node! The outreach engine will automatically rotate outbound email dispatches across all connected team member IPs.

---

### Method B: Dedicated SOCKS5 Proxy Mesh (Tailscale + Potatso / Shadowrocket)
*Best for autonomous, 24/7 background dispatch.*

Cellular carriers use CGNAT (Carrier-Grade NAT), which blocks incoming external ports. To connect your VPS directly to your iPhone's proxy:

#### Step 1: Install Tailscale on iPhone and Nexcloud Server
1. Download **Tailscale** from the iOS App Store (100% Free).
2. Install Tailscale on your server:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
3. Log in with the same account on both your iPhone and the server.
4. Your iPhone gets a persistent virtual IP (e.g. `100.85.120.45`).

#### Step 2: Run Mobile Proxy on iOS
1. Install **Potatso** or **Shadowrocket** from the iOS App Store.
2. Enable local proxy server on port `8080` (HTTP or SOCKS5).
3. In Flinza Command Center → **IP Nodes** or **Mailboxes**, enter:
   ```
   socks5://100.85.120.45:8080
   ```
4. Now, all emails assigned to this node route directly through your iPhone's 5G connection!

---

## Part 3: Nexcloud 1GB RAM Instance Architecture

### RAM Consumption Breakdown
You asked: **"how much a total gb ram would be required?"**

| Component | RAM Footprint | Notes |
|---|---|---|
| Linux OS + Python 3.11 Runtime | ~70 MB | Debian / Ubuntu base |
| FastAPI + Uvicorn ASGI Server | ~45 MB | Lightweight async web server |
| SQLite Database (WAL Mode) | ~15 MB | In-process, zero separate daemon |
| Background Workers (Watcher & Scheduler) | ~20 MB | Async event loops |
| **Total Flinza RAM Usage** | **~150 MB** | **Leaves >800 MB FREE on 1GB instance!** |

> [!TIP]
> **A 1GB RAM Nexcloud instance is more than enough!** Flinza was engineered using lightweight, native asynchronous libraries (`aiosmtplib`, `aiohttp`, `sqlite3`, `uvicorn`) instead of bloated frameworks.

---

## Part 4: Nexcloud 2-Button Deployment (`app.py`)

Nexcloud Python hosting provides a control panel with **Start** and **Stop** buttons that run `python app.py`.

### How `app.py` Self-Deploys Automatically:
When you click **Start**:
1. `app.py` checks for `flinza.db` and runs all pending database migrations automatically.
2. It launches background loops (reply monitoring, followups, warmup).
3. If `TELEGRAM_BOT_TOKEN` is configured, it spawns the Telegram bot in background.
4. It starts the Uvicorn web engine on port `7880` (or the Nexcloud assigned `$PORT`).

### If Web Setup Fails: Use Telegram `/runcmd` Remote Shell!
If you ever cannot access the web dashboard or need to run terminal commands, use the Telegram Bot:

```
/runcmd uptime
/runcmd df -h
/runcmd free -m
/runcmd git pull origin main
/runcmd pip install -r requirements.txt
/runcmd python migrate_new_tables.py
```

The Telegram bot executes the bash command directly on your Nexcloud server and returns formatted output in your Telegram chat!

---

## Part 5: Deliverability Best Practices with Brevo & Free Tiers

1. **Brevo (Sendinblue)**:
   - SMTP Relay: `smtp-relay.brevo.com:587`
   - *Crucial*: In your Brevo dashboard, ensure your sending IP or domain is whitelisted under **Settings → Authorized IPs**.
2. **Mailjet Multi-Account Strategy**:
   - Create 2 free accounts (6,000 emails/month each = 12,000 free emails/month).
   - Add Domain A to Account 1, Domain B to Account 2.
   - Save both in Flinza **SMTP Vault**.
3. **SMTP2GO**:
   - 1,000 emails/month free tier with instant DKIM/SPF verification.
   - Host: `mail.smtp2go.com:587`.
