"""
supabase_db.py — SQLite-compatibility layer over Supabase Postgres.

When SUPABASE_DB_URL is set (env or .env), database.get_db() transparently
returns a connection backed by Supabase Postgres instead of the local SQLite
file. Every query the CRM runs is translated on the fly:

  ? placeholders            ->  %s
  INSERT OR IGNORE          ->  ON CONFLICT DO NOTHING
  INSERT OR REPLACE         ->  ON CONFLICT (key) DO UPDATE SET ...
  datetime('now', '-15 m')  ->  now() - interval '15 minutes'
  LIKE (case-insensitive)   ->  ILIKE
  lastrowid                 ->  INSERT ... RETURNING id
  PRAGMA / journal_mode     ->  harmless no-op

Rows are returned as dict-like objects supporting row["col"], row[0] and
.get(), so the rest of the CRM (SqliteRow duck-typing) works unchanged.
"""

import os
import re
import threading

try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    from psycopg2 import errors as pg_errors
    IntegrityError = pg_errors.UniqueViolation
except ImportError:  # pragma: no cover - surfaced with a clear error on use
    psycopg2 = None
    pg_pool = None
    pg_errors = None

    class IntegrityError(Exception):
        pass


# ═══════════════════════════════════════════════════════════════
#                    SQL TRANSLATION (SQLite → Postgres)
# ═══════════════════════════════════════════════════════════════

# Tables whose INSERTs should append RETURNING id (everything except settings,
# whose PK is a text key and has no id column).
ID_TABLES = {
    "leads", "gmail_accounts", "smtp_aliases", "emails_sent", "replies",
    "conversation_history", "followups_scheduled", "templates", "campaigns",
    "blacklist", "activity_log", "users", "oauth_tokens",
    "campaign_sequences", "email_tracking", "custom_api_endpoints",
    "dns_audit_cache", "webhooks", "ip_nodes", "smtp_profiles",
}

# INSERT OR REPLACE → real Postgres upserts, keyed on each table's unique col.
# (mirrors the UNIQUE constraints declared in the CRM schema)
_UPSERTS = {
    "settings": ("(key)", "value=EXCLUDED.value"),
    "templates": ("(name)", "type=EXCLUDED.type, subject=EXCLUDED.subject, body=EXCLUDED.body"),
    "email_tracking": ("(email_id)", "tracking_token=EXCLUDED.tracking_token, created_at=now()"),
    "dns_audit_cache": (
        "(domain)",
        "spf_record=EXCLUDED.spf_record, spf_status=EXCLUDED.spf_status, "
        "dkim_record=EXCLUDED.dkim_record, dkim_status=EXCLUDED.dkim_status, "
        "dmarc_record=EXCLUDED.dmarc_record, dmarc_status=EXCLUDED.dmarc_status, "
        "mx_record=EXCLUDED.mx_record, mx_status=EXCLUDED.mx_status, "
        "overall_score=EXCLUDED.overall_score, last_audited=now()"
    ),
}


