# Flinza Deployment Guide

See detailed steps below.

## Quick Start

1. Get a Hetzner CX11 VPS (2GB RAM, EUR3.79/mo) at https://hetzner.com/cloud
2. Install Ubuntu 22.04 LTS
3. Upload the flinza/ folder via SCP
4. Run: python3 -m venv venv && source venv/bin/activate && pip install fastapi uvicorn python-telegram-bot requests pysocks
5. Create systemd services (see below)
6. Configure nginx reverse proxy
7. Get free SSL from Certbot

## Systemd: Web Server

File: /etc/systemd/system/flinza-web.service

[Unit]
Description=Flinza Web
After=network.target

[Service]
User=flinza
WorkingDirectory=/home/flinza/flinza
EnvironmentFile=/home/flinza/flinza/.env
ExecStart=/home/flinza/flinza/venv/bin/python -m uvicorn web_server:app --host 127.0.0.1 --port 7880
Restart=on-failure

[Install]
WantedBy=multi-user.target

## Systemd: Telegram Bot

File: /etc/systemd/system/flinza-bot.service

[Unit]
Description=Flinza Bot
After=network.target

[Service]
User=flinza
WorkingDirectory=/home/flinza/flinza
EnvironmentFile=/home/flinza/flinza/.env
ExecStart=/home/flinza/flinza/venv/bin/python bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target

## Nginx Config

File: /etc/nginx/sites-available/flinza

server {
    listen 80;
    server_name yourdomain.com;
    location / {
        proxy_pass http://127.0.0.1:7880;
        proxy_set_header X-Forwarded-For ;
        proxy_set_header Host System.Management.Automation.Internal.Host.InternalHost;
        proxy_read_timeout 300s;
    }
}

Enable with:
  ln -s /etc/nginx/sites-available/flinza /etc/nginx/sites-enabled/
  nginx -t && systemctl reload nginx
  certbot --nginx -d yourdomain.com

## IP Rotation (IP Nodes Tab)

1. All 3 friends open https://yourdomain.com from their own devices
2. Go to IP Nodes tab > Click Connect My IP
3. Browser heartbeats every 30s to stay in pool
4. Emails rotate naturally through different IPs

For BrightData: sign up at brightdata.com, get Residential SOCKS5 URL,
paste in Mailboxes > Edit Account > Proxy URL field.

## Update Code

  git pull && systemctl restart flinza-web flinza-bot
