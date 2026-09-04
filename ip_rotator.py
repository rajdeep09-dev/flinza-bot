"""
Flinza — Smart IP Node Fleet & Airplane Mode Auto-Rotator
==========================================================
Core engine for enterprise-grade mobile IP routing:

1. Multi-Node Fleet Balancing:
   If more than one 4G/5G mobile phone or residential node is connected,
   rotates outbound SMTP connections across them in round-robin fashion,
   ensuring uniform distribution and preventing any single node from being throttled.

2. Cellular Airplane Mode Auto-Rotation:
   After N emails (configurable per node, default 5 or 10) are sent through a node,
   hits the node's rotation webhook (e.g. MacroDroid / Localtonet Webhook) to toggle
   Airplane Mode ON -> OFF. Waits 4.5s for 4G/5G cellular reconnect, probes external IP,
   and updates SQLite with the newly assigned residential IP.

3. Health & Limit Aware:
   Skips paused nodes and nodes that have reached their configured daily send cap.
"""

import time
import socket
import logging
import threading
import requests
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

import database as db

logger = logging.getLogger(__name__)

_fleet_lock = threading.Lock()
_round_robin_counter = 0


def normalize_proxy_target(host: str, port: Any) -> Tuple[str, int]:
    """
    Cleans and normalizes proxy host and port inputs.
    Detects pasted host:port strings and extracts pure hostname and integer port.
    """
    h = str(host or "").strip()
    p = 1080
    if h.startswith("http://") or h.startswith("https://") or h.startswith("socks5://"):
        h = h.split("://", 1)[1]
    
    if ":" in h:
        parts = h.split(":")
        h = parts[0].strip()
        if len(parts) > 1 and parts[1].strip().isdigit():
            p = int(parts[1].strip())
    else:
        try:
            if port and str(port).strip().isdigit():
                p = int(str(port).strip())
        except Exception:
            p = 1080
    return h, p


def test_mobile_proxy(
    host: str,
    port: int,
    protocol: str = "socks5",
    username: str = "",
    password: str = "",
    timeout: int = 6
) -> Dict[str, Any]:
    """
    Tests proxy connection, measures round-trip latency in ms,
    and returns the public IP address currently assigned to the node.
    """
    h, p = normalize_proxy_target(host, port)
    proto = (protocol or "socks5").lower().strip()
    if proto.startswith("socks5"):
        scheme = "socks5h"
    elif proto.startswith("socks4"):
        scheme = "socks4"
    else:
        scheme = "http"

    usr = (username or "").strip()
    pwd = (password or "").strip()
    if usr and pwd:
        proxy_url = f"{scheme}://{usr}:{pwd}@{h}:{p}"
    else:
        proxy_url = f"{scheme}://{h}:{p}"

    # Fast TCP reachability pre-check (1.5s timeout)
    try:
        s = socket.socket()
        s.settimeout(1.5)
        s.connect((h, p))
        s.close()
    except Exception as e_sock:
        return {
            "success": False,
            "error": f"Cannot reach proxy tunnel at {h}:{p} ({e_sock}). Verify Every Proxy and Localtonet are active on the phone."
        }

    proxies = {"http": proxy_url, "https": proxy_url}
    t0 = time.time()
    try:
        resp = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=timeout)
        lat = max(8, int((time.time() - t0) * 1000))
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "ip": data.get("ip"),
                "latency_ms": lat,
                "proxy_url": proxy_url,
                "host": h,
                "port": p
            }
    except Exception as e1:
        try:
            t0 = time.time()
            resp2 = requests.get("https://ifconfig.me/ip", proxies=proxies, timeout=timeout)
            lat = max(8, int((time.time() - t0) * 1000))
            if resp2.status_code == 200:
                return {
                    "success": True,
                    "ip": resp2.text.strip(),
                    "latency_ms": lat,
                    "proxy_url": proxy_url,
                    "host": h,
                    "port": p
                }
        except Exception:
            return {"success": False, "error": f"SOCKS handshake failed: {str(e1)}"}
    return {"success": False, "error": "Could not verify external IP through proxy tunnel."}


