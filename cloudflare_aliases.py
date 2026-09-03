"""
Flinza — Cloudflare Email Routing Alias Generator
Creates random or custom email addresses on your CF domain that
forward to your master Gmail, then registers them as SMTP aliases.

CF API reference: https://developers.cloudflare.com/email-routing/
"""

import random
import string
import logging
import requests

import database as db

logger = logging.getLogger(__name__)

CF_BASE = "https://api.cloudflare.com/client/v4"


def _get_cf_creds() -> dict | None:
    """Read CF credentials from DB settings (user may have set them via bot)."""
    token      = db.get_setting("cf_api_token", "")
    account_id = db.get_setting("cf_account_id", "")
    zone_id    = db.get_setting("cf_zone_id", "")
    domain     = db.get_setting("cf_domain", "")
    if not all([token, zone_id, domain]):
        return None
    return {"token": token, "account_id": account_id, "zone_id": zone_id, "domain": domain}


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def verify_cf_config() -> dict:
    """Test CF credentials. Returns {success, error, zone_info}."""
    creds = _get_cf_creds()
    if not creds:
        return {"success": False, "error": "Cloudflare credentials not set. Use /cfconfig to configure."}
    try:
        r = requests.get(
            f"{CF_BASE}/zones/{creds['zone_id']}",
            headers=_headers(creds["token"]),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("success"):
            zone = data["result"]
            return {"success": True, "zone_name": zone["name"], "status": zone["status"]}
        return {"success": False, "error": str(data.get("errors"))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ensure_destination_verified(master_email: str) -> dict:
    """
    Check/create a destination address (forwarding target) on CF.
    CF will send a verification email — the user must click it once.
    Returns {success, status, error}
    """
    creds = _get_cf_creds()
    if not creds or not creds.get("account_id"):
        return {"success": False, "error": "CF account_id not set"}
    try:
        # List existing destinations
        r = requests.get(
            f"{CF_BASE}/accounts/{creds['account_id']}/email/routing/addresses",
            headers=_headers(creds["token"]),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        existing = [a["email"].lower() for a in data.get("result", [])]

        if master_email.lower() in existing:
            return {"success": True, "status": "already_exists"}

        # Create destination
        r2 = requests.post(
            f"{CF_BASE}/accounts/{creds['account_id']}/email/routing/addresses",
            headers=_headers(creds["token"]),
            json={"email": master_email},
            timeout=10,
        )
        r2.raise_for_status()
        data2 = r2.json()
        if data2.get("success"):
            return {"success": True, "status": "created_pending_verification",
                    "message": f"Verification email sent to {master_email}. Click the link in it."}
        return {"success": False, "error": str(data2.get("errors"))}

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_alias(custom_local: str, master_email: str, display_name: str = None) -> dict:
    """
    Create a single CF email routing rule:
    custom_local@domain → master_email (forwarded via Gmail)
    Returns {success, alias, rule_id, error}
    """
    creds = _get_cf_creds()
    if not creds:
        return {"success": False, "error": "Cloudflare not configured"}

    full_alias = f"{custom_local.lower()}@{creds['domain']}"

    # Check if alias already exists in our DB
    existing_aliases = [a["alias"].lower() for a in db.get_all_aliases()]
    if full_alias.lower() in existing_aliases:
        return {"success": False, "error": f"{full_alias} already exists in DB"}

    try:
        payload = {
            "actions":  [{"type": "forward", "value": [master_email]}],
            "enabled":  True,
            "matchers": [{"field": "to", "type": "literal", "value": full_alias}],
            "name":     display_name or custom_local,
            "priority": 1,
        }
        r = requests.post(
            f"{CF_BASE}/zones/{creds['zone_id']}/email/routing/rules",
            headers=_headers(creds["token"]),
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        if data.get("success"):
            rule_id = data["result"]["id"]
            # Register in DB as alias for the master Gmail
            # Find master account's app_password
            accs = [a for a in db.get_all_accounts() if a["email"].lower() == master_email.lower()]
            smtp_pass = accs[0]["app_password"] if accs else None

            db.add_alias(
                alias=full_alias,
                smtp_user=master_email,
                smtp_pass=smtp_pass,
                display_name=display_name or custom_local.replace("-", " ").replace("_", " ").title(),
                source="cloudflare",
                cf_rule_id=rule_id,
            )
            logger.info(f"CF alias created: {full_alias} → {master_email}")
            return {"success": True, "alias": full_alias, "rule_id": rule_id}

        errors = data.get("errors", [])
        return {"success": False, "error": "; ".join(e.get("message", str(e)) for e in errors)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_random_aliases(count: int, master_email: str, prefix: str = "") -> list:
    """
    Generate `count` random aliases and register them via CF API.
    Returns list of result dicts {success, alias, rule_id, error}.
    """
    results = []
    for _ in range(count):
        suffix   = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        local    = f"{prefix}{suffix}" if prefix else f"reach{suffix}"
        result   = create_alias(local, master_email)
        results.append(result)
    return results


def generate_word_aliases(count: int, master_email: str) -> list:
    """Generate human-looking aliases like outreach-team-x7k2."""
    WORDS_A = ["connect", "reach", "hello", "partner", "collab", "team", "info", "hi"]
    WORDS_B = ["hub", "hq", "central", "studio", "lab", "works", "desk", "base"]
    results = []
    for _ in range(count):
        w1     = random.choice(WORDS_A)
        w2     = random.choice(WORDS_B)
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
        local  = f"{w1}-{w2}-{suffix}"
        result = create_alias(local, master_email)
        results.append(result)
    return results


def delete_cf_rule(rule_id: str) -> dict:
    """Delete a CF routing rule by its rule ID."""
    creds = _get_cf_creds()
    if not creds:
        return {"success": False, "error": "Cloudflare not configured"}
    try:
        r = requests.delete(
            f"{CF_BASE}/zones/{creds['zone_id']}/email/routing/rules/{rule_id}",
            headers=_headers(creds["token"]),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return {"success": data.get("success", False)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_user_zones(token: str = None) -> list:
    """Fetches all active zones (domains) accessible by the token."""
    tk = token or db.get_setting("cf_api_token", "") or config.CF_API_TOKEN
    if not tk:
        return []
    try:
        r = requests.get(f"{CF_BASE}/zones?status=active&per_page=50", headers=_headers(tk), timeout=10)
        if r.status_code == 200:
            data = r.json()
            return [
                {
                    "id": z["id"],
                    "name": z["name"],
                    "status": z["status"],
                    "account_id": z.get("account", {}).get("id", ""),
                    "account_name": z.get("account", {}).get("name", ""),
                }
                for z in data.get("result", [])
            ]
        return []
    except Exception as e:
        logger.error(f"Error fetching CF zones: {e}")
        return []


def audit_domain_dns(domain: str) -> dict:
    """
    Performs deep DNS deliverability audit for SPF, DKIM, DMARC, and MX records.
    Returns audit details, score (0-100), and caches the result.
    """
    import dns.resolver

    domain = domain.lower().strip()
    score = 100
    spf_status, spf_record = "Missing", ""
    dmarc_status, dmarc_record = "Missing", ""
    dkim_status, dkim_record = "Unverified", ""
    mx_status, mx_records = "Missing", []

    # 1. Check MX Records
    try:
        mx_answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        mx_records = [str(r.exchange).rstrip(".") for r in mx_answers]
        if mx_records:
            mx_status = "Valid"
        else:
            mx_status = "No MX"
            score -= 30
    except Exception:
        mx_status = "Failed"
        score -= 30

    # 2. Check SPF
    try:
        txt_answers = dns.resolver.resolve(domain, "TXT", lifetime=5)
        for rdata in txt_answers:
            txt = "".join(s.decode("utf-8") if isinstance(s, bytes) else str(s) for s in rdata.strings)
            if "v=spf1" in txt:
                spf_record = txt
                if "include:_spf.google.com" in txt or "include:_spf.mx.cloudflare.net" in txt or "~all" in txt or "-all" in txt:
                    spf_status = "Optimal"
                else:
                    spf_status = "Basic"
                break
        if spf_status == "Missing":
            score -= 25
    except Exception:
        score -= 25

    # 3. Check DMARC
    try:
        dmarc_answers = dns.resolver.resolve(f"_dmarc.{domain}", "TXT", lifetime=5)
        for rdata in dmarc_answers:
            txt = "".join(s.decode("utf-8") if isinstance(s, bytes) else str(s) for s in rdata.strings)
            if "v=DMARC1" in txt:
                dmarc_record = txt
                if "p=reject" in txt or "p=quarantine" in txt:
                    dmarc_status = "Protected"
                else:
                    dmarc_status = "Monitoring (p=none)"
                break
        if dmarc_status == "Missing":
            score -= 20
    except Exception:
        score -= 20

    # 4. Check Google DKIM
    try:
        dkim_answers = dns.resolver.resolve(f"google._domainkey.{domain}", "TXT", lifetime=5)
        for rdata in dkim_answers:
            txt = "".join(s.decode("utf-8") if isinstance(s, bytes) else str(s) for s in rdata.strings)
            if "v=DKIM1" in txt or "p=" in txt:
                dkim_record = txt
                dkim_status = "Verified"
                break
    except Exception:
        dkim_status = "Selector Not Found"
        score -= 10

    score = max(0, min(100, score))
    db.save_dns_audit(
        domain=domain,
        spf_record=spf_record,
        spf_status=spf_status,
        dkim_record=dkim_record,
        dkim_status=dkim_status,
        dmarc_record=dmarc_record,
        dmarc_status=dmarc_status,
        mx_status=mx_status,
        score=score,
    )

    return {
        "domain": domain,
        "score": score,
        "spf_status": spf_status,
        "spf_record": spf_record,
        "dmarc_status": dmarc_status,
        "dmarc_record": dmarc_record,
        "dkim_status": dkim_status,
        "dkim_record": dkim_record,
        "mx_status": mx_status,
        "mx_records": mx_records,
    }


def toggle_cf_rule(rule_id: str, enabled: bool) -> dict:
    """Enable or disable a CF routing rule."""
    creds = _get_cf_creds()
    if not creds:
        return {"success": False, "error": "Cloudflare not configured"}
    try:
        r = requests.patch(
            f"{CF_BASE}/zones/{creds['zone_id']}/email/routing/rules/{rule_id}",
            headers=_headers(creds["token"]),
            json={"enabled": enabled},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return {"success": data.get("success", False)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_multiple_aliases(master_email: str, count: int = 5, domain: str = None) -> list:
    """Generates professional agency aliases and binds them to the master Gmail."""
    agency_prefixes = [
        "growth", "partnerships", "hello", "reach", "outreach",
        "client", "connect", "campaigns", "media", "success", "vip"
    ]
    random.shuffle(agency_prefixes)
    created = []
    for prefix in agency_prefixes:
        if len(created) >= count:
            break
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
        alias_local = f"{prefix}.{suffix}"
        res = create_alias(alias_local, master_email, display_name=f"Flinza {prefix.title()}")
        if res.get("success"):
            created.append(res)
    return created

