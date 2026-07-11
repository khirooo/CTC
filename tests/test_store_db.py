from ctc.store.db import connect, init_db


def test_init_db_creates_all_tables():
    conn = connect()
    init_db(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert {"cycles", "giver_cycles", "requests", "grants", "consumption_events"} <= names


def test_init_db_is_idempotent():
    conn = connect()
    init_db(conn)
    init_db(conn)  # must not raise


def test_wal_enabled_for_file_db(tmp_path):
    conn = connect(str(tmp_path / "ctc.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_autocommit_and_manual_transaction(tmp_path):
    conn = connect(str(tmp_path / "ctc.db"))
    init_db(conn)
    # isolation_level=None means we control transactions explicitly
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO cycles (id,label,starts_at,ends_at,status) VALUES ('c','L',0,1,'active')"
    )
    conn.execute("COMMIT")
    assert conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 1


def test_synchronous_normal_for_file_db(tmp_path):
    conn = connect(str(tmp_path / "ctc.db"))
    # PRAGMA synchronous returns an int: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA.
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_init_db_migrates_pre_reconcile_giver_cycles(tmp_path):
    # A DB created before the reconcile columns existed must gain them on init_db.
    conn = connect(str(tmp_path / "old.db"))
    conn.execute(
        "CREATE TABLE giver_cycles (cycle_id TEXT NOT NULL, giver_id TEXT NOT NULL, "
        "quota INTEGER NOT NULL, pledge INTEGER NOT NULL, PRIMARY KEY (cycle_id, giver_id))"
    )
    conn.execute("INSERT INTO giver_cycles (cycle_id, giver_id, quota, pledge) VALUES ('c','g',10,0)")
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(giver_cycles)")}
    assert {"burn_baseline", "pending_drift", "pending_drift_at"} <= cols
    r = conn.execute(
        "SELECT burn_baseline, pending_drift, pending_drift_at FROM giver_cycles "
        "WHERE cycle_id='c' AND giver_id='g'"
    ).fetchone()
    assert r["burn_baseline"] is None and r["pending_drift"] is None and r["pending_drift_at"] is None


def test_init_db_migrates_pre_health_giver_pats(tmp_path):
    # A DB created before the health columns existed must gain them on init_db.
    conn = connect(str(tmp_path / "old.db"))
    conn.execute(
        "CREATE TABLE giver_pats (user_id TEXT PRIMARY KEY, ciphertext BLOB NOT NULL, "
        "nonce BLOB NOT NULL, fingerprint TEXT NOT NULL, created_at INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO giver_pats VALUES ('u1', x'00', x'00', 'fp', 1)")
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(giver_pats)")}
    assert {"health_status", "health_checked_at", "health_error"} <= cols
    r = conn.execute("SELECT health_status, health_error FROM giver_pats WHERE user_id='u1'").fetchone()
    assert r["health_status"] is None and r["health_error"] is None
