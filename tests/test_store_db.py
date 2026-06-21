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
