"""Re-donation of received credit + returning it to the shared pool.

Covers the adversarially-reviewed scenario: attribution always chains to the
original PAT holder, no credit is created or destroyed, cancellations refund
the right party, and re-donation depth is capped at 1.
"""
import pytest

from ctc.accounting.engine import AccountingEngine
from ctc.accounting.errors import InsufficientCredit, InvalidConsumption
from ctc.domain.types import Bucket, Role
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db

CYC = "2026-07"


def seed(pledge: int = 0):
    conn = connect(); init_db(conn)
    s = AccountingStore(conn)
    e = AccountingEngine(s)
    e.start_cycle(CYC, "July", 0, 1_000_000)
    e.set_quota(CYC, "ada", 1000)
    if pledge:
        e.set_pledge(CYC, "ada", pledge)
    return e, s


def _receive(e, recipient: str, amount: int, needed: int | None = None):
    """Ada chips `amount` into a fresh request by `recipient`; returns (request, grant)."""
    r = e.create_request(CYC, recipient, Role.CONSUMER, needed or amount, "work", None, 0, 1_000_000)
    g = e.fund_request(r.id, "ada", amount, now=1)
    return r, g


def test_redonate_full_scenario_conservation():
    e, s = seed()
    # Ada -> Marco 250
    r0, g0 = _receive(e, "marco", 250)
    assert e.personal_remaining(CYC, "ada") == 750

    # Marco burns 90 of it
    e.record_consumption(CYC, "marco", "ada", Bucket.GRANT, 90, grant_id=g0.id, ts=2)

    # Marco re-donates 100 to Lena's request (needed 150 so it stays cancellable)
    r1 = e.create_request(CYC, "lena", Role.CONSUMER, 150, "PR", None, 0, 1_000_000)
    children = e.fund_request_from_received(r1.id, "marco", 100, now=3)
    assert [c.donor_id for c in children] == ["ada"]          # PAT attribution preserved
    assert [c.via_user_id for c in children] == ["marco"]     # human act attributed
    assert children[0].origin_grant_id == g0.id

    # Marco returns 60 to the shared pool
    e.return_received_to_pool("marco", CYC, 60, now=4)
    assert e.pool_available(CYC) == 60
    assert e.re_donatable_remaining(CYC, "marco") == 250 - 90 - 100 - 60  # == 0
    assert s.returned_to_pool_by(CYC, "marco") == 60
    assert s.re_donated_by(CYC, "marco") == 100

    # Priya draws the returned 60 onto her own request
    r2 = e.create_request(CYC, "priya", Role.CONSUMER, 60, "docs", None, 0, 1_000_000)
    drawn = e.fund_request_from_pool(r2.id, "priya", 60, now=5)
    assert [d.donor_id for d in drawn] == ["ada"]
    assert drawn[0].contribution_id is not None
    assert drawn[0].origin_grant_id == g0.id
    assert e.pool_available(CYC) == 0

    # Ada is charged exactly her original 250 — never more
    assert s.granted_out(CYC, "ada") == 250
    assert e.personal_remaining(CYC, "ada") == 750
    assert e.pledge_used(CYC, "ada") == 0  # contribution draws never touch pledges

    # Lena burns 30 of the re-donation, then cancels her request
    lena_grant = children[0]
    e.record_consumption(CYC, "lena", "ada", Bucket.GRANT, 30, grant_id=lena_grant.id, ts=6)
    e.cancel_request(r1.id, "lena", now=7)
    assert e.grant_remaining(CYC, lena_grant.id) == 0
    # The unconsumed 70 refunds to MARCO's received balance, not to Ada
    assert e.re_donatable_remaining(CYC, "marco") == 250 - 90 - 30 - 60  # == 70
    assert s.granted_out(CYC, "ada") == 250  # origin request still live
    assert s.re_donated_by(CYC, "marco") == 30  # only the burned part stays counted

    # Conservation: Marco 90 + Lena 30 + pool-drawn 60 + Marco's refunded 70 == 250
    assert 90 + 30 + 60 + e.re_donatable_remaining(CYC, "marco") == 250


def test_cancel_origin_charges_moved_credit_and_voids_undrawn_contribution():
    e, s = seed()
    # Partially-funded origin so it stays cancellable
    r0 = e.create_request(CYC, "marco", Role.CONSUMER, 250, "work", None, 0, 1_000_000)
    g0 = e.fund_request(r0.id, "ada", 200, now=1)
    e.record_consumption(CYC, "marco", "ada", Bucket.GRANT, 50, grant_id=g0.id, ts=2)

    r1 = e.create_request(CYC, "lena", Role.CONSUMER, 150, "PR", None, 0, 1_000_000)
    e.fund_request_from_received(r1.id, "marco", 80, now=3)
    e.return_received_to_pool("marco", CYC, 40, now=4)
    r2 = e.create_request(CYC, "priya", Role.CONSUMER, 20, "docs", None, 0, 1_000_000)
    e.fund_request_from_pool(r2.id, "priya", 20, now=5)
    assert e.pool_available(CYC) == 20  # 40 contributed − 20 drawn

    # Marco cancels the ORIGIN request
    e.cancel_request(r0.id, "marco", now=6)
    # Ada stays charged for what's live downstream: 50 burned + 80 re-donated
    # + 20 drawn from the returned credit. The undrawn 20 of the contribution
    # is voided (refunds Ada, leaves the pool).
    assert s.granted_out(CYC, "ada") == 50 + 80 + 20
    assert e.personal_remaining(CYC, "ada") == 1000 - 150
    assert e.pool_available(CYC) == 0
    assert e.re_donatable_remaining(CYC, "marco") == 0
    assert s.returned_to_pool_by(CYC, "marco") == 20  # drawn part only


