from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore


def _store():
    conn = connect(":memory:"); init_db(conn)
    return AuthStore(conn)


def test_add_and_get():
    s = _store()
    s.add_magic_link("id1", "a@b.com", expires_at=100, created_at=10)
    row = s.get_magic_link("id1")
    assert row["email"] == "a@b.com" and row["consumed_at"] is None


def test_consume_is_single_use():
    s = _store()
    s.add_magic_link("id1", "a@b.com", expires_at=100, created_at=10)
    assert s.consume_magic_link("id1", now=20) is True
    assert s.consume_magic_link("id1", now=21) is False
    assert s.get_magic_link("id1")["consumed_at"] == 20
