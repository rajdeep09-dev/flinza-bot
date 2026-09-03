import requests
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

base = 'http://localhost:7880'

tests = [
    ('GET',  '/', None),
    ('GET',  '/api/stats', None),
    ('GET',  '/api/pool/status', None),
    ('POST', '/api/leads/verify-all', {}),
    ('GET',  '/api/aliases/routing', None),
    ('POST', '/api/campaign/testsend', {'to_email': 'rajdep.f12x@gmail.com'}),
    ('GET',  '/api/warmup/stats', None),
    ('POST', '/api/warmup/audit', {}),
    ('POST', '/api/score', {'subject': 'Quick idea, {{first_name}}', 'body': 'Hey {{first_name}}, loved your video on {{niche}}! Open to a quick call?'}),
    ('POST', '/api/spintax/preview', {
        'text': '{Hey|Hi|Hello} {{first_name|there}}, {open to|interested in} a {10-min|quick} chat?',
        'count': 3,
        'mock_lead': {'name': 'Sarah Connor', 'company': 'Cyberdyne'}
    }),
    ('POST', '/api/terminal', {'command': '/stats'}),
    ('POST', '/api/terminal', {'command': '/pool'}),
    ('POST', '/api/terminal', {'command': '/cleanleads'}),
    ('POST', '/api/unibox/check', {}),
    ('GET',  '/t/o/sample_lead_token.png', None),
    ('GET',  '/u/sample_lead_token?email=test_lead@example.com', None),
    ('POST', '/webhook/smartlead', {'type': 'email_opened', 'lead_email': 'alex@example.com'}),
    ('GET',  '/api/analytics', None),
]

print("=== FLINZA ENTERPRISE END-TO-END VERIFICATION ===")
for method, path, body in tests:
    try:
        if method == 'GET':
            r = requests.get(base + path, timeout=10)
        else:
            r = requests.post(base + path, json=body, timeout=10)
        print(f"[{r.status_code}] {method} {path} -> {len(r.content)} bytes")
        if r.status_code == 200 and path.startswith('/api'):
            d = r.json()
            if 'score' in d and 'grade' in d:
                print(f"       Deliverability: {d.get('score')}/100 (Grade: {d.get('grade')})")
            if 'output' in d:
                print(f"       CLI: {repr(d.get('output'))[:90]}...")
            if 'variants' in d:
                print(f"       Clean Spintax: {d.get('variants')}")
                print(f"       Entropy: {d.get('entropy_score')}% | Combinations: {d.get('combinations')}")
            if 'fleet_daily_capacity' in d:
                print(f"       Mailbox Pool: {d.get('active_available')} active | Capacity: {d.get('fleet_daily_capacity')}/day")
            if 'dead_bounced' in d:
                print(f"       Zero-Bounce: {d.get('scanned')} scanned | {d.get('deliverable')} clean | {d.get('dead_bounced')} dead filtered")
            if path == '/api/aliases/routing' and 'accounts' in d and len(d['accounts']) > 0:
                sample = d['accounts'][0]
                pw = sample.get('app_password') or sample.get('smtp_pass')
                print(f"       Credential Masking: {'MASKED (OK)' if pw == '••••••••••••' else 'RAW (ALERT)'}")
    except Exception as e:
        print(f"[FAIL] {method} {path} -> {e}")