def test_depth_cap_child_credit_cannot_be_redonated_or_returned():
    e, _ = seed()
    _, g0 = _receive(e, "marco", 100)
    r1 = e.create_request(CYC, "lena", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    e.fund_request_from_received(r1.id, "marco", 50, now=3)
    # Lena received a CHILD grant — she can spend it but not pass it on
    r2 = e.create_request(CYC, "priya", Role.CONSUMER, 50, "x", None, 0, 1_000_000)
    with pytest.raises(InsufficientCredit):
        e.fund_request_from_received(r2.id, "lena", 10, now=4)
    with pytest.raises(InsufficientCredit):
        e.return_received_to_pool("lena", CYC, 10, now=4)


def test_redonate_skips_grants_from_the_target_requester():
    e, _ = seed()
    # Marco's only received credit came from Ada; re-donating to ADA's request
    # would create donor==requester — the eligible-grant loop must skip it.
    _, g0 = _receive(e, "marco", 100)
    r_ada = e.create_request(CYC, "ada", Role.GIVER, 50, "self", None, 0, 1_000_000)
    with pytest.raises(InsufficientCredit):
        e.fund_request_from_received(r_ada.id, "marco", 50, now=3)


def test_redonate_rejects_own_request_and_respects_caps():
    e, _ = seed()
    _, g0 = _receive(e, "marco", 100)
    own = e.create_request(CYC, "marco", Role.CONSUMER, 50, "own", None, 0, 1_000_000)
    with pytest.raises(InvalidConsumption):
        e.fund_request_from_received(own.id, "marco", 10, now=3)
    # Cap to received remaining: asking for 500 places only 100
    r1 = e.create_request(CYC, "lena", Role.CONSUMER, 500, "big", None, 0, 1_000_000)
    children = e.fund_request_from_received(r1.id, "marco", 500, now=3)
    assert sum(c.amount for c in children) == 100
    assert e.re_donatable_remaining(CYC, "marco") == 0


def test_pool_draw_prefers_recycled_contributions_over_pledges():
    e, s = seed(pledge=300)
    _, g0 = _receive(e, "marco", 100)
    e.return_received_to_pool("marco", CYC, 100, now=2)
    assert e.pool_available(CYC) == 300 + 100
    r = e.create_request(CYC, "priya", Role.CONSUMER, 150, "x", None, 0, 1_000_000)
    drawn = e.fund_request_from_pool(r.id, "priya", 150, now=3)
    # First 100 from the recycled contribution, the remaining 50 from the pledge
    assert [(d.amount, d.contribution_id is not None) for d in drawn] == [(100, True), (50, False)]
    assert e.pledge_used(CYC, "ada") == 50
    assert e.pool_available(CYC) == 250


def test_donor_count_credits_the_via_user():
    e, s = seed()
    _, g0 = _receive(e, "marco", 100)
    r1 = e.create_request(CYC, "lena", Role.CONSUMER, 200, "PR", None, 0, 1_000_000)
    e.fund_request_from_received(r1.id, "marco", 50, now=3)
    assert s.request_donor_count(r1.id) == 1          # marco, not ada
    e.fund_request(r1.id, "ada", 50, now=4)           # ada also chips in directly
    assert s.request_donor_count(r1.id) == 2
    assert s.grants_count_by(CYC, "marco") == 1       # the re-donation is marco's act


def test_child_grant_consumption_routes_to_original_donor():
    e, _ = seed()
    _, g0 = _receive(e, "marco", 100)
    r1 = e.create_request(CYC, "lena", Role.CONSUMER, 100, "PR", None, 0, 1_000_000)
    child = e.fund_request_from_received(r1.id, "marco", 60, now=3)[0]
    # active_grants exposes the child with the ORIGINAL donor for PAT routing
    active = e.active_grants(CYC, "lena")
    assert [(g.id, g.donor_id) for g in active] == [(child.id, "ada")]
    # donor-mismatch guard still enforced against the chained donor
    with pytest.raises(InvalidConsumption):
        e.record_consumption(CYC, "lena", "marco", Bucket.GRANT, 10, grant_id=child.id, ts=4)
    e.record_consumption(CYC, "lena", "ada", Bucket.GRANT, 10, grant_id=child.id, ts=5)
    assert e.grant_remaining(CYC, child.id) == 50
