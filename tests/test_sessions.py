from ctc.auth.sessions import SessionService
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db


def _svc(ttl=100):
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    store.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    return SessionService(store, secret="sekret", ttl_s=ttl), store


def test_create_then_resolve():
    svc, _ = _svc()
    cookie = svc.create("u1", now=1000)
    assert "." in cookie
    assert svc.user_id_for(cookie, now=1050) == "u1"


def test_expired_session_returns_none():
    svc, _ = _svc(ttl=10)
    cookie = svc.create("u1", now=1000)
    assert svc.user_id_for(cookie, now=2000) is None


def test_tampered_cookie_rejected():
    svc, _ = _svc()
    cookie = svc.create("u1", now=1000)
    sid, _, _sig = cookie.partition(".")
    assert svc.user_id_for(sid + ".deadbeef", now=1050) is None


def test_revoke():
    svc, _ = _svc()
    cookie = svc.create("u1", now=1000)
    svc.revoke(cookie)
    assert svc.user_id_for(cookie, now=1050) is None
