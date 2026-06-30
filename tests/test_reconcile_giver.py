import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.domain.types import Cycle, GiverCycle, Bucket
from ctc.domain.config import NANO_PER_AIU as N

CYC = "2026-06"


def seed():
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 4000 * N, 0))  # quota = entitlement ceiling
    return AccountingEngine(s), s


def test_reconcile_books_drift_as_bypass():
    e, s = seed()
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500})
    # GitHub burned 2500 AIU; CTC tracked nothing -> all 2500 is bypass.
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 2500 * N


def test_reconcile_is_idempotent():
    e, s = seed()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500})
    second = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500})
    assert second is None                       # no new delta
    assert s.bypass_consumed(CYC, "g1") == 2500 * N


def test_reconcile_books_only_positive_increment():
    e, s = seed()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500})  # 2500
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1000})  # +500
    assert s.bypass_consumed(CYC, "g1") == 3000 * N


def test_reconcile_excludes_tracked_proxied_and_shared_burn():
    e, s = seed()
    # 200 own proxied + (pool/grant from g1 omitted for brevity) already in events
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 200 * N, ts=1)
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500})
    # github_burn 2500 - tracked own 200 = 2300 bypass
    assert s.bypass_consumed(CYC, "g1") == 2300 * N


def test_reconcile_noop_on_missing_quota():
    e, s = seed()
    assert e.reconcile_giver(CYC, "g1", None) is None
    assert e.reconcile_giver(CYC, "g1", {"entitlement": None, "remaining": 5}) is None
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": None}) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_reconcile_noop_when_ctc_tracked_more_than_github():
    e, s = seed()
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 3000 * N, ts=1)
    # github says only 2500 burned (lag); never write negative, never reverse.
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_reconcile_noop_on_unlimited_sentinel():
    e, s = seed()
    assert e.reconcile_giver(CYC, "g1", {"entitlement": -1, "remaining": 0}) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_reconcile_noop_on_zero_entitlement_and_overbudget_remaining():
    e, s = seed()
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 0, "remaining": 0}) is None      # burn 0
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 5000}) is None # remaining > ent -> negative burn
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": -5}) is None   # negative remaining guarded
    assert s.bypass_consumed(CYC, "g1") == 0
