import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.errors import RequestClosed, InvalidPledge, InsufficientCredit, InvalidConsumption
from ctc.domain.types import Cycle, GiverCycle, Role, RequestStatus

CYC = "2026-06"


def seed():
    conn = connect(); init_db(conn)
    s = AccountingStore(conn)
    e = AccountingEngine(s)
    e.start_cycle(CYC, "June", 0, 1_000_000)
    e.set_quota(CYC, "g1", 1000)
    e.set_pledge(CYC, "g1", 300)  # personal = 700
    return e, s


def test_start_and_current_cycle():
    e, _ = seed()
    assert e.current_cycle().id == CYC


def test_set_pledge_rejects_above_quota():
    e, _ = seed()
    with pytest.raises(InvalidPledge):
        e.set_pledge(CYC, "g1", 1001)


def test_set_quota_clamps_existing_pledge():
    e, _ = seed()
    e.set_quota(CYC, "g1", 200)  # pledge was 300 -> clamped to 200
    assert e.pledge_remaining(CYC, "g1") == 200


def test_fund_request_caps_to_need_and_donor_and_autofulfills():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    g = e.fund_request(r.id, "g1", 1000, now=5)   # capped to need 100 (and donor 700)
    assert g.amount == 100
    assert e.request_status(r.id, 5) == RequestStatus.FULFILLED
    # donor personal reduced by the committed grant
    assert e.personal_remaining(CYC, "g1") == 700 - 100


def test_fund_request_rejects_self_funding():
    e, _ = seed()
    r = e.create_request(CYC, "g1", Role.GIVER, 100, "PR", None, 0, 1_000_000)  # g1's own request
    with pytest.raises(InvalidConsumption):
        e.fund_request(r.id, "g1", 50, now=5)


def test_fund_request_partial_then_close():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.fund_request(r.id, "g1", 60, now=5)
    assert e.request_status(r.id, 5) == RequestStatus.PARTIALLY_FUNDED
    e.fund_request(r.id, "g1", 60, now=6)  # capped to remaining 40
    assert e.request_status(r.id, 6) == RequestStatus.FULFILLED
    with pytest.raises(RequestClosed):
        e.fund_request(r.id, "g1", 10, now=7)


def test_fund_request_capped_by_donor_personal():
    e, _ = seed()
    e.set_pledge(CYC, "g1", 950)  # personal = 50
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    g = e.fund_request(r.id, "g1", 100, now=5)
    assert g.amount == 50  # capped by donor personal


def test_fund_expired_request_rejected():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 10)
    with pytest.raises(RequestClosed):
        e.fund_request(r.id, "g1", 50, now=20)  # now > expires_at
