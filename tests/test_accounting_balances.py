from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.domain.types import Cycle, GiverCycle, Request, Grant, Event, Role, Bucket, RequestStatus

CYC = "2026-06"


def seed():
    conn = connect(); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 300))  # quota 1000, pledge 300
    # g1 consumes 100 of their own; a pool draw of 120 hits g1; g1 donates a 200 grant
    s.add_event(Event("e1", CYC, 1, "g1", "g1", Bucket.OWN, None, 100))
    s.add_event(Event("e2", CYC, 2, "c1", "g1", Bucket.POOL, None, 120))
    s.add_request(Request("r1", CYC, "c1", Role.CONSUMER, 200, "need", None, 0, 1_000_000))
    s.add_grant(Grant("gr1", CYC, "r1", "g1", "c1", 200, 3))
    s.add_event(Event("e3", CYC, 4, "c1", "g1", Bucket.GRANT, "gr1", 50))  # 50 of the grant used
    return AccountingEngine(s)


def test_personal_remaining_subtracts_own_and_granted_out():
    e = seed()
    # 1000 - 300(pledge) - 100(own) - 200(grant committed) = 400
    assert e.personal_remaining(CYC, "g1") == 400


def test_pledge_and_pool_available():
    e = seed()
    assert e.pledge_remaining(CYC, "g1") == 300 - 120  # 180
    assert e.pool_available(CYC) == 180


def test_grant_remaining():
    e = seed()
    assert e.grant_remaining(CYC, "gr1") == 200 - 50  # 150


def test_donated_live_counts_pool_and_grant_excludes_own():
    e = seed()
    # pool 120 + grant 50 consumed off g1 by others; g1's own 100 excluded
    assert e.donated_live(CYC, "g1") == 170


def test_consumed_total_per_user():
    e = seed()
    assert e.consumed_total(CYC, "c1") == 120 + 50  # 170
    assert e.consumed_total(CYC, "g1") == 100


def test_givers_with_pool_capacity_and_active_grants():
    e = seed()
    assert e.givers_with_pool_capacity(CYC) == [("g1", 180)]
    assert [g.id for g in e.active_grants(CYC, "c1")] == ["gr1"]  # 150 remaining


def test_request_status_partial():
    e = seed()
    # funded 200 == needed 200 -> fulfilled
    assert e.request_status("r1", 5) == RequestStatus.FULFILLED


# --- dead-PAT pledges are not pool capacity ------------------------------------
# A definitively dead PAT (expired/revoked/forbidden/no entitlement) can be neither
# forwarded upstream nor reconciled, so its pledge is unbackable. Unknown health
# (no giver_pats row, NULL status, or a transient "unreachable" that kept its last
# verdict) stays eligible — same convention as AttributionService._dead.

def _pat(e, user_id, health_status=None, health_error=None):
    e.store.conn.execute(
        "INSERT INTO giver_pats (user_id, ciphertext, nonce, fingerprint, created_at, "
        "entitlement, health_status, health_error) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, b"x", b"y", "fp", 0, 100, health_status, health_error),
    )


def test_dead_pat_pledge_excluded_from_pool():
    for status in ("expired", "forbidden", "no_entitlement"):
        e = seed()
        _pat(e, "g1", status)
        assert e.dead_pat_givers() == {"g1"}, status
        # g1's own pledge_remaining is unchanged (history/profile), but the pool
        # no longer advertises it and no fill can be routed to them.
        assert e.pledge_remaining(CYC, "g1") == 180, status
        assert e.pool_available(CYC) == 0, status
        assert e.givers_with_pool_capacity(CYC) == [], status


def test_unknown_pat_health_stays_pool_eligible():
    for kwargs in ({}, {"health_status": "valid"},
                   {"health_status": "valid", "health_error": "502"}):
        e = seed()
        if kwargs:
            _pat(e, "g1", **kwargs)   # no _pat call at all == no giver_pats row
        assert e.dead_pat_givers() == set(), kwargs
        assert e.pool_available(CYC) == 180, kwargs
        assert e.givers_with_pool_capacity(CYC) == [("g1", 180)], kwargs


def test_retract_pledge_floors_at_drawn_and_is_idempotent():
    e = seed()                     # pledge 300, 120 already drawn by a POOL event
    assert e.retract_pledge(CYC, "g1") == 180
    assert e.store.get_giver_cycle(CYC, "g1").pledge == 120
    assert e.pledge_remaining(CYC, "g1") == 0
    assert e.retract_pledge(CYC, "g1") == 0            # nothing left to retract
    assert e.retract_pledge(CYC, "nobody") == 0        # no giver_cycle row


def test_retract_pledge_floor_counts_booked_pool_fills():
    # A marketplace pool fill draws pledge as a source='pool' grant, not a POOL
    # event. Flooring on pool_consumed_from alone would trip the engine's own
    # pledge-below-consumed guard.
    e = seed()
    e.store.add_grant(Grant("gr2", CYC, "r1", "g1", "c1", 60, 5, source="pool"))
    assert e.pledge_used(CYC, "g1") == 180             # 120 event + 60 pool grant
    assert e.retract_pledge(CYC, "g1") == 120
    assert e.store.get_giver_cycle(CYC, "g1").pledge == 180