def _translate(sql: str):
    """Translate one SQLite statement to Postgres. Returns (sql, wants_id)."""
    if not sql:
        return sql, False

    stripped = sql.lstrip()
    head = stripped[:10].upper()
    if head.startswith("PRAGMA"):
        return "SELECT 1", False  # sqlite tuning flags are meaningless here

    s = sql

    # datetime('now', '-15 minutes') -> now() - interval '15 minutes'
    s = re.sub(
        r"datetime\(\s*'now'\s*,\s*'([-+][^']*)'\s*\)",
        lambda m: (
            "now() - interval '%s'" if m.group(1).startswith("-") else "now() + interval '%s'"
        ) % m.group(1)[1:].strip(),
        s, flags=re.I,
    )
    # datetime('now') -> now()
    s = re.sub(r"datetime\(\s*'now'\s*\)", "now()", s, flags=re.I)

    # SQLite LIKE is case-insensitive by default; Postgres needs ILIKE.
    s = re.sub(r"\bLIKE\b", "ILIKE", s, flags=re.I)

    wants_id = False

    # INSERT OR REPLACE -> per-table upsert
    m = re.match(r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+([A-Za-z_]\w*)", s, re.I)
    if m:
        tbl = m.group(1).lower()
        s = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", s, count=1, flags=re.I)
        up = _UPSERTS.get(tbl)
        clause = f" ON CONFLICT {up[0]} DO UPDATE SET {up[1]}" if up else " ON CONFLICT DO NOTHING"
        s = s.rstrip().rstrip(";") + clause

    # INSERT OR IGNORE -> ON CONFLICT DO NOTHING (target-free works for all)
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", s, re.I):
        s = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", s, count=1, flags=re.I)
        s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    # RETURNING id emulation for lastrowid
    m3 = re.match(r"\s*INSERT\s+INTO\s+([A-Za-z_]\w*)", s, re.I)
    if m3 and m3.group(1).lower() in ID_TABLES and "returning" not in s.lower():
        s = s.rstrip().rstrip(";") + " RETURNING id"
        wants_id = True

    # placeholder swap (CRM queries contain no literal '?' inside strings)
    if "?" in s:
        s = s.replace("?", "%s")

    return s, wants_id


def normalize_dsn(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def is_enabled() -> bool:
    return bool(os.environ.get("SUPABASE_DB_URL", "").strip())


# ═══════════════════════════════════════════════════════════════
#                        ROW + CURSOR WRAPPERS
# ═══════════════════════════════════════════════════════════════

class Row(dict):
    """Dict with SqliteRow's extra powers: row[0] int indexing, .get(), JSON-safe."""

    __slots__ = ("_tuple",)

    def __init__(self, description, values):
        self._tuple = values
        if description and values is not None:
            for idx, col in enumerate(description):
                self[col[0]] = values[idx]

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._tuple[item]
        return super().__getitem__(item)


class Cursor:
    def __init__(self, cur):
        self._cur = cur
        self._lastrowid = None

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def fetchone(self):
        r = self._cur.fetchone()
        if r is None:
            return None
        return Row(self._cur.description, r)

    def fetchall(self):
        return [Row(self._cur.description, r) for r in self._cur.fetchall()]

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class Connection:
    """Mimics the sqlite3 connection object the CRM expects."""

    def __init__(self, conn, pool=None):
        self._conn = conn
        self._pool = pool

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        tsql, wants_id = _translate(sql)
        try:
            if params:
                cur.execute(tsql, params)
            else:
                cur.execute(tsql)
        except IntegrityError as e:
            cur.close()
            raise IntegrityError(str(e)) from e
        wrapper = Cursor(cur)
        if wants_id:
            row = cur.fetchone()
            wrapper._lastrowid = row[0] if row else None
        return wrapper

    def executescript(self, sql):  # schema comes from supabase_schema.sql instead
        raise RuntimeError("executescript is SQLite-only; use supabase_db.ensure_schema()")

    def commit(self):
        try:
            self._conn.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        if self._pool is not None:
            try:
                self._pool.putconn(self._conn)
            except Exception:
                pass
        else:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ═══════════════════════════════════════════════════════════════
#                       CONNECTION POOL / get_db
# ═══════════════════════════════════════════════════════════════

_pool = None
_pool_lock = threading.Lock()


def _dsn():
    dsn = normalize_dsn(os.environ.get("SUPABASE_DB_URL", ""))
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    return dsn


def get_db() -> Connection:
    global _pool
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required for Supabase mode: pip install psycopg2-binary"
        )
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(
                    1, 16, _dsn(),
                    application_name="flinza-crm",
                    connect_timeout=15,
                )
                host = _pool._dsn if hasattr(_pool, "_dsn") else ""
                print("[db] Supabase Postgres connected", flush=True)
    conn = _pool.getconn()
    conn.autocommit = True  # match SQLite's implicit-commit feel; commit() is a no-op
    return Connection(conn, pool=_pool)


# ═══════════════════════════════════════════════════════════════
#                          SCHEMA BOOTSTRAP
# ═══════════════════════════════════════════════════════════════

_TOLERATED = ("already exists", "duplicate")


def ensure_schema():
    """Create all CRM tables/indexes in Supabase (idempotent) + seed settings."""
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required for Supabase mode: pip install psycopg2-binary"
        )
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supabase_schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        raw = f.read()
    clean = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("--"))

    conn = psycopg2.connect(_dsn(), application_name="flinza-schema", connect_timeout=15)
    conn.autocommit = True
    created = 0
    try:
        cur = conn.cursor()
        for stmt in clean.split(";\n"):
            st = stmt.strip()
            if not st:
                continue
            try:
                cur.execute(st)
                created += 1
            except psycopg2.errors.DuplicateTable:
                pass
            except psycopg2.errors.DuplicateObject:
                pass
            except psycopg2.errors.DuplicateColumn:
                pass
            except psycopg2.errors.UniqueViolation:
                raise
        cur.close()
    finally:
        conn.close()

    # Seed the CRM's default settings rows through the normal compat path
    try:
        from database import _init_default_settings  # lazy: avoids import cycle
        c = get_db()
        _init_default_settings(c)
        c.close()
    except Exception as e:
        print(f"[db] default settings seed skipped: {e}", flush=True)

    print(f"[db] Supabase schema ready ({created} statements)", flush=True)