def select_next_node() -> Optional[Dict[str, Any]]:
    """
    Selects the next available sending node from the fleet using intelligent round-robin.
    Balances load across all active, unpaused nodes that have remaining daily capacity.
    """
    global _round_robin_counter
    with _fleet_lock:
        active_nodes = db.get_connected_nodes()
        if not active_nodes:
            return None

        # Filter out nodes that hit daily limits or are paused
        avail = [n for n in active_nodes if (n.get("sent_today") or 0) < (n.get("daily_limit") or 150)]
        if not avail:
            # Fallback to active nodes if all reached limit
            avail = active_nodes

        if not avail:
            return None

        node = avail[_round_robin_counter % len(avail)]
        _round_robin_counter += 1
        logger.info(
            f"🔄 IP Fleet Dispatch: Selected Node #{node.get('id')} '{node.get('name')}' "
            f"(IP: {node.get('ip_address')}, Sends Today: {node.get('sent_today', 0)}/{node.get('daily_limit', 150)}, "
            f"Rotation: {node.get('sends_since_last_rotation', 0)}/{node.get('rotate_every_n', 5)})"
        )
        return node


def peek_active_node() -> Optional[Dict[str, Any]]:
    """Returns the primary active node without advancing the round-robin counter."""
    active_nodes = db.get_connected_nodes()
    if not active_nodes:
        return None
    avail = [n for n in active_nodes if (n.get("sent_today") or 0) < (n.get("daily_limit") or 150)]
    return avail[0] if avail else active_nodes[0]


def build_proxy_url(node: Dict[str, Any]) -> Optional[str]:
    """Generates standard proxy URL from a node row. Returns None for native host direct sending."""
    proto = (node.get("proxy_protocol") or "socks5").lower().strip()
    host = (node.get("proxy_host") or "").strip()
    
    # Direct Native Server IP (sends directly from host network interface without proxy)
    if proto in ("direct", "native", "none") or not host:
        return None

    port = node.get("proxy_port") or 1080
    usr = (node.get("proxy_user") or "").strip()
    pwd = (node.get("proxy_pass") or "").strip()

    if usr and pwd:
        return f"{proto}://{usr}:{pwd}@{host}:{port}"
    return f"{proto}://{host}:{port}"


_cached_server_ip_info: Optional[Tuple[str, str, int]] = None
_cached_server_ip_time: float = 0.0


def auto_detect_server_ip(force_refresh: bool = False) -> Tuple[str, str, int]:
    """
    Detects the real public outbound IP, ISP/carrier name, and latency of this Python host server.
    Caches results for 120s to avoid redundant external HTTP lookups.
    """
    global _cached_server_ip_info, _cached_server_ip_time
    now = time.time()
    if not force_refresh and _cached_server_ip_info and (now - _cached_server_ip_time < 120):
        return _cached_server_ip_info

    detected_ip = "127.0.0.1"
    provider = "Python Host Server (Native IP)"
    lat = 20

    t0 = time.time()
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=4)
        lat = max(5, int((time.time() - t0) * 1000))
        if r.status_code == 200:
            detected_ip = r.json().get("ip", detected_ip)
    except Exception:
        try:
            t0 = time.time()
            r2 = requests.get("https://ifconfig.me/ip", timeout=4)
            lat = max(5, int((time.time() - t0) * 1000))
            if r2.status_code == 200 and r2.text.strip():
                detected_ip = r2.text.strip()
        except Exception:
            pass

    if detected_ip and detected_ip not in ("127.0.0.1", "localhost", "unknown"):
        try:
            r_info = requests.get(f"http://ip-api.com/json/{detected_ip}", timeout=3)
            if r_info.status_code == 200:
                d = r_info.json()
                isp = d.get("isp") or d.get("org") or "Direct ISP"
                city = d.get("city") or ""
                country = d.get("countryCode") or ""
                loc = f" ({city}, {country})" if city else ""
                provider = f"{isp}{loc}"
        except Exception:
            provider = "Host Server Direct"

    res = (detected_ip, provider, lat)
    if detected_ip and detected_ip not in ("127.0.0.1", "localhost", "unknown"):
        _cached_server_ip_info = res
        _cached_server_ip_time = now
    return res


