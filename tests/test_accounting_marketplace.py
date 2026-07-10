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


def test_request_consumed_tracks_recipient_burn():
    """request_consumed = grant-bucket credits the recipient burned from a
    request's grants; 0 before any draw, rising as the recipient consumes."""
    from ctc.domain.types import Bucket
    e, s = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    g = e.fund_request(r.id, "g1", 100, now=5)
    assert s.request_funded(r.id) == 100
    assert s.request_consumed(r.id) == 0          # funded but nothing used yet
    e.record_consumption(CYC, "c1", "g1", Bucket.GRANT, 40, grant_id=g.id, ts=6)
    assert s.request_consumed(r.id) == 40         # 40 of 100 burned
    assert e.grant_remaining(CYC, g.id) == 60

# ---------------------------------------------------------------------------
# cancel_request (soft delete)
# ---------------------------------------------------------------------------

def test_cancel_request_owner_only():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    with pytest.raises(InvalidConsumption):
        e.cancel_request(r.id, "g1", now=5)   # not the requester
    e.cancel_request(r.id, "c1", now=5)
    assert e.request_status(r.id, 5) == RequestStatus.CANCELLED


def test_cancel_request_unknown_and_idempotent():
    e, _ = seed()
    with pytest.raises(InvalidConsumption):
        e.cancel_request("nope", "c1", now=5)
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.cancel_request(r.id, "c1", now=5)
    e.cancel_request(r.id, "c1", now=6)   # second cancel is a no-op
    assert e.request_status(r.id, 6) == RequestStatus.CANCELLED


def test_cancel_fulfilled_request_rejected():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.fund_request(r.id, "g1", 100, now=5)
    with pytest.raises(RequestClosed):
        e.cancel_request(r.id, "c1", now=6)


def test_cancel_expired_request_allowed():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 10)
    e.cancel_request(r.id, "c1", now=20)   # already expired — harmless cleanup
    assert e.request_status(r.id, 20) == RequestStatus.CANCELLED


def test_cancelled_request_hidden_from_list():
    e, s = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    assert [x.id for x in s.list_requests(CYC)] == [r.id]
    e.cancel_request(r.id, "c1", now=5)
    assert s.list_requests(CYC) == []
    assert s.get_request(r.id) is not None   # row kept for history


def test_cancel_refunds_unconsumed_grant_to_donor():
    from ctc.domain.types import Bucket
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 200, "PR", None, 0, 1_000_000)
    g = e.fund_request(r.id, "g1", 100, now=5)   # partial — still cancellable
    e.record_consumption(CYC, "c1", "g1", Bucket.GRANT, 30, grant_id=g.id, ts=6)
    assert e.personal_remaining(CYC, "g1") == 700 - 100
    e.cancel_request(r.id, "c1", now=7)
    # only the 30 already burned stays charged; the 70 remainder returns
    assert e.personal_remaining(CYC, "g1") == 700 - 30
    # and the recipient can no longer draw from the cancelled request's grant
    assert e.grant_remaining(CYC, g.id) == 0
    assert e.active_grants(CYC, "c1") == []


def test_funding_cancelled_request_rejected():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.cancel_request(r.id, "c1", now=5)
    with pytest.raises(RequestClosed):
        e.fund_request(r.id, "g1", 50, now=6)
    with pytest.raises(RequestClosed):
        e.fund_request_from_pool(r.id, "c1", 50, now=6)


# ---------------------------------------------------------------------------
# fund_request_from_pool (marketplace pool fills)
# ---------------------------------------------------------------------------

def test_pool_fund_own_request_allowed_and_charges_pledge():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    grants = e.fund_request_from_pool(r.id, "c1", 80, now=5)   # requester fills own request
    assert [(g.donor_id, g.amount, g.source) for g in grants] == [("g1", 80, "pool")]
    # the fill comes out of the pledge, never the giver's personal credit
    assert e.pledge_remaining(CYC, "g1") == 300 - 80
    assert e.pool_available(CYC) == 220
    assert e.personal_remaining(CYC, "g1") == 700


def test_pool_fund_splits_across_givers_largest_pledge_first():
    e, _ = seed()
    e.set_quota(CYC, "g2", 500)
    e.set_pledge(CYC, "g2", 400)   # g2 has the larger pledge
    r = e.create_request(CYC, "c1", Role.CONSUMER, 600, "PR", None, 0, 1_000_000)
    grants = e.fund_request_from_pool(r.id, "c1", 600, now=5)
    assert [(g.donor_id, g.amount) for g in grants] == [("g2", 400), ("g1", 200)]
    assert e.request_status(r.id, 5) == RequestStatus.FULFILLED  # 600 of 600


def test_pool_fund_caps_to_pool_and_need():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 1000, "PR", None, 0, 1_000_000)
    grants = e.fund_request_from_pool(r.id, "c1", 5000, now=5)
    assert sum(g.amount for g in grants) == 300   # capped by pool_available
    assert e.pool_available(CYC) == 0
    with pytest.raises(InsufficientCredit):
        e.fund_request_from_pool(r.id, "c1", 10, now=6)   # pool dry


def test_pool_fund_fulfills_request():
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.fund_request(r.id, "g1", 40, now=5)          # personal chip-in
    e.fund_request_from_pool(r.id, "c1", 60, now=6)  # pool tops it up
    assert e.request_status(r.id, 6) == RequestStatus.FULFILLED
    with pytest.raises(RequestClosed):
        e.fund_request_from_pool(r.id, "c1", 10, now=7)


def test_pool_fund_grant_consumption_and_pledge_floor():
    from ctc.domain.types import Bucket
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    g = e.fund_request_from_pool(r.id, "c1", 100, now=5)[0]
    # consumption of a pool-fill grant flows through the normal GRANT machinery
    e.record_consumption(CYC, "c1", "g1", Bucket.GRANT, 40, grant_id=g.id, ts=6)
    assert e.grant_remaining(CYC, g.id) == 60
    # the pledge cannot be lowered below what pool fills already committed
    with pytest.raises(InvalidPledge):
        e.set_pledge(CYC, "g1", 99)
    e.set_pledge(CYC, "g1", 100)   # exactly the committed amount is fine


def test_cancel_returns_unconsumed_pool_fill_to_pool():
    from ctc.domain.types import Bucket
    e, _ = seed()
    r = e.create_request(CYC, "c1", Role.CONSUMER, 200, "PR", None, 0, 1_000_000)
    g = e.fund_request_from_pool(r.id, "c1", 100, now=5)[0]   # partial — still cancellable
    e.record_consumption(CYC, "c1", "g1", Bucket.GRANT, 30, grant_id=g.id, ts=6)
    assert e.pool_available(CYC) == 200
    e.cancel_request(r.id, "c1", now=7)
    # the unburned 70 returns to the pool; the 30 stays charged to the pledge
    assert e.pool_available(CYC) == 300 - 30


def test_pool_fill_does_not_change_giver_left_math():
    # Explicit guard for the profile equation left = E − used − pledged − donated:
    # a pool fill moves credit WITHIN the pledge, so 'left' must not move.
    e, _ = seed()
    r = e.create_request(CYC, "c2", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.fund_request_from_pool(r.id, "c2", 40, now=5)
    g = e.fund_request(r.id, "g1", 30, now=6)   # personal chip-in on top
    # donated (personal) counts only the personal grant
    assert e.store.granted_out(CYC, "g1") == 30
    assert e.store.pool_granted_out(CYC, "g1") == 40
    assert e.personal_remaining(CYC, "g1") == 700 - 30
