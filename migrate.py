"""
Flinza — Migrate accounts from MagicFit parent bot database.
Run once: python migrate.py
"""
import sqlite3
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Path to the parent magicfitbot database
PARENT_DB = os.path.join(os.path.dirname(__file__), "..", "outreach.db")

def migrate():
    if not os.path.exists(PARENT_DB):
        print(f"Parent DB not found at: {PARENT_DB}")
        sys.exit(1)

    # Init flinza DB first
    import database as db
    db.init_db()

    parent = sqlite3.connect(PARENT_DB)
    parent.row_factory = sqlite3.Row

    # --- Import Gmail accounts ---
    accounts = parent.execute("SELECT * FROM gmail_accounts").fetchall()
    acc_added = 0
    for a in accounts:
        ok = db.add_account(
            email=a["email"],
            app_password=a["app_password"],
            daily_limit=a["daily_limit"] or 50,
        )
        if ok:
            # If account was inactive in parent, keep it active here
            print(f"  ✅ Account: {a['email']} (limit: {a['daily_limit']})")
            acc_added += 1
        else:
            print(f"  ⏩ Account already exists: {a['email']}")

    # --- Import SMTP aliases ---
    try:
        aliases = parent.execute("SELECT * FROM smtp_aliases").fetchall()
        alias_added = 0
        for al in aliases:
            smtp_pass = al["smtp_pass"] if "smtp_pass" in al.keys() else None
            daily_limit = al["daily_limit"] if "daily_limit" in al.keys() else 20
            # Map display name from alias local part
            local = al["alias"].split("@")[0].replace(".", " ").replace("-", " ").title()
            ok = db.add_alias(
                alias=al["alias"],
                smtp_user=al["smtp_user"],
                smtp_pass=smtp_pass,
                display_name=local,
                source="migrated",
                daily_limit=daily_limit,
            )
            # Enable all aliases by default
            if ok:
                conn = db.get_db()
                conn.execute("UPDATE smtp_aliases SET is_active=1 WHERE alias=?", (al["alias"],))
                conn.commit()
                conn.close()
                print(f"  ✅ Alias: {al['alias']} → {al['smtp_user']}")
                alias_added += 1
            else:
                print(f"  ⏩ Alias already exists: {al['alias']}")
    except Exception as e:
        aliases = []
        alias_added = 0
        print(f"  ⚠️ Could not import aliases: {e}")

    parent.close()
    print(f"\n✅ Migration complete: {acc_added} accounts, {alias_added} aliases added to Flinza.")

if __name__ == "__main__":
    migrate()
