# tests/test_auth_store_admin.py
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore


def _store():
    conn = connect(":memory:"); init_db(conn)
    return AuthStore(conn)


def test_list_users_admin_includes_fingerprint_and_token_count():
    s = _store()
    s.upsert_user("u1", "octo", "Octo", "giver", 1)
    s.upsert_user("u2", "bob", "Bob", "consumer", 2)
    s.set_giver_pat("u1", b"ct", b"nonce", "abcd1234", 5)
    s.add_proxy_token("t1", "h1", "u1", "wxyz", 6)
    s.add_proxy_token("t2", "h2", "u1", "qrst", 7)
    rows = {r["id"]: r for r in s.list_users_admin()}
    assert rows["u1"]["pat_fingerprint"] == "abcd1234"
    assert rows["u1"]["token_count"] == 2
    assert rows["u2"]["pat_fingerprint"] is None
    assert rows["u2"]["token_count"] == 0
    assert rows["u1"]["onboarded"] == 0


def test_add_and_list_admin_audit():
    s = _store()
    s.add_admin_audit("a1", "admin_uid", "octo", "reveal_pat", "u1", 1000)
    rows = s.list_admin_audit()
    assert len(rows) == 1
    assert rows[0]["action"] == "reveal_pat"
    assert rows[0]["admin_login"] == "octo"
    assert rows[0]["target_user_id"] == "u1"


def test_list_users_admin_includes_pat_health():
    s = _store()
    s.upsert_user("u1", "octo", "Octo", "giver", 1)
    s.upsert_user("u2", "bob", "Bob", "consumer", 2)
    s.set_giver_pat("u1", b"ct", b"nonce", "abcd1234", 5)
    s.set_pat_health_ok("u1", "expired", 100)
    s.set_pat_health_error("u1", "boom", 150)
    rows = {r["id"]: r for r in s.list_users_admin()}
    assert rows["u1"]["pat_health_status"] == "expired"
    assert rows["u1"]["pat_health_checked_at"] == 150
    assert rows["u1"]["pat_health_error"] == "boom"
    assert rows["u2"]["pat_health_status"] is None
