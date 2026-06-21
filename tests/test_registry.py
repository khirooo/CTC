from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry, hash_token, mint_proxy_token
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db


def _reg():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    return AuthRegistry(store, derive_key("k")), store


def test_mint_token_is_pat_shaped_and_unique():
    a, b = mint_proxy_token(), mint_proxy_token()
    assert a.startswith("github_pat_") and len(a) > 50 and a != b


def test_issue_then_resolve_to_user():
    reg, store = _reg()
    store.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    tid, token, fp = reg.issue_proxy_token("u1", now=10)
    ident = reg.resolve(token)
    assert ident.user_id == "u1" and ident.is_giver is False
    assert fp == token[-4:]
    # the raw token is never stored — only its hash
    assert store.get_active_proxy_token(hash_token(token))["user_id"] == "u1"
    assert reg.resolve("github_pat_unknown") is None


def test_giver_role_reflected_in_identity():
    reg, store = _reg()
    store.upsert_user("u1", "octocat", "Octo", "giver", 1)
    _, token, _ = reg.issue_proxy_token("u1", now=10)
    assert reg.resolve(token).is_giver is True


def test_store_and_decrypt_pat_round_trip():
    reg, store = _reg()
    store.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    reg.store_pat("u1", "github_pat_REALSECRET", now=5)
    assert reg.pat_for("u1") == "github_pat_REALSECRET"
    assert reg.list_givers() == ["u1"]
    assert reg.pat_for("nobody") is None
