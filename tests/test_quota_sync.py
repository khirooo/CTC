"""sync_quota_ceiling: self-heal a giver's quota ceiling when GitHub reports a
higher live entitlement mid-cycle (e.g. an exceptional grant), without
requiring a PAT resubmit. Never lowers quota; never raises for
unknown/unlimited(-1)/corrupt live data or a missing giver_cycle row."""
from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.domain.types import Cycle, GiverCycle
from ctc.domain.config import NANO_PER_AIU as N

CYC = "2026-06"


def seed(quota_aiu=4000, pledge_aiu=0):
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", quota_aiu * N, pledge_aiu * N))
    return AccountingEngine(s), s


def test_higher_live_entitlement_raises_quota():
    e, s = seed(quota_aiu=4000)
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": 5000, "remaining": 4800})
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.quota == 5000 * N


def test_higher_live_entitlement_never_lowers_pledge_or_consumed():
    e, s = seed(quota_aiu=4000, pledge_aiu=1000)
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": 5000, "remaining": 4800})
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.quota == 5000 * N
    assert gc.pledge == 1000 * N  # unaffected — set_quota only clamps pledge DOWN if quota shrinks


def test_lower_or_equal_live_entitlement_is_noop():
    e, s = seed(quota_aiu=4000)
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": 4000, "remaining": 1500})
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": 3000, "remaining": 1500})
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.quota == 4000 * N  # never lowered


def test_none_live_is_noop():
    e, s = seed(quota_aiu=4000)
    e.sync_quota_ceiling(CYC, "g1", None)
    assert s.get_giver_cycle(CYC, "g1").quota == 4000 * N


def test_unknown_entitlement_is_noop():
    e, s = seed(quota_aiu=4000)
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": None, "remaining": 1500})
    assert s.get_giver_cycle(CYC, "g1").quota == 4000 * N


def test_unlimited_entitlement_is_noop():
    e, s = seed(quota_aiu=4000)
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": -1, "remaining": -1})
    assert s.get_giver_cycle(CYC, "g1").quota == 4000 * N


def test_missing_giver_cycle_is_noop_and_does_not_crash():
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    e = AccountingEngine(s)
    e.sync_quota_ceiling(CYC, "unknown-giver", {"entitlement": 5000, "remaining": 4800})
    assert s.get_giver_cycle(CYC, "unknown-giver") is None


def test_raising_quota_never_trips_consumed_floor_guard():
    # Even when pledge usage is close to the OLD quota, raising is always safe
    # (set_quota only rejects lowering quota below already-consumed pledge).
    e, s = seed(quota_aiu=4000, pledge_aiu=4000)
    e.sync_quota_ceiling(CYC, "g1", {"entitlement": 4500, "remaining": 4300})
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.quota == 4500 * N
    assert gc.pledge == 4000 * N
