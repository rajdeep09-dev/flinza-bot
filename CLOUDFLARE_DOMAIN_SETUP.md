# 🌐 100% Free Custom Domain & Cloudflare Tunnel Guide for Flinza

This guide walks you through connecting your custom domain to Flinza Web Studio and hosting it **100% free with unlimited bandwidth and automatic SSL** using **Cloudflare Tunnels (`cloudflared`)**, plus embedding it directly inside your Telegram Mini App.

---

## 🚀 Why Cloudflare Tunnel?

- **$0 / Free Forever**: No VPS costs, no hosting bills, zero port forwarding required.
- **Instant HTTPS / SSL**: Free enterprise SSL certificates provided automatically by Cloudflare Edge.
- **Telegram Mini App Compliant**: Telegram requires strict HTTPS with valid SSL certificates. Cloudflare Tunnels satisfy this automatically.
- **DDoS Protected**: Your origin IP remains 100% hidden behind Cloudflare's global edge network.

---

## Part 1: Prerequisites

1. A domain managed on Cloudflare (e.g., `yourdomain.com`).
2. Flinza running locally on port 8000:
   ```bash
   python web_server.py
   ```

---

## Part 2: Instant 1-Minute Temporary Public URL (Zero Installation)

If you just want an instant HTTPS public link to test right away without configuring DNS:

```bash
npx cloudflared tunnel --url http://localhost:8000
```

Cloudflare will output a live URL like:
```
https://random-words-1234.trycloudflare.com
```
You can paste this URL into Telegram Bot via `/seturl https://random-words-1234.trycloudflare.com` to open the studio immediately inside Telegram!

---

## Part 3: Permanent Custom Domain Setup (`studio.yourdomain.com`)

### Step 1: Install `cloudflared`

#### Windows (PowerShell):
```powershell
winget install --id Cloudflare.cloudflared
```
*Or download the executable from Cloudflare's official GitHub releases.*

#### Linux / macOS:
```bash
# Ubuntu / Debian
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# macOS
brew install cloudflare/cloudflare/cloudflared
```

---

### Step 2: Authenticate with Cloudflare

Run:
```bash
cloudflared tunnel login
```
A browser window will open. Select your domain (`yourdomain.com`) and click **Authorize**. This downloads a certificate file to your machine.

---

### Step 3: Create the Named Tunnel

Run:
```bash
cloudflared tunnel create flinza-tunnel
```
This generates a Tunnel ID (e.g. `a1b2c3d4-e5f6-7890-abcd-1234567890ab`).

---

### Step 4: Route your Subdomain in DNS

Run:
```bash
cloudflared tunnel route dns flinza-tunnel studio.yourdomain.com
```
Cloudflare automatically adds the CNAME record to your Cloudflare DNS zone!

---

### Step 5: Configure the Tunnel

Create a configuration file `config.yml` in `~/.cloudflared/` (or `C:\Users\<username>\.cloudflared\config.yml` on Windows):

```yaml
tunnel: flinza-tunnel
credentials-file: C:\Users\<username>\.cloudflared\<TUNNEL-ID>.json

ingress:
  - hostname: studio.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

---

### Step 6: Run the Tunnel as a Background Service

Test running the tunnel:
```bash
cloudflared tunnel run flinza-tunnel
```

To install it as a persistent system service that starts automatically on boot:

#### Windows:
```powershell
cloudflared service install
```

#### Linux:
```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

Now, navigating to `https://studio.yourdomain.com` will securely load Flinza Studio with green padlock SSL!

---

## Part 4: Connect to Telegram Web App (Mini App)

### Method A: Via Flinza Telegram Bot (Fastest)

Send this command directly to your Flinza bot:
```
/seturl https://studio.yourdomain.com
```
The bot will save this URL and open it when you click **🖥️ Launch Web Studio**!

### Method B: Via Telegram @BotFather (Menu Button)

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/setmenubutton`.
3. Choose your bot (`@your_flinza_bot`).
4. Enter URL: `https://studio.yourdomain.com`
5. Enter button title: `⚡ Flinza Studio`
6. Now, every chat with your bot will display a persistent Mini App button in the bottom-left corner!

---

## Part 5: Configuring Outbound Email Dispatch Routes

Flinza supports 3 flexible outbound routing modes for custom domain aliases:

| Route Mode | Cost | Prerequisites | Best For |
|---|---|---|---|
| **✉️ Gmail Send-As Relay** | Free | Google App Password or OAuth | Low-to-medium volume (10–100/day) |
| **⚡ Cloudflare Native Sending API** | $5/month | Workers Paid plan + sending enabled | Edge-native micro-bursts |
| **🚀 Amazon SES / Dedicated SMTP** | $0.10 / 1k emails | AWS SES Verified Domain | High-volume agency scale (1k–50k/day) |

### How to Switch Routing Modes:
1. Open `https://studio.yourdomain.com`
2. Click **Aliases & Routing** in the sidebar.
3. For any alias (e.g. `alex@yourdomain.com`), select the desired route from the dropdown.
4. Click **⚡ Test Route** to verify real-time delivery and latency!
