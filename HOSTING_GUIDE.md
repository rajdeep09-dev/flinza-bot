# 🌐 Complete VPS Hosting & Domain Setup Guide (₹100 / 1GB RAM Server)

This step-by-step master guide walks you through hosting both the **Flinza Python Telegram Bot** and the **Web App Studio** on a budget **₹100–₹150/month (~$1.50) 1GB RAM Linux VPS** and pointing your **custom domain name with free SSL (HTTPS)** so your entire team can securely access the dashboard anywhere.

---

## 📋 Architecture Overview

```
[Your Custom Domain: outreach.yourdomain.com]
                       │
                       ▼ (Cloudflare DNS + SSL HTTPS)
          [Your ₹100 / 1GB Ubuntu VPS Server]
                       │
             ┌─────────┴─────────┐
             │   Nginx (Port 443)│  <── Reverse Proxy & Let's Encrypt SSL
             └─────────┬─────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
[flinza-web.service]          [flinza-bot.service]
FastAPI Web Studio            Telegram Bot Daemon
(Internal Port 7880)          (Runs 24/7 in Background)
       │                               │
       └───────────────┬───────────────┘
                       ▼
            [SQLite DB: flinza.db]
```

---

## ⚡ Recommended Cheap VPS Providers

You can get a 1GB RAM server running **Ubuntu 22.04 or 24.04 LTS** from:
1. **RackNerd / LowEndBox**: ~$11 to $14 per **year** (~₹80 to ₹100/mo).
2. **Hostinger India**: Starting at ~₹139 to ₹199/month.
3. **Hetzner Cloud (CX22)**: €3.29/month (~₹300/mo, extreme high performance).
4. **100% Free Forever Alternative**: **Oracle Cloud Always Free Tier** (Get 4 Cores + 24 GB RAM for ₹0) or **AWS EC2 Free Tier** (`t2.micro` free for 12 months).

---

## 🛠️ Step 1: Connect to Your VPS & Set Up 2GB Swap Memory (CRITICAL)

> [!IMPORTANT]
> **Why 1GB RAM servers crash without this:**
> When running Python with background queues and installing packages with `pip`, Linux will run out of RAM and the kernel's **OOM Killer** will terminate Python.
> Creating a **2GB swap file** gives your ₹100 server 3GB of total virtual memory, making it 100% stable 24/7!

Connect to your server via SSH (from your terminal or PowerShell):
```bash
ssh root@YOUR_SERVER_IP
```

Run these 4 commands to configure 2GB swap memory:
```bash
# 1. Allocate 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile

# 2. Format and enable swap
sudo mkswap /swapfile
sudo swapon /swapfile

# 3. Make swap permanent across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 4. Verify swap is active
free -h
```
*(You will see 1GB RAM + 2GB Swap = 3GB total available memory!)*

---

## 📦 Step 2: Install Python 3.12, Git, Nginx & Certbot

Run this one-liner to install everything:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw
```

---

## 📥 Step 3: Clone the Repository & Configure `.env`

1. Clone your repository:
```bash
cd /var/www
sudo git clone https://github.com/rajdeep09-dev/flinza-bot.git flinza
sudo chown -R $USER:$USER /var/www/flinza
cd /var/www/flinza
```

2. Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3. Initialize your production database and migrations:
```bash
python3 -c "import database; database.init_db(); print('Database ready!')"
```

4. Configure your `.env` file:
```bash
cp .env.example .env
nano .env
```
Paste your:
- `TELEGRAM_BOT_TOKEN=...`
- `TELEGRAM_ADMIN_ID=...`
- `SECRET_KEY=generate_a_random_32_char_string`
- `CLOUDFLARE_API_TOKEN=...` (optional)
- `GROQ_API_KEY=...` / `OPENROUTER_API_KEY=...` (optional)

Press `CTRL + O`, `Enter` to save, and `CTRL + X` to exit.

---

## 🔄 Step 4: Run Both Web App & Telegram Bot 24/7 (`systemd`)

We will create two background system services so they start automatically on server reboots and restart automatically if anything ever crashes.

### Service 1: The Web Studio App (`flinza-web.service`)
Create the service file:
```bash
sudo nano /etc/systemd/system/flinza-web.service
```
Paste the following configuration:
```ini
[Unit]
Description=Flinza Outreach Web Studio App
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/flinza
Environment="PATH=/var/www/flinza/venv/bin"
ExecStart=/var/www/flinza/venv/bin/python -m uvicorn web_server:app --host 127.0.0.1 --port 7880 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Service 2: The Telegram Bot (`flinza-bot.service`)
Create the service file:
```bash
sudo nano /etc/systemd/system/flinza-bot.service
```
Paste the following configuration:
```ini
[Unit]
Description=Flinza Telegram Bot Daemon
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/flinza
Environment="PATH=/var/www/flinza/venv/bin"
ExecStart=/var/www/flinza/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Start & Enable Both Services
```bash
sudo systemctl daemon-reload

