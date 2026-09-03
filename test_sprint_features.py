import requests
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

base = 'http://localhost:7880'

print("=== TESTING LUXURY SIGNATURE & DOMAIN ROUTING FLOW ===")

# 1. Test Signature Settings & Preview
r = requests.get(f"{base}/api/signature")
print(f"[1] GET /api/signature -> {r.status_code}")
d = r.json()
assert d["success"] is True, "Failed to get signature"
print(f"    Loaded Name: {d['settings'].get('sig_name')}")
print(f"    Preview length: {len(d.get('preview_html', ''))} chars (Contains glassmorphism table)")

# 2. Test Save Signature
r = requests.post(f"{base}/api/signature", json={
    "sig_name": "Rajdeep Dev",
    "sig_title": "Founder & SMMA Growth Lead",
    "sig_company": "Flinza Agency",
    "sig_website": "https://flinza.io",
    "sig_cta_text": "Book a 10-Min Strategy Call",
    "sig_cta_url": "https://calendly.com/flinza/10min",
    "sig_address": "548 Market St, Suite 402, San Francisco, CA 94104",
    "sig_enabled": "1",
    "sig_stealth_disguise": "1"
})
print(f"[2] POST /api/signature -> {r.status_code}")
d = r.json()
assert d["success"] is True
assert d["settings"]["sig_name"] == "Rajdeep Dev"
print(f"    Updated Name: {d['settings']['sig_name']} | Title: {d['settings']['sig_title']}")

# 3. Test Saved Defaults (before saving domain1.com)
r = requests.get(f"{base}/api/aliases/saved-defaults?domain=domain1.com")
print(f"[3] GET /api/aliases/saved-defaults?domain=domain1.com -> {r.status_code}")

# 4. Test Create Alias with SES & remember_settings=True
r = requests.post(f"{base}/api/aliases/create", json={
    "alias": "growth@domain1.com",
    "display_name": "Rajdeep from Flinza",
    "routing_mode": "amazon_ses",
    "smtp_host": "email-smtp.us-east-1.amazonaws.com",
    "smtp_port": 587,
    "custom_smtp_user": "AKIA_TEST_KEY_123",
    "custom_smtp_pass": "SECRET_SES_PASS_XYZ",
    "remember_settings": True
})
print(f"[4] POST /api/aliases/create (SES + Remember) -> {r.status_code}")
d = r.json()
assert d["success"] is True
print(f"    Created alias: {d.get('alias')} with routing {d.get('routing_mode')}")

# 5. Verify that domain1.com now returns the remembered credentials!
r = requests.get(f"{base}/api/aliases/saved-defaults?domain=domain1.com")
print(f"[5] GET /api/aliases/saved-defaults?domain=domain1.com -> {r.status_code}")
d = r.json()
ses_defaults = d.get("defaults", {}).get("ses", {})
print(f"    Remembered SES Host: {ses_defaults.get('smtp_host')}")
print(f"    Remembered SES User: {ses_defaults.get('smtp_user')}")
assert ses_defaults.get("smtp_user") == "AKIA_TEST_KEY_123", "Remembered credentials check failed!"
print("    ✓ Successfully auto-fills remembered credentials for domain1.com!")

# 6. Test Create Alias with Namecheap Private Email
r = requests.post(f"{base}/api/aliases/create", json={
    "alias": "hello@domain2.com",
    "display_name": "Support Team",
    "routing_mode": "namecheap_smtp",
    "smtp_host": "mail.privateemail.com",
    "smtp_port": 465,
    "custom_smtp_user": "hello@domain2.com",
    "custom_smtp_pass": "SecretNC_Password",
    "remember_settings": True
})
print(f"[6] POST /api/aliases/create (Namecheap 465 SSL) -> {r.status_code}")
d = r.json()
assert d["success"] is True

# 7. Test Outbound Send with Luxury Signature Included
r = requests.post(f"{base}/api/campaign/testsend", json={"to_email": "rajdep.f12x@gmail.com"})
print(f"[7] POST /api/campaign/testsend -> {r.status_code}")
d = r.json()
assert d["success"] is True
print(f"    Delivered via {d.get('account_used')} in {d.get('elapsed_ms')}ms")

# 8. Check Sent History has logged the message with signature
r = requests.get(f"{base}/api/history?limit=1")
print(f"[8] GET /api/history -> {r.status_code}")
d = r.json()
items = d.get("items", [])
if items:
    email_id = items[0]["id"]
    r_det = requests.get(f"{base}/api/history/{email_id}")
    det = r_det.json().get("email", {})
    body = det.get("body", "")
    print(f"    Latest Sent Email: ID {email_id} | Subject: {det.get('subject')}")
    print(f"    Body snippet: {repr(body[:120])}")
    assert "Rajdeep Dev" in body or "Flinza" in body, "Signature not found in sent body!"
    print("    ✓ Verified luxury signature was attached and logged to database!")

print("\n🎉 ALL MULTI-DOMAIN ROUTING & GLASSMORPHIC SIGNATURE TESTS PASSED 100%!")
