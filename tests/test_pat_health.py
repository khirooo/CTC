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


# --- sweep-driven reconcile (engine wired) -------------------------------------

from ctc.accounting.engine import AccountingEngine
from ctc.domain.config import NANO_PER_AIU as N
from ctc.domain.types import Bucket, Event, GiverCycle
from ctc.store.accounting_store import AccountingStore


def _body(ent, rem):
    return {"quota_snapshots": {"premium_interactions":
            {"entitlement": ent, "remaining": rem}},
            "quota_reset_date": "2026-08-01"}


def _engine_setup(responses, *, ends_at=10_000_000_000):
    """Like _setup but with a real AccountingEngine sharing the same conn, plus an
    injectable `sleep` recorder that ADVANCES the fake clock by whatever it is
    asked to wait (so the confirm phase's second observation lands >=90s later)."""
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    reg = AuthRegistry(store, derive_key("k"))
    acct = AccountingStore(conn)
    engine = AccountingEngine(acct)
    engine.start_cycle("c1", "June", 0, ends_at)

    calls = []

    async def fetch_raw(pat):
        calls.append(pat)
        r = responses[pat]
        if isinstance(r, Exception):
            raise r
        return r

    t = [1000]
    sleeps = []

    async def sleep(s):
        sleeps.append(s)
        t[0] += s

    def make(engine_arg=engine):
        return PatHealthChecker(store, reg.pat_for, fetch_raw, now=lambda: t[0],
                                engine=engine_arg, confirm_delay_s=95, sleep=sleep)

    return dict(store=store, reg=reg, acct=acct, engine=engine, calls=calls,
                t=t, sleeps=sleeps, make=make)


def _seed_giver(env, uid, pat, *, baseline=0, ent=4000, quota_aiu=4000):
    store, reg, acct = env["store"], env["reg"], env["acct"]
    store.upsert_user(uid, uid, uid.title(), "giver", 1)
    reg.store_pat(uid, pat, 1)
    # entitlement column on giver_pats is what _open_month_cycle seeds from.
    store.set_giver_quota_snapshot(uid, ent, 0, None, 1)
    acct.upsert_giver_cycle(GiverCycle("c1", uid, quota_aiu * N, 0))
    if baseline is not None:
        acct.set_burn_baseline("c1", uid, baseline)


def _book_own(acct, uid, credits, ts=500):
    acct.add_event(Event("ev-" + uid + "-" + str(ts), "c1", ts, uid, uid,
                         Bucket.OWN, None, credits))


@pytest.mark.asyncio
async def test_sweep_without_engine_unchanged():
    env = _engine_setup({"p1": (200, _body(4000, 1500))})
    _seed_giver(env, "g1", "p1")
    checker = env["make"](engine_arg=None)
    await checker.run_once()
    # No engine → giver_cycles reconcile columns untouched, nothing booked.
    gc = env["acct"].get_giver_cycle("c1", "g1")
    assert gc.pending_drift is None and gc.burn_baseline == 0
    assert env["acct"].bypass_consumed("c1", "g1") == 0
    assert env["sleeps"] == []
    # But the display-only work still happened.
    assert env["store"].get_pat_health("g1")["status"] == "valid"


@pytest.mark.asyncio
async def test_sweep_valid_pat_records_pending_drift():
    env = _engine_setup({"p1": (200, _body(4000, 1500))})   # burn 2500 AIU
    _seed_giver(env, "g1", "p1")
    checker = env["make"]()
    await checker.check_one("g1", cycle_id="c1")             # phase-1 observation
    gc = env["acct"].get_giver_cycle("c1", "g1")
    assert gc.pending_drift == 2500 * N
    assert env["acct"].bypass_consumed("c1", "g1") == 0      # not booked yet


@pytest.mark.asyncio
async def test_sweep_confirm_phase_books_bypass():
    env = _engine_setup({"p1": (200, _body(4000, 1500))})
    _seed_giver(env, "g1", "p1")
    await env["make"]().run_once()
    # Phase 1 pending, slept once by confirm_delay_s, phase 2 confirmed.
    assert env["sleeps"] == [95]
    assert env["acct"].bypass_consumed("c1", "g1") == 2500 * N
    gc = env["acct"].get_giver_cycle("c1", "g1")
    assert gc.pending_drift is None