# Start and enable Web Studio
sudo systemctl start flinza-web
sudo systemctl enable flinza-web

# Start and enable Telegram Bot
sudo systemctl start flinza-bot
sudo systemctl enable flinza-bot
```

To check their real-time live status:
```bash
sudo systemctl status flinza-web
sudo systemctl status flinza-bot
```
*(Both will show `Active: active (running)` in bright green!)*

---

## 🌐 Step 5: Connect Your Custom Domain with Nginx & Free SSL

Let's say your domain is `magicfitpartners.com` and you want the web app on `outreach.magicfitpartners.com` (or `app.magicfitpartners.com`).

### 1. Add DNS `A` Record in Cloudflare (or Namecheap / GoDaddy)
- Go to your DNS Manager (e.g. Cloudflare DNS).
- Click **Add record**:
  - **Type**: `A`
  - **Name**: `outreach` (or `app`, or `@` for root)
  - **IPv4 address**: `YOUR_SERVER_IP`
  - **Proxy status**: **Proxied** (Orange Cloud) or **DNS Only** (Grey Cloud). *Either works; DNS Only is recommended when issuing Certbot certificates the first time.*

---

### 2. Configure Nginx Reverse Proxy
Create a new Nginx site configuration:
```bash
sudo nano /etc/nginx/sites-available/flinza
```
Paste this configuration (replace `outreach.magicfitpartners.com` with your actual subdomain/domain):
```nginx
server {
    listen 80;
    server_name outreach.magicfitpartners.com;

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
        proxy_read_timeout 86400;
    }
}
```

Enable the site and test Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/flinza /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### 3. Generate Free Auto-Renewing SSL Certificate (HTTPS)
Run Certbot:
```bash
sudo certbot --nginx -d outreach.magicfitpartners.com
```
- Enter your email address for renewal notices.
- Agree to the Terms of Service.
- Certbot will automatically edit your Nginx config and set up **free 100% automated SSL renewal**!

Now visit **`https://outreach.magicfitpartners.com`** in your browser — your luxury glassmorphic Flinza Web Studio is live with SSL lock icon 🔒!

---

## 🔒 Step 6: Security & Firewall Configuration (UFW)

Protect your server so only HTTP, HTTPS, and SSH are open to the public:
```bash
# Allow SSH so you don't get locked out
sudo ufw allow 22/tcp

# Allow Web Traffic
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable
sudo ufw status
```
*(Port 7880 is kept blocked from the internet so users can ONLY access via your secure domain name!)*

---

## 🛠️ Useful Maintenance & Logs Commands

| Task | Command |
|---|---|
| **View Live Web App Logs** | `sudo journalctl -u flinza-web -f` |
| **View Live Telegram Bot Logs** | `sudo journalctl -u flinza-bot -f` |
| **Restart Web App** | `sudo systemctl restart flinza-web` |
| **Restart Telegram Bot** | `sudo systemctl restart flinza-bot` |
| **Update Code from GitHub** | `cd /var/www/flinza && git pull origin main && sudo systemctl restart flinza-web flinza-bot` |
| **Check RAM Usage** | `free -h` or `htop` |

---

## 🎯 Summary Checklist

- [x] 1GB Server deployed on Ubuntu 22.04 / 24.04
- [x] 2GB Swapfile activated (`free -h` confirms 3GB total memory)
- [x] Cloned code to `/var/www/flinza` and installed `requirements.txt`
- [x] `flinza-web.service` running FastAPI on port 7880
- [x] `flinza-bot.service` running Telegram Bot daemon
- [x] DNS `A` record pointing `outreach.yourdomain.com` to VPS IP
- [x] Nginx reverse proxy configured and SSL certificate active via Certbot
- [x] UFW firewall active
