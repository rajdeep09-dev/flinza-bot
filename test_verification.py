import requests
import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

base = 'http://localhost:7880'

tests = [
    ('GET',  '/', None),
    ('GET',  '/api/stats', None),
    ('POST', '/api/campaign/testsend', {'to_email': 'rajdep.f12x@gmail.com'}),
    ('GET',  '/api/warmup/stats', None),
    ('POST', '/api/warmup/audit', {}),
    ('POST', '/api/score', {'subject': 'Quick idea, {{first_name}}', 'body': 'Hey {{first_name}}, loved your video on {{niche}}! Open to a quick call?'}),
    ('POST', '/api/spintax/preview', {'text': '{Hey|Hi|Hello} {{first_name}}, {open to|interested in} a {10-min|quick} chat?', 'count': 3}),
    ('POST', '/api/terminal', {'command': '/stats'}),
    ('POST', '/api/terminal', {'command': '/warmup'}),
    ('POST', '/api/unibox/check', {}),
    ('POST', '/webhook/smartlead', {'type': 'email_opened', 'lead_email': 'alex@example.com'}),
    ('GET',  '/api/analytics', None),
]

print("=== FLINZA END-TO-END VERIFICATION ===")
for method, path, body in tests:
    try:
        if method == 'GET':
            r = requests.get(base + path, timeout=10)
        else:
            r = requests.post(base + path, json=body, timeout=10)
        print(f"[{r.status_code}] {method} {path} -> {len(r.text)} bytes")
        if r.status_code == 200 and path.startswith('/api'):
            d = r.json()
            if 'score' in d:
                print(f"       Score: {d.get('score')}/100, Grade: {d.get('grade')}")
            if 'output' in d:
                print(f"       Terminal: {repr(d.get('output'))[:90]}...")
            if 'variants' in d:
                print(f"       Variants: {d.get('variants')}")
            if 'accounts' in d and isinstance(d['accounts'], list):
                print(f"       Accounts: {len(d['accounts'])} accounts loaded")
    except Exception as e:
        print(f"[FAIL] {method} {path} -> {e}")
