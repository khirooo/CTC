import pytest
from ctc.auth.crypto import derive_key
from ctc.auth.pat_health import PatHealthChecker, classify, display_status
from ctc.auth.registry import AuthRegistry
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db


BODY_OK = {"quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 1500}},
           "quota_reset_date": "2026-08-01"}
BODY_NO_ENT = {"quota_snapshots": {"premium_interactions": {}}}


# --- classify: response -> verdict --------------------------------------------

@pytest.mark.parametrize("status,body,expected", [
    (200, BODY_OK, "valid"),
    (200, BODY_NO_ENT, "no_entitlement"),
    (200, {}, "no_entitlement"),
    (200, None, "no_entitlement"),
    (401, None, "expired"),
    (403, None, "forbidden"),
    (500, None, None),     # indefinitive: keep previous verdict
    (502, None, None),     # GHE outage 502s everything — must not flip a PAT
    (429, None, None),
])
def test_classify(status, body, expected):
    assert classify(status, body) == expected


# --- display_status: stored row -> UI string -----------------------------------

def test_display_status():
    assert display_status(None) is None
    assert display_status({"status": None, "checked_at": None, "error": None}) is None
    assert display_status({"status": "valid", "checked_at": 5, "error": None}) == "valid"
    assert display_status({"status": "valid", "checked_at": 5, "error": "boom"}) == "unreachable"
    assert display_status({"status": None, "checked_at": 5, "error": "boom"}) == "unreachable"


# --- checker -------------------------------------------------------------------

def _setup(responses):
    """responses: dict pat -> (status, body) or Exception to raise."""
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    reg = AuthRegistry(store, derive_key("k"))
    calls = []

    async def fetch_raw(pat):
        calls.append(pat)
        r = responses[pat]
        if isinstance(r, Exception):
            raise r
        return r

    t = [1000]
    checker = PatHealthChecker(store, reg.pat_for, fetch_raw, now=lambda: t[0])
    return store, reg, checker, calls, t


def _add_giver(store, reg, uid, pat):
    store.upsert_user(uid, uid, uid.title(), "giver", 1)
    reg.store_pat(uid, pat, 1)


@pytest.mark.asyncio
async def test_check_one_persists_each_definitive_state():
    for status, body, expected in [(200, BODY_OK, "valid"), (401, None, "expired"),
                                   (403, None, "forbidden"), (200, BODY_NO_ENT, "no_entitlement")]:
        store, reg, checker, _, t = _setup({"p1": (status, body)})
        _add_giver(store, reg, "g1", "p1")
        assert await checker.check_one("g1") == expected
        h = store.get_pat_health("g1")
        assert h == {"status": expected, "checked_at": 1000, "error": None}


@pytest.mark.asyncio
async def test_valid_check_refreshes_quota_snapshot():
    store, reg, checker, _, _ = _setup({"p1": (200, BODY_OK)})
    _add_giver(store, reg, "g1", "p1")
    await checker.check_one("g1")
    snap = store.get_giver_quota_snapshot("g1")
    assert snap == {"entitlement": 4000, "remaining_at_submit": 1500,
                    "quota_reset_date": "2026-08-01"}


@pytest.mark.asyncio
async def test_indefinitive_keeps_prior_verdict_and_sets_error():
    store, reg, checker, _, t = _setup({"p1": (200, BODY_OK)})
    _add_giver(store, reg, "g1", "p1")
    await checker.check_one("g1")                      # valid at t=1000

    checker.fetch_raw = _raiser(ConnectionError("dns down"))
    t[0] = 2000
    assert await checker.check_one("g1") is None       # network error
    h = store.get_pat_health("g1")
    assert h == {"status": "valid", "checked_at": 2000, "error": "dns down"}
    assert display_status(h) == "unreachable"

    checker.fetch_raw = _responder(502, None)
    t[0] = 3000
    assert await checker.check_one("g1") is None       # GHE outage
    h = store.get_pat_health("g1")
    assert h["status"] == "valid"
    assert h["error"] == "/copilot_internal/user -> 502"


@pytest.mark.asyncio
async def test_definitive_result_clears_error():
    store, reg, checker, _, t = _setup({"p1": (200, BODY_OK)})
    _add_giver(store, reg, "g1", "p1")
    checker.fetch_raw = _raiser(ConnectionError("boom"))
    await checker.check_one("g1")
    assert store.get_pat_health("g1")["error"] == "boom"

    checker.fetch_raw = _responder(401, None)
    t[0] = 2000
    await checker.check_one("g1")
    assert store.get_pat_health("g1") == {"status": "expired", "checked_at": 2000, "error": None}


@pytest.mark.asyncio
async def test_run_once_survives_a_raising_giver_and_checks_the_rest():
    store, reg, checker, calls, _ = _setup({"p1": (200, BODY_OK), "p2": (401, None)})
    _add_giver(store, reg, "g1", "p1")
    _add_giver(store, reg, "g2", "p2")
    # A store-level failure for g1 must not skip g2.
    real = checker.store.set_pat_health_ok
    def boom_once(user_id, status, now):
        if user_id == "g1":
            raise RuntimeError("db hiccup")
        return real(user_id, status, now)
    checker.store.set_pat_health_ok = boom_once
    await checker.run_once()
    assert store.get_pat_health("g2")["status"] == "expired"
    assert set(calls) == {"p1", "p2"}


@pytest.mark.asyncio
async def test_check_one_skips_deleted_pat():
    store, reg, checker, calls, _ = _setup({})
    assert await checker.check_one("ghost") is None
    assert calls == []


def _raiser(exc):
    async def f(pat):
        raise exc
    return f


def _responder(status, body):
    async def f(pat):
        return status, body
    return f
