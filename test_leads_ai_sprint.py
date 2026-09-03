import requests
import json
import csv
import io
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

base = 'http://localhost:7880'

print("=== TESTING LEADS CRM AI HYPER-PERSONALIZATION & ZERO-BOUNCE SUITE ===")

# 1. Test Download Sample CSV
r = requests.get(f"{base}/api/leads/sample-csv")
print(f"[1] GET /api/leads/sample-csv -> {r.status_code}")
assert r.status_code == 200
assert "attachment; filename=" in r.headers.get("Content-Disposition", "")
reader = list(csv.reader(io.StringIO(r.text)))
headers = reader[0]
print(f"    CSV Headers: {headers}")
assert "custom_hook" in headers
assert "linkedin" in headers
assert len(reader) >= 6 # Header + 5 rows
print(f"    Sample lead 1: {reader[1]}")
print("    ✓ Sample CSV download correctly formatted with AI personalization headers!")

# 2. Test Upload Leads CSV with Custom Hooks
test_csv = """first_name,last_name,email,company,niche,website,linkedin,custom_hook
Taylor,Mason,taylor@vanguardcapital.co,Vanguard Capital,Fintech VC,https://vanguardcapital.co,https://linkedin.com/in/taylormason,Saw your recent investment thesis on AI agent infrastructure
Zack,Kass,zack@hyperagency.io,HyperAgency,E-Commerce Ads,https://hyperagency.io,https://linkedin.com/in/zackkass,Loved your TikTok breakdown of scaling Shopify DTC brands
Dead,Test,dead_user_fake_domain_xyz9812@nonexistentdomain123891823.com,Fake Org,Software,,,This should bounce on DNS
"""
r = requests.post(f"{base}/api/leads/upload-csv", json={"csv_text": test_csv})
print(f"[2] POST /api/leads/upload-csv -> {r.status_code}")
d = r.json()
assert d["success"] is True
print(f"    Imported: {d.get('imported_count')} leads")
assert d["imported_count"] == 3

# 3. Test Fetch Leads
r = requests.get(f"{base}/api/leads?stage=all")
print(f"[3] GET /api/leads?stage=all -> {r.status_code}")
d = r.json()
leads = d.get("leads", [])
print(f"    Total leads in CRM: {len(leads)}")
target_lead = next((l for l in leads if l["email"] == "taylor@vanguardcapital.co"), None)
assert target_lead is not None
print(f"    Found imported lead: {target_lead['name']} ({target_lead['company']}) | Hook: {target_lead.get('custom_hook')}")

# 4. Test Single Lead AI Hyper-Personalized Generation
lead_id = target_lead["id"]
r = requests.post(f"{base}/api/leads/{lead_id}/ai-draft")
print(f"[4] POST /api/leads/{lead_id}/ai-draft -> {r.status_code}")
d = r.json()
assert d["success"] is True
print(f"    Generated AI Subject: {d.get('ai_subject')}")
print(f"    Generated AI Body snippet: {repr(d.get('ai_draft', '')[:100])}...")
assert len(d.get("ai_draft", "")) > 20

# 5. Test Batch AI Generation for All Leads
r = requests.post(f"{base}/api/leads/generate-ai-batch")
print(f"[5] POST /api/leads/generate-ai-batch -> {r.status_code}")
d = r.json()
assert d["success"] is True
print(f"    Batch generated pitches for {d.get('generated_count')} leads!")

# 6. Test Deep Deliverability Audit on Single Lead
r = requests.post(f"{base}/api/leads/{lead_id}/verify-deep")
print(f"[6] POST /api/leads/{lead_id}/verify-deep -> {r.status_code}")
d = r.json()
assert d["success"] is True
audit = d.get("audit", {})
print(f"    Audit for {audit.get('email')}: Status={audit.get('status')} | Score={audit.get('score')} | MX={audit.get('primary_mx')}")

# 7. Test Deep Verification Across All Leads (including fake domain)
r = requests.post(f"{base}/api/leads/verify-all-deep")
print(f"[7] POST /api/leads/verify-all-deep -> {r.status_code}")
d = r.json()
assert d["success"] is True
print(f"    Deep Audit Results: Scanned={d.get('scanned')}, Clean={d.get('clean_count')}, Catch-All={d.get('catchall_count')}, Dead/Filtered={d.get('dead_count')}")
assert d.get("dead_count") >= 1, "Fake domain was not flagged as dead!"
print("    ✓ Successfully detected and isolated unresolvable email to prevent bounce!")

print("\n🎉 ALL LEADS CRM AI HYPER-PERSONALIZATION & ZERO-BOUNCE TESTS PASSED 100%!")