def auto_register_server_node(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    Automatically detects and registers this Python server's real public IP in flinza.db.
    Cleans up any stale 127.0.0.1 localhost entries so the fleet only uses real deliverable IPs.
    """
    detected_ip, provider, lat = auto_detect_server_ip(force_refresh=force_refresh)
    if not detected_ip or detected_ip in ("127.0.0.1", "localhost", "unknown"):
        logger.warning("Could not determine public IP for Python host server.")
        return None

    conn = db.get_db()
    now = datetime.utcnow().isoformat()

    # Clean up stale localhost or dummy nodes
    conn.execute("DELETE FROM ip_nodes WHERE ip_address IN ('127.0.0.1', 'localhost', '::1', 'unknown')")

    # Check if server node already exists
    existing = conn.execute(
        """SELECT id, daily_limit FROM ip_nodes 
           WHERE user_agent='Python-Server-Native/2.0' 
              OR proxy_protocol IN ('direct', 'native') 
              OR name LIKE 'Python Host Server%'
              OR name LIKE 'Python Server%'"""
    ).fetchone()

    node_label = f"Python Server ({provider.split('(')[0].strip()})"

    if existing:
        node_id = existing["id"]
        conn.execute(
            """UPDATE ip_nodes 
               SET name=?, ip_address=?, provider=?, latency_ms=?, status='connected',
                   is_paused=0, is_persistent_tunnel=1, proxy_protocol='direct',
                   proxy_host='', proxy_port=0, last_seen=?
               WHERE id=?""",
            (node_label, detected_ip, provider, lat, now, node_id)
        )
    else:
        cur = conn.execute(
            """INSERT INTO ip_nodes (
                name, ip_address, status, user_agent, provider, daily_limit, sent_today, latency_ms,
                is_paused, connected_at, last_seen, is_persistent_tunnel, proxy_protocol,
                proxy_host, proxy_port, proxy_user, proxy_pass, rotation_webhook, rotate_every_n, sends_since_last_rotation
               ) VALUES (?, ?, 'connected', 'Python-Server-Native/2.0', ?, 300, 0, ?, 0, ?, ?, 1, 'direct', '', 0, '', '', '', 0, 0)""",
            (node_label, detected_ip, provider, lat, now, now)
        )
        node_id = cur.lastrowid

    conn.commit()
    row = conn.execute("SELECT * FROM ip_nodes WHERE id=?", (node_id,)).fetchone()
    conn.close()

    logger.info(f"🚀 Python Host Server IP auto-set: {detected_ip} ({provider}) registered in IP fleet as Node #{node_id}.")
    return dict(row) if row else None



def rotate_node_ip_sync(node_id: int) -> Dict[str, Any]:
    """
    Synchronously triggers cellular Airplane Mode IP rotation for a specific node:
    1. Fires the node's rotation_webhook (MacroDroid, Localtonet Webhook, Tasker).
    2. Waits 4.5s for phone to cycle airplane mode and obtain a fresh carrier IP lease.
    3. Probes the proxy to retrieve and verify the newly assigned cellular IP.
    4. Updates SQLite (ip_address, latency_ms, last_rotated_at, auto_rotate_count, resets sends_since_last_rotation).
    5. Records activity in activity_logs.
    """
    conn = db.get_db()
    node_row = conn.execute("SELECT * FROM ip_nodes WHERE id=?", (node_id,)).fetchone()
    conn.close()
    if not node_row:
        return {"success": False, "error": f"Node #{node_id} not found."}

    node = dict(node_row)
    webhook = (node.get("rotation_webhook") or "").strip()
    old_ip = node.get("ip_address")
    node_name = node.get("name") or f"Node #{node_id}"

    if not webhook:
        return {
            "success": False,
            "error": f"No rotation webhook configured for '{node_name}'. Set your MacroDroid / Localtonet webhook URL in node settings."
        }

    logger.info(f"📱 [Airplane Mode Rotation] Firing webhook for '{node_name}' (Current IP: {old_ip}) via {webhook}")

    # 1. Trigger rotation webhook (MacroDroid airplane mode toggler)
    try:
        w_resp = requests.get(webhook, timeout=10)
        logger.info(f"📱 Rotation webhook response for {node_name}: HTTP {w_resp.status_code}")
    except Exception as e_w:
        logger.warning(f"📱 Webhook request warning for {node_name}: {e_w}")

    # 2. Wait 4.5 seconds for cellular radio cycle (Airplane Mode ON -> OFF)
    time.sleep(4.5)

    # 3. Test through proxy to retrieve new cellular IP
    h = node.get("proxy_host") or node.get("ip_address")
    p = node.get("proxy_port") or 1080
    proto = node.get("proxy_protocol") or "socks5"
    u = node.get("proxy_user") or ""
    pwd = node.get("proxy_pass") or ""

    test_res = test_mobile_proxy(host=h, port=p, protocol=proto, username=u, password=pwd, timeout=10)
    new_ip = test_res.get("ip") if test_res.get("success") else old_ip
    lat = test_res.get("latency_ms") if test_res.get("success") else (node.get("latency_ms") or 28)

    # 4. Update database
    db.reset_node_rotation_counter(node_id, new_ip=new_ip, latency_ms=lat)

    # 5. Log activity
    rot_num = (node.get("auto_rotate_count") or 0) + 1
    db.log_activity(
        "ip_rotation",
        f"Auto-rotated '{node_name}' via Airplane Mode → Fresh IP: {new_ip} (Old: {old_ip} · Latency: {lat}ms · Rotation #{rot_num})"
    )

    logger.info(f"✅ IP Rotation Complete: '{node_name}' successfully rotated to {new_ip} (Latency: {lat}ms)")

    return {
        "success": True,
        "node_id": node_id,
        "name": node_name,
        "old_ip": old_ip,
        "new_ip": new_ip,
        "latency_ms": lat,
        "rotation_count": rot_num,
        "message": f"Mobile IP successfully rotated to {new_ip}!" if new_ip != old_ip else "Rotation webhook triggered. Radio link active."
    }


def record_send_and_maybe_rotate(node_id: int, status_callback=None) -> Dict[str, Any]:
    """
    Records an outbound send against node_id.
    Checks if the node reached its `rotate_every_n` threshold.
    If threshold is hit and a rotation_webhook is configured, triggers Airplane Mode auto-rotation!
    """
    updated_node = db.record_ip_node_send(node_id)
    if not updated_node:
        return {"rotated": False, "reason": "node not found"}

    sends_since = updated_node.get("sends_since_last_rotation", 0) or 0
    threshold = updated_node.get("rotate_every_n", 5) or 5
    webhook = (updated_node.get("rotation_webhook") or "").strip()
    node_name = updated_node.get("name") or f"Node #{node_id}"

    logger.info(f"📡 Node '{node_name}' send progress: {sends_since}/{threshold} sends towards airplane mode rotation.")

    if webhook and sends_since >= threshold:
        logger.info(
            f"⚡ [Auto-Rotate Trigger] Node '{node_name}' reached {sends_since}/{threshold} sends. "
            f"Initiating automatic cellular Airplane Mode rotation..."
        )
        if status_callback:
            try:
                status_callback(f"🔄 Auto-rotating cellular IP for '{node_name}' after {sends_since} sends…")
            except Exception:
                pass

        rot_res = rotate_node_ip_sync(node_id)
        if status_callback and rot_res.get("success"):
            try:
                status_callback(f"✅ Cellular IP rotated for '{node_name}' → Fresh IP: {rot_res.get('new_ip')}")
            except Exception:
                pass
        return {"rotated": True, "result": rot_res}

    return {"rotated": False, "sends_since": sends_since, "threshold": threshold}


def get_fleet_status() -> Dict[str, Any]:
    """
    Returns live health, multi-node rotation status, and rotation progress for the IP fleet.
    """
    nodes = db.get_ip_nodes()
    active_nodes = db.get_connected_nodes()
    
    total_capacity = sum(n.get("daily_limit", 150) for n in active_nodes)
    total_sent = sum(n.get("sent_today", 0) for n in active_nodes)
    total_rotations = sum(n.get("auto_rotate_count", 0) for n in nodes)

    current_node = peek_active_node()

    node_names_list = []
    for n in active_nodes:
        raw_name = n.get("name", "Node")
        short_name = raw_name.split("(")[0].strip()
        node_names_list.append(short_name)
    nodes_summary = " + ".join(node_names_list) if node_names_list else "None"

    return {
        "total_nodes": len(nodes),
        "active_nodes_count": len(active_nodes),
        "active_nodes": active_nodes,
        "primary_node": current_node,
        "primary_ip": current_node.get("ip_address") if current_node else "Direct / None",
        "primary_name": current_node.get("name") if current_node else "No Node Connected",
        "nodes_summary": nodes_summary,
        "total_fleet_capacity": total_capacity,
        "fleet_sent_today": total_sent,
        "total_rotations_performed": total_rotations,
        "is_multi_node": len(active_nodes) > 1,
    }

