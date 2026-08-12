"""The phantom-pool repair tool: reporting and retracting pledges that are still
sitting on the current cycle behind a definitively dead PAT.
"""
from ctc.accounting.engine import AccountingEngine
from ctc.domain.config import NANO_PER_AIU as N
from ctc.domain.types import Bucket, Cycle, Event, GiverCycle
from ctc.store.accounting_store import AccountingStore
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db
from tools.retract_dead_pledges import find_dead_pledges

CYC = "2026-08"


def seed_incident():
    """Reproduce the incident: two givers whose PATs expired carried 2,103 + 1,000
    AIU of pledge into the new cycle; a third healthy giver pledged 500."""
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    store = AuthStore(conn)
    s.add_cycle(Cycle(CYC, "August", 0, 4_000_000_000, "active"))
    for uid, pledge, health in (("g1", 2103, "expired"), ("g2", 1000, "expired"),
                                ("g3", 500, "valid")):
        store.upsert_user(uid, uid, uid.title(), "giver", 1)
        s.upsert_giver_cycle(GiverCycle(CYC, uid, 4000 * N, pledge * N))
        conn.execute(
            "INSERT INTO giver_pats (user_id, ciphertext, nonce, fingerprint, created_at, "
            "entitlement, health_status) VALUES (?,?,?,?,?,?,?)",
            (uid, b"x", b"y", "fp", 1, 4000, health),
        )
    return AccountingEngine(s), s, store


def test_report_lists_only_dead_pat_pledges():
    e, s, store = seed_incident()
    rows = find_dead_pledges(e, store, CYC)
    assert [(r["giver_id"], r["retractable"]) for r in rows] == [
        ("g1", 2103 * N), ("g2", 1000 * N)]
    assert {r["health"] for r in rows} == {"expired"}
    # read-only
    assert s.get_giver_cycle(CYC, "g1").pledge == 2103 * N


def test_report_can_be_restricted_to_one_giver():
    e, s, store = seed_incident()
    rows = find_dead_pledges(e, store, CYC, only={"g2"})
    assert [r["giver_id"] for r in rows] == ["g2"]


def test_report_skips_fully_drawn_pledge():
    e, s, store = seed_incident()
    # every pledged nano-AIU of g2's pledge was already drawn — nothing to retract
    s.add_event(Event("e1", CYC, 5, "c1", "g2", Bucket.POOL, None, 1000 * N))
    assert [r["giver_id"] for r in find_dead_pledges(e, store, CYC)] == ["g1"]


def test_retraction_clears_the_phantom_pool():
    e, s, store = seed_incident()
    # pool_available already ignores dead-PAT givers, so it reads 500 pre-repair;
    # the retraction is what stops the rollover carrying the pledge forward again.
    assert e.pool_available(CYC) == 500 * N
    for r in find_dead_pledges(e, store, CYC):
        e.retract_pledge(CYC, r["giver_id"])
    assert s.get_giver_cycle(CYC, "g1").pledge == 0
    assert s.get_giver_cycle(CYC, "g2").pledge == 0
    assert s.get_giver_cycle(CYC, "g3").pledge == 500 * N   # healthy giver untouched
    assert find_dead_pledges(e, store, CYC) == []
