import requests, json

base = 'http://localhost:7880'

tests = [
    ('GET',  '/api/stats',                  None),
    ('GET',  '/api/accounts',               None),
    ('GET',  '/api/leads?stage=all',        None),
    ('GET',  '/api/aliases/routing',        None),
    ('GET',  '/api/cloudflare/zones',       None),
    ('GET',  '/api/settings',               None),
    ('GET',  '/api/sequences?campaign_id=1',None),
    ('GET',  '/api/webmail/threads?folder=inbox', None),
    ('POST', '/api/unibox/check',           {}),
    ('POST', '/api/campaign/testsend',      {'to_email': 'rajdep.f12x@gmail.com'}),
]

print('=== FLINZA ENDPOINT AUDIT ===')
for method, path, body in tests:
    try:
        if method == 'GET':
            r = requests.get(base + path, timeout=10)
        else:
            r = requests.post(base + path, json=body, timeout=15)
        d = r.json()
        success = d.get('success', d.get('status', 'N/A'))
        error = d.get('error', d.get('detail', ''))
        print(f'[{r.status_code}] {method} {path}')
        print(f'       success={success}' + (f' ERR={error}' if error else ''))
        if path == '/api/accounts':
            accs = d.get('accounts', [])
            aliases = d.get('aliases', [])
            print(f'       Accounts: {len(accs)}, Aliases: {len(aliases)}')
            for a in accs:
                print(f'         - {a.get("email")} provider={a.get("provider")} daily_limit={a.get("daily_limit")}')
        if path == '/api/stats':
            stats = d.get('stats', {})
            tracking = d.get('tracking', {})
            print(f'       leads={stats.get("total_leads",0)} sent_today={stats.get("sent_today",0)} replies={stats.get("total_replies",0)} unhandled={stats.get("unhandled_replies",0)}')
            print(f'       open_rate={tracking.get("open_rate",0)}% click_rate={tracking.get("click_rate",0)}%')
        if path == '/api/campaign/testsend':
            print(f'       Result: {json.dumps(d)[:300]}')
        if 'webmail' in path:
            threads = d.get('threads', [])
            print(f'       Inbox threads: {len(threads)}')
    except Exception as e:
        print(f'[FAIL] {method} {path} -> {e}')
    print()
