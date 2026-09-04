import sqlite3

db_path = "flinza.db"
conn = sqlite3.connect(db_path)

conn.execute("""
    CREATE TABLE IF NOT EXISTS ip_nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        ip_address TEXT NOT NULL,
        status TEXT DEFAULT 'connected',
        user_agent TEXT,
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

conn.commit()

tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('ip_nodes','smtp_profiles')"
).fetchall()
print("Tables created:", [t[0] for t in tables])
conn.close()
