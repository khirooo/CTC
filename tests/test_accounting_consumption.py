import threading

import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.errors import InsufficientCredit, InvalidConsumption
from ctc.domain.types import Cycle, GiverCycle, Request, Grant, Role, Bucket
from ctc.domain.config import config

CYC = "2026-06"


def seed(path=":memory:"):
    conn = connect(path); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 300))
    return AccountingEngine(s), s


def test_record_own_consumption_ok_and_decrements():
    e, _ = seed()
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 100, ts=1)
    assert e.personal_remaining(CYC, "g1") == 1000 - 300 - 100  # 600


def test_own_consumption_rejected_over_personal():
    e, _ = seed()
    with pytest.raises(InsufficientCredit):
        e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 701, ts=1)  # personal is 700


def test_own_consumption_requires_self_source():
    e, _ = seed()
    with pytest.raises(InvalidConsumption):
        e.record_consumption(CYC, "c1", "g1", Bucket.OWN, 10, ts=1)


def test_pool_capped_by_pledge_and_allowance():
    e, _ = seed()
    # pledge is 300; a single 301 pool draw exceeds pledge
    with pytest.raises(InsufficientCredit):
        e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 301, ts=1)
    # over the consumer's free allowance -> raises on allowance. Set the giver's
    # pledge well above the allowance so the allowance is the binding cap.
    e.store.upsert_giver_cycle(GiverCycle(CYC, "g1", 2 * config.free_allowance, 2 * config.free_allowance))
    with pytest.raises(InsufficientCredit):
        e.record_consumption(CYC, "c1", "g1", Bucket.POOL, config.free_allowance + 1, ts=1)


def test_grant_consumption_capped_and_donor_checked():
    e, s = seed()
    s.add_request(Request("r1", CYC, "c1", Role.CONSUMER, 200, "n", None, 0, 1_000_000))
    s.add_grant(Grant("gr1", CYC, "r1", "g1", "c1", 50, 1))
    with pytest.raises(InsufficientCredit):
        e.record_consumption(CYC, "c1", "g1", Bucket.GRANT, 51, grant_id="gr1", ts=2)
    with pytest.raises(InvalidConsumption):  # wrong donor as source
        e.record_consumption(CYC, "c1", "gX", Bucket.GRANT, 10, grant_id="gr1", ts=2)
    e.record_consumption(CYC, "c1", "g1", Bucket.GRANT, 50, grant_id="gr1", ts=2)
    assert e.grant_remaining(CYC, "gr1") == 0


def test_nonpositive_credits_rejected():
    e, _ = seed()
    with pytest.raises(InvalidConsumption):
        e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 0, ts=1)


def test_concurrent_pool_draws_cannot_exceed_pledge(tmp_path):
    path = str(tmp_path / "ctc.db")
    e0, _ = seed(path)  # pledge 300; two threads each try 200 -> only one fits
    results = []

    def worker(consumer):
        eng = AccountingEngine(AccountingStore(connect(path)))
        try:
            eng.record_consumption(CYC, consumer, "g1", Bucket.POOL, 200, ts=1)
            results.append("ok")
        except InsufficientCredit:
            results.append("rejected")

    t1 = threading.Thread(target=worker, args=("c1",))
    t2 = threading.Thread(target=worker, args=("c2",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert sorted(results) == ["ok", "rejected"]
    assert e0.pledge_remaining(CYC, "g1") == 100  # exactly one 200 draw landed


def test_bypass_consumption_is_self_sourced_and_recorded():
    e, s = seed()
    e.record_consumption(CYC, "g1", "g1", Bucket.BYPASS, 250, ts=1)
    assert s.bypass_consumed(CYC, "g1") == 250


def test_bypass_consumption_requires_self_source():
    e, _ = seed()
    with pytest.raises(InvalidConsumption):
        e.record_consumption(CYC, "c1", "g1", Bucket.BYPASS, 10, ts=1)


def test_bypass_consumption_ignores_personal_headroom():
    # personal headroom is 700 (quota 1000 - pledge 300); bypass may exceed it
    # because the burn already happened at GitHub. No InsufficientCredit.
    e, _ = seed()
    e.record_consumption(CYC, "g1", "g1", Bucket.BYPASS, 5000, ts=1)


def test_personal_remaining_subtracts_bypass():
    e, _ = seed()  # quota 1000, pledge 300 -> personal headroom 700
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 100, ts=1)
    e.record_consumption(CYC, "g1", "g1", Bucket.BYPASS, 250, ts=2)
    # 1000 - 300 - 100(own) - 250(bypass) - 0(granted) = 350
    assert e.personal_remaining(CYC, "g1") == 350


def test_own_headroom_gate_accounts_for_bypass():
    e, _ = seed()  # quota 1000, pledge 300 -> personal 700
    e.record_consumption(CYC, "g1", "g1", Bucket.BYPASS, 650, ts=1)
    # personal_remaining is now 700 - 650 = 50; consuming 100 via OWN must fail
    with pytest.raises(InsufficientCredit):
        e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 100, ts=2)
