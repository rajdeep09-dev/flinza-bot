# 📱 The Complete Guide: Turn Your Phone into a 24/7 Mobile Rotating Proxy with Localtonet & Flinza (No Root)

> **Zero Root Required** · Works on Any Android Phone (or iOS) · Stays Online 24/7 Even After Closing Browser

---

## 📑 Table of Contents
1. [Why Mobile 4G/5G Residential Proxies?](#1-why-mobile-4g5g-residential-proxies)
2. [How the Architecture Works](#2-how-the-architecture-works)
3. [Prerequisites](#3-prerequisites)
4. [Step 1: Setup Local Proxy on Phone (Every Proxy)](#step-1-setup-local-proxy-on-phone-every-proxy)
5. [Step 2: Connect Phone to Localtonet](#step-2-connect-phone-to-localtonet)
6. [Step 3: Create Persistent SOCKS5 Tunnel on Localtonet](#step-3-create-persistent-socks5-tunnel-on-localtonet)
7. [Step 4: Connect to Flinza Outreach Command Center](#step-4-connect-to-flinza-outreach-command-center)
8. [Step 5: Automated 1-Click Airplane Mode IP Rotation ✈️](#step-5-automated-1-click-airplane-mode-ip-rotation)
9. [Step 6: Phone Optimization for 24/7 Uninterrupted Stability](#step-6-phone-optimization-for-247-uninterrupted-stability)
10. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## 1. Why Mobile 4G/5G Residential Proxies?

When sending cold outreach emails or web automation, **IP reputation is the #1 factor** determining whether your emails land in the Primary Inbox or Spam folder.

* **Data Center IPs (AWS, DigitalOcean, Hetzner, OVH):**
  * ❌ Heavily monitored by Google Workspace, Microsoft 365, and Spamhaus.
  * ❌ High spam score; emails are easily flagged.
* **Mobile Carrier IPs (Reliance Jio 5G, Airtel 4G/5G, Vodafone Idea, AT&T, T-Mobile):**
  * ✅ **Highest Sender Reputation in the World**: Millions of regular smartphone users share the exact same mobile IP pool through Carrier-Grade NAT (CGNAT).
  * ✅ **Immune to Subnet Bans**: Google and Microsoft *cannot* ban mobile carrier IP ranges without breaking email for millions of real mobile users.
  * ✅ **Unlimited Clean Residential IPs**: Toggling **Airplane Mode** for 5 seconds forces the cell tower to assign your phone a brand new, clean IP lease.

---

## 2. How the Architecture Works

Because mobile phone carriers use **CGNAT (Carrier-Grade NAT)**, your phone does not have a public IPv4 address, and inbound ports are blocked by the carrier.

**Localtonet solves this effortlessly:**

```
┌─────────────────────────────────────────────────────────┐
│                    Your Android Phone                   │
│  [4G/5G Cellular Data Active (Wi-Fi OFF)]               │
│                                                         │
│  ┌──────────────────────┐      ┌─────────────────────┐  │
│  │ Every Proxy (SOCKS5) │ ───> │  Localtonet Client  │  │
│  │   127.0.0.1:1080     │      │   (Outbound TCP)    │  │
│  └──────────────────────┘      └──────────┬──────────┘  │
└───────────────────────────────────────────┼─────────────┘
                                            │ Outbound Reverse
                                            │ Tunnel Connection
                                            ▼
                       ┌───────────────────────────────┐
                       │    Localtonet Cloud Relay     │
                       │ prx-us-1.localtonet.com:12345 │
                       └───────────────┬───────────────┘
                                       │
                                       │ Outbound SMTP via SOCKS5
                                       ▼
                       ┌───────────────────────────────┐
                       │     Flinza Outreach Engine    │
                       │    (Runs 24/7 via SQLite DB)  │
                       └───────────────────────────────┘
```

1. **Every Proxy** turns your phone's cellular connection into a local proxy server listening on port `1080`.
2. **Localtonet** establishes an *outbound* encrypted reverse tunnel from your phone to Localtonet's cloud server.
3. Localtonet exposes a public SOCKS5 endpoint (e.g. `prx-us-1.localtonet.com:12345`).
4. **Flinza** stores this tunnel in `flinza.db`. Even if you shut down your browser, Flinza's backend daemon keeps the connection active and routes all outreach emails through your phone's mobile IP!

---

## 3. Prerequisites

| Component | Recommendation | Cost |
|---|---|---|
| **Android Device** | Any spare Android phone (Android 7.0+) | Free / Spare Phone |
| **Cellular SIM** | Jio 5G, Airtel 5G/4G, Vi, or any carrier with active data | Regular data plan |
| **Local Proxy App** | **Every Proxy** (Google Play Store) | 100% Free |
| **Tunnel Provider** | **Localtonet** ([localtonet.com](https://localtonet.com)) | Free trial / Paid plan |
| **Automation App** | **MacroDroid** (for Airplane mode rotation) | 100% Free |

---

## Step 1: Setup Local Proxy on Phone (Every Proxy)

1. Open **Google Play Store** on your Android phone and install **Every Proxy** by *Gorillas Software*.
2. Open Every Proxy:
   - Turn **ON** the **SOCKS5** toggle.
   - Note the port number displayed: typically **`1080`**.
   - (Optional) Also turn **ON** the **HTTP** toggle (typically port `8080`).
3. Tap the **Settings** (gear icon) in Every Proxy:
   - Ensure **IP Address to bind** is set to `0.0.0.0` or `127.0.0.1`.
   - Ensure **Require Authentication** is disabled (or note your credentials if enabled).
4. **Disable Wi-Fi**: Turn OFF your phone's Wi-Fi. Ensure mobile data (4G/5G) is active. Every Proxy will now route all traffic through your cellular carrier!

---

## Step 2: Connect Phone to Localtonet

1. Create a free account at [localtonet.com](https://localtonet.com) if you haven't already.
2. In the Localtonet dashboard, copy your **Auth Token**.
3. Install Localtonet on your phone:
   - **Method A (Direct App)**: Download the Localtonet Android APK from the Localtonet dashboard or Google Play, paste your Auth Token, and tap **Connect**.
   - **Method B (Termux / Linux CLI)**:
     ```bash
     pkg update && pkg install curl -y
     curl -s https://localtonet.com/install.sh | bash
     localtonet authtoken YOUR_TOKEN_HERE
     localtonet
     ```
4. Verify your phone shows **Connected** to the Localtonet relay.

---

## Step 3: Create Persistent SOCKS5 Tunnel on Localtonet

1. On your PC or phone, open your [Localtonet Dashboard](https://localtonet.com).
2. Click **My Tunnels** in the sidebar → click **Create Tunnel**.
3. Configure the tunnel:
   - **Protocol**: Select `TCP` (or `SOCKS5` if available in your tier).
   - **Local IP**: Enter `127.0.0.1` (or `localhost`).
   - **Local Port**: Enter `1080` (the Every Proxy SOCKS5 port).
   - **Region**: Choose the closest server region (e.g. `US`, `EU`, `Asia-India`).
   - **Auth (Optional)**: Set a Username & Password if you want private proxy authentication.
4. Click **Start Tunnel**.
5. Once started, Localtonet displays your public tunnel connection details:
   - **Host / Server**: e.g., `prx-us-1.localtonet.com` (or user domain)
   - **Port**: e.g., `12345`

---

## Step 4: Connect to Flinza Outreach Command Center

1. Open your Flinza Dashboard (`http://localhost:7880`).
2. Click the **IP Nodes** tab in the sidebar.
3. Ensure the **"⚡ Localtonet 24/7 Mobile Tunnel (No Browser Needed)"** tab is active.
4. Fill in the form:
   - **Node Label**: e.g. `OnePlus 12 Jio 5G (Localtonet)`
   - **Tunnel Host**: e.g. `prx-us-1.localtonet.com`
   - **Tunnel Port**: e.g. `12345`
   - **Protocol**: `SOCKS5 (Recommended for Outreach)`
   - **Auth Username & Password**: *(Leave blank if not configured in Localtonet)*
   - **Carrier / ISP Provider**: Select your mobile network (e.g. `📱 Reliance Jio 5G`)
   - **Daily Send Limit**: e.g. `250`
   - **IP Rotation Webhook URL**: *(See Step 5 below)*
5. Click **⚡ Test Connection**:
   - Flinza establishes a live SOCKS5 connection to your phone's cellular data.
   - It retrieves your real mobile carrier external IP and latency in milliseconds (e.g., `⚡ 28 ms`).
6. Click **💾 Save & Activate 24/7 Mobile Tunnel**:
   - The tunnel is saved into `flinza.db`.
   - Flinza's background daemon will now maintain this connection indefinitely.
   - **You can safely close the dashboard browser tab!** Outreach will continue dispatching via this mobile IP.

---

## Step 5: Automated 1-Click Airplane Mode IP Rotation ✈️

When sending bulk outreach, rotating your IP address every 10–25 emails keeps your sender reputation 100% spotless.

### How Airplane Mode Rotation Works
In 4G/5G mobile networks, turning Airplane mode ON for 5 seconds breaks the cellular radio session. When turned OFF, the cell tower assigns a **brand new IP lease from the carrier pool**.

### Method 1: Using MacroDroid (100% Free & No Root)
1. Install **MacroDroid** from Google Play Store on your phone.
2. In MacroDroid, create a new Macro:
   - **Trigger**: Tap **+** → Select **Connectivity** → **Webhook (URL)**.
     - MacroDroid provides you with a unique trigger URL, e.g.:
       `https://trigger.macrodroid.com/YOUR_DEVICE_ID/rotate_ip`
   - **Action 1**: Tap **+** → Select **Connectivity** → **Airplane Mode** → Turn **ON**.
   - **Action 2**: Tap **+** → Select **MacroDroid Specific** → **Wait / Delay** → Set to **5 seconds**.
   - **Action 3**: Tap **+** → Select **Connectivity** → **Airplane Mode** → Turn **OFF**.
   - **Action 4**: Tap **+** → Select **MacroDroid Specific** → **Wait / Delay** → Set to **4 seconds** (allows cellular data to reconnect).
3. Save the Macro.
4. Copy your MacroDroid Webhook URL and paste it into Flinza:
   - In Flinza's IP Nodes section → click **✏️ Edit** on your node.
   - Paste the URL into **IP Rotation Webhook URL**.
   - Click **Save Settings**.
5. **Test it!** Click the **🔄 Rotate** button in the IP Node Fleet table:
   - Flinza calls your phone's webhook.
   - Your phone toggles airplane mode.
   - Flinza waits 3.5s, detects the new carrier IP, updates `flinza.db`, and alerts you:
     `🔄 Mobile IP rotated: 42.105.x.x → 42.108.y.y (32 ms)`!

### Method 2: Localtonet Native Rotation Webhook
If you have Localtonet's Rotating Mobile Proxy add-on:
1. Open your tunnel settings on `localtonet.com`.
2. Copy the **Rotation Webhook URL** provided in the dashboard.
3. Paste it into Flinza's **IP Rotation Webhook URL** field.

---

## Step 6: Phone Optimization for 24/7 Uninterrupted Stability

To ensure your Android phone never sleeps or kills the proxy app when left unattended for weeks:

1. **Keep Connected to Charger**: Plug the phone into a standard 5V/1A or 5V/2A wall charger.
2. **Disable Android Battery Optimization (Crucial)**:
   - Go to phone **Settings → Apps → Every Proxy → Battery**.
   - Set to **Unrestricted** (or "Don't optimize").
   - Repeat for **Localtonet** and **MacroDroid**.
3. **Turn OFF Wi-Fi**:
   - Ensure Wi-Fi is disabled so Android never accidentally routes traffic through your home broadband.
4. **Enable Developer Options Stay Awake**:
   - Go to phone **Settings → About Phone** → tap **Build Number** 7 times.
   - Go to **Settings → Developer Options** → toggle **Stay Awake** (Screen will never sleep while charging).
   - Lower the screen brightness to 0% to prevent OLED burn-in and save energy.

---

## Troubleshooting & FAQ

### Q: Flinza shows "Connection timed out" when testing the tunnel?
- Verify **Every Proxy** is running and the **SOCKS5** toggle is green.
- Verify the **Localtonet** client on your phone shows **Connected**.
- In Localtonet dashboard, check that the tunnel status is **Active / Running**.
- Ensure Local Port is set to `1080` (matches Every Proxy).

### Q: Does Flinza disconnect if I close my browser or shut down my PC?
- **No!** If Flinza is running on a VPS or background server, the persistent tunnel credentials are saved in `flinza.db`. The background keepalive daemon pings the proxy every 60 seconds. Only browser WebRTC nodes require the browser tab; Localtonet tunnels are 100% autonomous.

### Q: Can I connect multiple mobile phones to Flinza?
- **Yes!** You can connect multiple phones (e.g., Phone 1 on Jio 5G, Phone 2 on Airtel 5G, Phone 3 on Vi 4G). Flinza will automatically distribute cold outreach across all active nodes according to their individual daily sending limits!

### Q: What is the recommended daily email volume per mobile IP?
- We recommend **150 to 300 emails per day** per mobile IP node. With automated airplane mode rotation every 25 emails, you can safely scale outreach while maintaining 99%+ deliverability.

---

*Guide built for Flinza Outreach Command Center. Compatible with Localtonet, Every Proxy, and MacroDroid.*
