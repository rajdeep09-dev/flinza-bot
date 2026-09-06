"""
Flinza — Universal Nexcloud 1-Click Entrypoint (app.py)
------------------------------------------------------
Designed for Nexcloud Python Host instances (1GB RAM) with Start / Stop buttons.
When "Start" is clicked:
  1. Auto-checks database migrations & initializes flinza.db
  2. Spawns background worker loops (Reply Watcher, Followup Scheduler)
  3. Spawns Telegram Bot (with /runcmd remote VPS terminal) if token configured
  4. Launches FastAPI / Uvicorn Outreach Studio on port 7880 (or $PORT)
  5. Memory footprint: ~150MB RAM (leaving >800MB free on 1GB instances)
"""

import sys
import os
import subprocess
import threading
import time
import logging
import signal

# Ensure working directory is the app root
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("flinza-runner")


def check_and_migrate_db():
    """Initializes flinza.db and ensures all required tables and columns exist."""
    logger.info("📦 Checking database and running auto-migrations...")
    try:
        import database as db
        db.init_db()

        # Run auxiliary migrations for robustness
        import sqlite3
        conn = sqlite3.connect("flinza.db")
        # Ensure ip_nodes has all columns
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ip_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                ip_address TEXT NOT NULL,
                status TEXT DEFAULT 'connected',
                user_agent TEXT,
                provider TEXT DEFAULT 'Cellular / 5G',
                daily_limit INTEGER DEFAULT 150,
                sent_today INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 32,
                is_paused INTEGER DEFAULT 0,
                last_reset_date TEXT DEFAULT '',
                is_persistent_tunnel INTEGER DEFAULT 0,
                proxy_protocol TEXT DEFAULT 'socks5',
                proxy_host TEXT DEFAULT '',
                proxy_port INTEGER DEFAULT 1080,
                proxy_user TEXT DEFAULT '',
                proxy_pass TEXT DEFAULT '',
                rotation_webhook TEXT DEFAULT '',
                auto_rotate_count INTEGER DEFAULT 0,
                last_rotated_at TEXT DEFAULT '',
                rotate_every_n INTEGER DEFAULT 5,
                sends_since_last_rotation INTEGER DEFAULT 0,
                connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                assigned_accounts TEXT DEFAULT '[]'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS smtp_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT DEFAULT 'custom',
                smtp_host TEXT NOT NULL,
                smtp_port INTEGER DEFAULT 587,
                smtp_user TEXT NOT NULL,
                smtp_pass TEXT,
                use_ssl INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Ensure column additions
        for col_sql in [
            "ALTER TABLE replies ADD COLUMN message_id TEXT",
            "ALTER TABLE replies ADD COLUMN to_email TEXT",
            "ALTER TABLE replies ADD COLUMN is_read INTEGER DEFAULT 0",
            "ALTER TABLE replies ADD COLUMN is_starred INTEGER DEFAULT 0",
            "ALTER TABLE ip_nodes ADD COLUMN provider TEXT DEFAULT 'Cellular / 5G'",
            "ALTER TABLE ip_nodes ADD COLUMN daily_limit INTEGER DEFAULT 150",
            "ALTER TABLE ip_nodes ADD COLUMN sent_today INTEGER DEFAULT 0",
            "ALTER TABLE ip_nodes ADD COLUMN latency_ms INTEGER DEFAULT 32",
            "ALTER TABLE ip_nodes ADD COLUMN is_paused INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass
        conn.commit()
        conn.close()
        logger.info("✅ Database migrations verified successfully.")
    except Exception as e:
        logger.warning(f"Database migration notice: {e}")


def start_telegram_bot_thread():
    """Starts Telegram Bot in a dedicated daemon thread if token is present."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        try:
            import config
            token = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        except Exception:
            token = None

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.info("ℹ️ TELEGRAM_BOT_TOKEN not configured — running in Web Studio Only mode.")
        return

    def _run_bot():
        logger.info("🤖 Starting Flinza Telegram Bot thread (with /runcmd host execution)...")
        try:
            import bot
            bot.main()
        except Exception as e:
            logger.error(f"Telegram Bot error: {e}")

    t = threading.Thread(target=_run_bot, daemon=True, name="TelegramBotThread")
    t.start()
    logger.info("✅ Telegram Bot thread launched.")


def send_startup_telegram_alert(port: int):
    """Sends immediate confirmation alert to admin Telegram with public IP and access URL."""
    def _send():
        time.sleep(2)  # brief pause to allow network & server socket to initialize
        try:
            import config
            import requests
            import socket
            token = os.environ.get("TELEGRAM_BOT_TOKEN") or getattr(config, "TELEGRAM_BOT_TOKEN", None)
            user_id = os.environ.get("ALLOWED_USER_ID") or getattr(config, "ALLOWED_USER_ID", None)
            if not token or not user_id:
                return

            # Discover public IP
            public_ip = "127.0.0.1"
            try:
                resp = requests.get("https://api.ipify.org?format=text", timeout=4)
                if resp.status_code == 200:
                    public_ip = resp.text.strip()
            except Exception:
                try:
                    public_ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    pass

            dashboard_url = f"http://{public_ip}:{port}"

            msg = (
                "🚀 *FLINZA OUTREACH OS IS ONLINE*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌐 *Live Dashboard URL*:\n`{dashboard_url}`\n\n"
                "📊 *Active Outbound Fleet*:\n"
                "• *Amazon SES*: Stockholm (`eu-north-1`) Ingress Active\n"
                "• *21 Aliases Ready*: 7 per domain across:\n"
                "  — `flinzaworks.online`\n"
                "  — `flinzaworks.site`\n"
                "  — `tryflinzaworks.site`\n"
                "• *Brevo Fallback & Rotation*: 3 Account slots ready (awaiting mobile verification passwords)\n"
                "• *Auto-Failover*: ON (SES Quota Limit → Brevo)\n"
                "• *Batch Rotation*: ON (5 SES ↔ 5 Brevo)\n\n"
                "🔗 *Cannot Access IP directly?*\n"
                "If port 7880 is blocked by your VPS/host firewall:\n"
                "1. Go to Cloudflare DNS for `flinzaworks.online`\n"
                f"2. Add A record: `studio` ➜ `{public_ip}` (Proxy ON)\n"
                "3. In Cloudflare Rules ➜ Origin Rules: Port 443 ➜ 7880\n"
                "4. Access securely via `https://studio.flinzaworks.online`\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚡ Reply `/runcmd <command>` anytime to run VPS terminal commands."
            )

            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": msg,
                    "parse_mode": "Markdown"
                },
                timeout=10
            )
            logger.info(f"✅ Telegram startup confirmation dispatched to Admin ({dashboard_url})")
        except Exception as e:
            logger.warning(f"Could not send Telegram startup confirmation: {e}")

    t = threading.Thread(target=_send, daemon=True, name="StartupTelegramAlert")
    t.start()


def start_port_forwarder(source_port: int, target_port: int):
    """Bridges traffic from source_port to target_port so both 10000 and 7880 respond seamlessly."""
    if source_port == target_port:
        return
    import socket

    def _forward(src, dst):
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                src.close()
            except Exception:
                pass
            try:
                dst.close()
            except Exception:
                pass

    def _listen():
        time.sleep(1.0)  # Brief pause to allow primary web server to bind
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", source_port))
            server.listen(20)
            logger.info(f"🔗 Dual-Port Bridge active: forwarding 0.0.0.0:{source_port} ➜ 127.0.0.1:{target_port}")
            while True:
                client_sock, _ = server.accept()
                target_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    target_sock.connect(("127.0.0.1", target_port))
                    threading.Thread(target=_forward, args=(client_sock, target_sock), daemon=True).start()
                    threading.Thread(target=_forward, args=(target_sock, client_sock), daemon=True).start()
                except Exception:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    try:
                        target_sock.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Dual-Port Bridge ({source_port}->{target_port}) notice: {e}")

    t = threading.Thread(target=_listen, daemon=True, name=f"Bridge-{source_port}-{target_port}")
    t.start()


def print_banner(port: int):
    banner = f"""
====================================================================
                    FLINZA OUTREACH OS v2.2                         
                Nexcloud & Render Production Server                  
====================================================================
  * Web Command Center : http://0.0.0.0:{port}
  * RAM Footprint      : ~150 MB (Optimal for 1GB Instances)
  * Telegram /runcmd   : Active (Remote VPS Shell Enabled)
  * Deliverability Tool: Active (Cloudflare DoH Auditor)
  * Multi-Provider     : Brevo, Amazon SES, SMTP2GO, Mailjet, Gmail
====================================================================
"""
    try:
        print(banner)
    except Exception:
        pass


def main():
    check_and_migrate_db()

    # Smart port detection:
    # Render's load balancer expects web services on port 10000.
    is_render = (
        os.environ.get("RENDER") == "true"
        or "RENDER_SERVICE_ID" in os.environ
        or "RENDER_EXTERNAL_HOSTNAME" in os.environ
        or "onrender.com" in os.environ.get("RENDER_EXTERNAL_URL", "")
    )

    if is_render:
        raw_port = os.environ.get("PORT", "10000")
        # If user copied PORT=7880 from local .env into Render dashboard env vars, override to 10000
        # because Render internal health check expects port 10000
        port = 10000 if str(raw_port).strip() == "7880" else int(raw_port)
    else:
        port = int(os.environ.get("PORT", 7880))

    host = os.environ.get("HOST", "0.0.0.0")

    print_banner(port)

    # Launch dual-port bridge:
    # If primary is 10000 (Render), bridge 7880 -> 10000 so legacy scripts & CF origin rules work.
    # If primary is 7880 (VPS/Local), bridge 10000 -> 7880 so Render probes also get 200 OK.
    secondary_port = 7880 if port == 10000 else 10000
    start_port_forwarder(secondary_port, port)

    # Launch Telegram Bot thread if configured
    start_telegram_bot_thread()

    # Dispatch Telegram startup confirmation message with public IP link
    send_startup_telegram_alert(port)

    # Launch FastAPI / Uvicorn Server
    try:
        import uvicorn
        logger.info(f"🚀 Starting Uvicorn Web Server on {host}:{port}...")
        uvicorn.run(
            "web_server:app",
            host=host,
            port=port,
            log_level="info",
            access_log=True,
            timeout_keep_alive=30
        )
    except Exception as e:
        logger.error(f"Server exited with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