@pytest.mark.asyncio
async def test_sweep_confirm_skipped_when_no_pending():
    env = _engine_setup({"p1": (200, _body(4000, 4000))})    # zero burn → no drift
    _seed_giver(env, "g1", "p1")
    await env["make"]().run_once()
    assert env["sleeps"] == []                               # never slept
    assert env["acct"].bypass_consumed("c1", "g1") == 0


@pytest.mark.asyncio
async def test_sweep_confirm_no_book_when_tracked_catches_up():
    env = _engine_setup({"p1": (200, _body(4000, 1500))})
    _seed_giver(env, "g1", "p1")
    # During the confirm sleep, CTC's own tracked burn catches up to GitHub, so
    # the second observation sees drift <= 0 and books nothing.
    async def sleep_and_track(s):
        env["sleeps"].append(s)
        env["t"][0] += s
        _book_own(env["acct"], "g1", 2500 * N, ts=env["t"][0])
    checker = env["make"]()
    checker.sleep = sleep_and_track
    await checker.run_once()
    assert env["acct"].bypass_consumed("c1", "g1") == 0
    gc = env["acct"].get_giver_cycle("c1", "g1")
    assert gc.pending_drift is None                          # pending cleared


@pytest.mark.asyncio
async def test_sweep_skips_reconcile_for_non_valid_verdicts():
    env = _engine_setup({"p1": (401, None), "p2": (403, None),
                         "p3": (200, BODY_NO_ENT), "p4": ConnectionError("dns")})
    for uid, pat in [("g1", "p1"), ("g2", "p2"), ("g3", "p3"), ("g4", "p4")]:
        _seed_giver(env, uid, pat)
    await env["make"]().run_once()
    for uid in ["g1", "g2", "g3", "g4"]:
        gc = env["acct"].get_giver_cycle("c1", uid)
        assert gc.pending_drift is None and gc.burn_baseline == 0
        assert env["acct"].bypass_consumed("c1", uid) == 0
    assert env["sleeps"] == []


@pytest.mark.asyncio
async def test_sweep_reconcile_failure_still_persists_health():
    env = _engine_setup({"p1": (200, _body(4000, 1500))})
    _seed_giver(env, "g1", "p1")

    def boom(*a, **k):
        raise RuntimeError("engine down")
    env["engine"].reconcile_giver = boom
    checker = env["make"]()
    # Must not raise, and the health verdict is still persisted.
    assert await checker.check_one("g1", cycle_id="c1") == "valid"
    assert env["store"].get_pat_health("g1") == {"status": "valid", "checked_at": 1000, "error": None}


@pytest.mark.asyncio
async def test_sweep_rolls_cycle_over():
    # Active cycle already ended (ends_at in the past): run_once must roll over.
    env = _engine_setup({"p1": (200, _body(4000, 4000))}, ends_at=500)
    _seed_giver(env, "g1", "p1")
    await env["make"]().run_once()
    cur = env["engine"].current_cycle()
    assert cur.id == "cycle-1970-01" and cur.status == "active"


@pytest.mark.asyncio
async def test_sweep_confirms_pending_seeded_by_other_caller():
    # A profile/proxy observation recorded pending 30s before the sweep starts.
    env = _engine_setup({"p1": (200, _body(4000, 1500))})
    _seed_giver(env, "g1", "p1")
    env["acct"].set_pending_drift("c1", "g1", 2500 * N, 970)   # now=1000 → age 30s
    await env["make"]().run_once()
    # Phase 1 age 30s (< CONFIRM_MIN_S) keeps it pending; phase 2 (age 125s) books.
    assert env["sleeps"] == [95]
    assert env["acct"].bypass_consumed("c1", "g1") == 2500 * N
    assert env["acct"].get_giver_cycle("c1", "g1").pending_drift is None
