from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db


def _store():
    conn = connect(":memory:")
    init_db(conn)
    return AuthStore(conn)


def test_user_upsert_and_lookup():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo Cat", "consumer", 100)
    assert s.get_user_by_login("octocat")["id"] == "u1"
    assert s.get_user_by_id("u1")["ghe_login"] == "octocat"
    # upsert on same login is idempotent (no duplicate / no error)
    s.upsert_user("u1", "octocat", "Octo Cat", "consumer", 200)
    assert s.get_user_by_login("octocat")["id"] == "u1"
    s.set_user_role("u1", "giver")
    assert s.get_user_by_id("u1")["role"] == "giver"


def test_list_users():
    s = _store()
    assert s.list_users() == []
    s.upsert_user("u1", "octocat", "Octo Cat", "consumer", 100)
    s.upsert_user("u2", "hubot", None, "giver", 200)
    rows = s.list_users()
    assert [(r["id"], r["ghe_login"], r["display_name"], r["role"]) for r in rows] == [
        ("u1", "octocat", "Octo Cat", "consumer"),
        ("u2", "hubot", None, "giver"),
    ]


def test_proxy_token_lifecycle():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    s.add_proxy_token("t1", "hash_abc", "u1", "wxyz", 10)
    assert s.get_active_proxy_token("hash_abc")["user_id"] == "u1"
    assert s.get_active_proxy_token("nope") is None
    assert [t["id"] for t in s.list_proxy_tokens("u1")] == ["t1"]
    assert s.revoke_proxy_token("t1", "u1", 20) is True
    assert s.get_active_proxy_token("hash_abc") is None  # revoked => inactive
    assert s.revoke_proxy_token("t1", "u1", 30) is False  # already revoked / no-op


def test_giver_pat_store_and_list():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    s.set_giver_pat("u1", b"CIPHER", b"NONCE", "ab12", 5)
    row = s.get_giver_pat("u1")
    assert row["ciphertext"] == b"CIPHER" and row["nonce"] == b"NONCE" and row["fingerprint"] == "ab12"
    # upsert replaces
    s.set_giver_pat("u1", b"CIPHER2", b"NONCE2", "cd34", 6)
    assert s.get_giver_pat("u1")["ciphertext"] == b"CIPHER2"
    assert s.list_giver_ids() == ["u1"]


def test_session_lifecycle():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    s.create_session("s1", "u1", now=100, ttl_s=50)
    assert s.get_active_session("s1", now=120)["user_id"] == "u1"
    assert s.get_active_session("s1", now=200) is None  # expired (100+50<200)
    s.create_session("s2", "u1", now=100, ttl_s=50)
    s.revoke_session("s2")
    assert s.get_active_session("s2", now=110) is None


def test_new_user_defaults_not_onboarded():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo", "consumer", 1000)
    assert s.get_user_by_id("u1")["onboarded"] == 0


def test_set_onboarded_flips_flag():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo", "consumer", 1000)
    s.set_onboarded("u1")
    assert s.get_user_by_id("u1")["onboarded"] == 1


def test_pat_health_lifecycle():
    s = _store()
    s.upsert_user("u1", "octocat", "Octo", "giver", 1)
    s.set_giver_pat("u1", b"ct", b"nonce", "abcd1234", 5)
    # fresh PAT row: no verdict yet
    assert s.get_pat_health("u1") == {"status": None, "checked_at": None, "error": None}
    assert s.get_pat_health("nobody") is None

    s.set_pat_health_ok("u1", "valid", 100)
    assert s.get_pat_health("u1") == {"status": "valid", "checked_at": 100, "error": None}

    # indefinitive check: error recorded, verdict kept
    s.set_pat_health_error("u1", "502", 200)
    assert s.get_pat_health("u1") == {"status": "valid", "checked_at": 200, "error": "502"}

    # next definitive verdict clears the error
    s.set_pat_health_ok("u1", "expired", 300)
    assert s.get_pat_health("u1") == {"status": "expired", "checked_at": 300, "error": None}
