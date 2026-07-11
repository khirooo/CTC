from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  starts_at INTEGER NOT NULL,
  ends_at INTEGER NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS giver_cycles (
  cycle_id TEXT NOT NULL,
  giver_id TEXT NOT NULL,
  quota INTEGER NOT NULL,
  pledge INTEGER NOT NULL,
  burn_baseline INTEGER,
  pending_drift INTEGER,
  pending_drift_at INTEGER,
  PRIMARY KEY (cycle_id, giver_id)
);
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL,
  requester_id TEXT NOT NULL,
  requester_role TEXT NOT NULL,
  amount_needed INTEGER NOT NULL,
  reason TEXT NOT NULL,
  target TEXT,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  cancelled_at INTEGER
);
CREATE TABLE IF NOT EXISTS grants (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  donor_id TEXT NOT NULL,
  recipient_id TEXT NOT NULL,
  amount INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'personal',
  origin_grant_id TEXT,
  via_user_id TEXT,
  contribution_id TEXT
);
CREATE TABLE IF NOT EXISTS pool_contributions (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL,
  contributor_id TEXT NOT NULL,
  origin_grant_id TEXT NOT NULL,
  donor_id TEXT NOT NULL,
  amount INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pool_contrib_cycle ON pool_contributions (cycle_id);
CREATE INDEX IF NOT EXISTS ix_pool_contrib_origin ON pool_contributions (origin_grant_id);
CREATE INDEX IF NOT EXISTS ix_grants_origin ON grants (origin_grant_id);
CREATE INDEX IF NOT EXISTS ix_grants_contribution ON grants (contribution_id);
CREATE TABLE IF NOT EXISTS consumption_events (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  consumer_id TEXT NOT NULL,
  source_giver_id TEXT NOT NULL,
  bucket TEXT NOT NULL,
  grant_id TEXT,
  credits INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_cycle ON consumption_events (cycle_id);
CREATE INDEX IF NOT EXISTS ix_events_consumer ON consumption_events (cycle_id, consumer_id);
CREATE INDEX IF NOT EXISTS ix_events_source ON consumption_events (cycle_id, source_giver_id);
CREATE INDEX IF NOT EXISTS ix_events_grant ON consumption_events (grant_id);
CREATE INDEX IF NOT EXISTS ix_grants_request ON grants (request_id);
CREATE INDEX IF NOT EXISTS ix_grants_donor ON grants (cycle_id, donor_id);
CREATE INDEX IF NOT EXISTS ix_grants_recipient ON grants (cycle_id, recipient_id);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  ghe_login TEXT UNIQUE NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  onboarded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS proxy_tokens (
  id TEXT PRIMARY KEY,
  token_hash TEXT UNIQUE NOT NULL,
  user_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_proxy_tokens_user ON proxy_tokens (user_id);
CREATE TABLE IF NOT EXISTS giver_pats (
  user_id TEXT PRIMARY KEY,
  ciphertext BLOB NOT NULL,
  nonce BLOB NOT NULL,
  fingerprint TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  entitlement INTEGER,
  remaining_at_submit INTEGER,
  quota_reset_date TEXT,
  health_status TEXT,
  health_checked_at INTEGER,
  health_error TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  updated_by TEXT
);
CREATE TABLE IF NOT EXISTS admin_audit (
  id             TEXT PRIMARY KEY,
  admin_id       TEXT NOT NULL,
  admin_login    TEXT NOT NULL,
  action         TEXT NOT NULL,
  target_user_id TEXT,
  ts             INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_admin_audit_ts ON admin_audit (ts);
CREATE TABLE IF NOT EXISTS cycle_reports (
  cycle_id    TEXT PRIMARY KEY,
  report_json TEXT NOT NULL,
  created_at  INTEGER NOT NULL
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    # check_same_thread=False: aiohttp test/server machinery may touch the
    # connection from a worker thread. Safe because (a) isolation_level=None
    # means no implicit transactions, and (b) the engine never awaits inside a
    # BEGIN IMMEDIATE/COMMIT block, so two contexts cannot interleave on it.
    # If that invariant ever breaks, guard engine calls with a lock.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    # synchronous=NORMAL is safe with WAL (a crash can lose the last few committed
    # transactions but never corrupts the DB) and materially cuts fsync stalls that
    # would otherwise freeze the proxy event loop under control-plane write load.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "onboarded" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN onboarded INTEGER NOT NULL DEFAULT 0")
    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(giver_pats)")}
    for col, decl in (("entitlement", "INTEGER"),
                      ("remaining_at_submit", "INTEGER"),
                      ("quota_reset_date", "TEXT"),
                      ("health_status", "TEXT"),
                      ("health_checked_at", "INTEGER"),
                      ("health_error", "TEXT")):
        if col not in pcols:
            conn.execute(f"ALTER TABLE giver_pats ADD COLUMN {col} {decl}")
    rcols = {r["name"] for r in conn.execute("PRAGMA table_info(requests)")}
    if "cancelled_at" not in rcols:
        conn.execute("ALTER TABLE requests ADD COLUMN cancelled_at INTEGER")
    gccols = {r["name"] for r in conn.execute("PRAGMA table_info(giver_cycles)")}
    for col in ("burn_baseline", "pending_drift", "pending_drift_at"):
        if col not in gccols:
            conn.execute(f"ALTER TABLE giver_cycles ADD COLUMN {col} INTEGER")
    gcols = {r["name"] for r in conn.execute("PRAGMA table_info(grants)")}
    if "source" not in gcols:
        conn.execute("ALTER TABLE grants ADD COLUMN source TEXT NOT NULL DEFAULT 'personal'")
    for col in ("origin_grant_id", "via_user_id", "contribution_id"):
        if col not in gcols:
            conn.execute(f"ALTER TABLE grants ADD COLUMN {col} TEXT")
    # Normalize legacy inclusive month-end cycles (…T23:59:59 UTC) to the exclusive
    # boundary (first second of the next month) so liveness `now < ends_at` covers
    # the whole final day (P0-1). Idempotent: once bumped, ends_at%86400==0 no longer
    # matches. Realistic cycle ends are exact UTC-midnight boundaries and unaffected.
    conn.execute("UPDATE cycles SET ends_at = ends_at + 1 WHERE ends_at % 86400 = 86399")
