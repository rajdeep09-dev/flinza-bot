-- supabase_schema.sql — auto-extracted from database.py init_db,
-- SQLite -> Postgres mapping applied. Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS leads (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE NOT NULL,
    handle TEXT,
    platform TEXT DEFAULT 'email',
    followers INTEGER,
    tier TEXT,
    bio TEXT,
    niche TEXT,
    company TEXT,
    website TEXT,
    stage TEXT DEFAULT 'new',
    source TEXT,
    score INTEGER DEFAULT 0,
    blacklisted INTEGER DEFAULT 0,
    unsubscribed INTEGER DEFAULT 0,
    notes TEXT,
    custom_hook TEXT,
    linkedin TEXT,
    ai_subject TEXT,
    ai_draft TEXT,
    deliverability_status TEXT DEFAULT 'unverified',
    deliverability_score INTEGER DEFAULT 100,
    last_audit_details TEXT,
    added_at TIMESTAMP DEFAULT now(),
    last_contact TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gmail_accounts (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    app_password TEXT NOT NULL,
    daily_limit INTEGER DEFAULT 50,
    sent_today INTEGER DEFAULT 0,
    last_reset_date TEXT,
    active INTEGER DEFAULT 1,
    proxy_url TEXT,
    warmup_mode INTEGER DEFAULT 0,
    warmup_day INTEGER DEFAULT 1,
    label TEXT,
    provider TEXT DEFAULT 'smtp',
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_user TEXT,
    smtp_pass TEXT,
    added_at TIMESTAMP DEFAULT now(),
    last_used TIMESTAMP
);

CREATE TABLE IF NOT EXISTS smtp_aliases (
    id BIGSERIAL PRIMARY KEY,
    alias TEXT UNIQUE NOT NULL,
    display_name TEXT,
    smtp_user TEXT NOT NULL,
    smtp_pass TEXT,
    daily_sent INTEGER DEFAULT 0,
    daily_limit INTEGER DEFAULT 20,
    last_reset TEXT,
    is_active INTEGER DEFAULT 1,
    warmup_day INTEGER DEFAULT 1,
    source TEXT DEFAULT 'manual',
    cf_rule_id TEXT,
    routing_mode TEXT DEFAULT 'gmail_send_as',
    smtp_host TEXT,
    smtp_port INTEGER,
    custom_smtp_user TEXT,
    custom_smtp_pass TEXT,
    forward_to TEXT,
    added_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS emails_sent (
    id BIGSERIAL PRIMARY KEY,
    lead_id INTEGER,
    from_account TEXT,
    to_email TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    message_type TEXT DEFAULT 'opener',
    status TEXT DEFAULT 'queued',
    queued_at TIMESTAMP DEFAULT now(),
    sent_at TIMESTAMP,
    scheduled_for TIMESTAMP,
    error_msg TEXT,
    message_id TEXT,
    campaign_id INTEGER,
    is_starred INTEGER DEFAULT 0,
    provider TEXT DEFAULT 'amazon_ses',
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS replies (
    id BIGSERIAL PRIMARY KEY,
    lead_id INTEGER,
    from_email TEXT,
    to_email TEXT,
    received_at TIMESTAMP DEFAULT now(),
    subject TEXT,
    body TEXT,
    sentiment TEXT,
    intent TEXT,
    ai_draft_subject TEXT,
    ai_draft_body TEXT,
    handled INTEGER DEFAULT 0,
    action_taken TEXT,
    is_read INTEGER DEFAULT 0,
    is_starred INTEGER DEFAULT 0,
    message_id TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id BIGSERIAL PRIMARY KEY,
    lead_id INTEGER,
    role TEXT,
    content TEXT,
    timestamp TIMESTAMP DEFAULT now(),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS followups_scheduled (
    id BIGSERIAL PRIMARY KEY,
    lead_id INTEGER,
    scheduled_for TIMESTAMP,
    followup_number INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT now(),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS templates (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    type TEXT DEFAULT 'opener',
    subject TEXT,
    body TEXT,
    use_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    status TEXT DEFAULT 'draft',
    total_leads INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    bounce_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT now(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blacklist (
    id BIGSERIAL PRIMARY KEY,
    email TEXT,
    domain TEXT,
    reason TEXT,
    added_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS activity_log (
    id BIGSERIAL PRIMARY KEY,
    action TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT,
    google_id TEXT,
    role TEXT DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT now(),
    last_login TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id BIGSERIAL PRIMARY KEY,
    account_email TEXT UNIQUE NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry TIMESTAMP,
    client_id TEXT,
    client_secret TEXT,
    scopes TEXT,
    provider TEXT DEFAULT 'google',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS campaign_sequences (
    id BIGSERIAL PRIMARY KEY,
    campaign_id INTEGER,
    step_number INTEGER NOT NULL,
    delay_days INTEGER DEFAULT 3,
    condition_type TEXT DEFAULT 'always',
    subject_a TEXT NOT NULL,
    body_a TEXT NOT NULL,
    subject_b TEXT,
    body_b TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_tracking (
    id BIGSERIAL PRIMARY KEY,
    email_id INTEGER UNIQUE,
    tracking_token TEXT UNIQUE NOT NULL,
    opened_at TIMESTAMP,
    open_count INTEGER DEFAULT 0,
    clicked_at TIMESTAMP,
    click_count INTEGER DEFAULT 0,
    last_user_agent TEXT,
    last_ip TEXT,
    created_at TIMESTAMP DEFAULT now(),
    FOREIGN KEY (email_id) REFERENCES emails_sent(id)
);

CREATE TABLE IF NOT EXISTS custom_api_endpoints (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    provider_type TEXT DEFAULT 'openai_compatible',
    base_url TEXT NOT NULL,
    api_key TEXT,
    model_name TEXT NOT NULL,
    temperature REAL DEFAULT 0.85,
    max_tokens INTEGER DEFAULT 2048,
    custom_headers_json TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dns_audit_cache (
    id BIGSERIAL PRIMARY KEY,
    domain TEXT UNIQUE NOT NULL,
    spf_record TEXT,
    spf_status TEXT,
    dkim_record TEXT,
    dkim_status TEXT,
    dmarc_record TEXT,
    dmarc_status TEXT,
    mx_record TEXT,
    mx_status TEXT,
    overall_score INTEGER DEFAULT 0,
    last_audited TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS webhooks (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    events_json TEXT,
    secret TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ip_nodes (
    id BIGSERIAL PRIMARY KEY,
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
    connected_at TIMESTAMP DEFAULT now(),
    last_seen TIMESTAMP DEFAULT now(),
    assigned_accounts TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS smtp_profiles (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT DEFAULT 'custom',
    smtp_host TEXT NOT NULL,
    smtp_port INTEGER DEFAULT 587,
    smtp_user TEXT NOT NULL,
    smtp_pass TEXT,
    use_ssl INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT now()
);
