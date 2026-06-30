"""
Tests for Task 7: overshoot spill across grants.

Scenario: consumer "kef" has two active grants — A from donor "yas" (25 AIU
remaining) and B from donor "zed" (40 AIU remaining).  A single 50-AIU debit
on source=grant A should drain A to 0, spill 25 into B (B left 15), and drive
NEITHER grant below zero.

Also covers regression: OWN-source debit still uses a single record (no spill
loop for OWN/POOL), and a debit that exceeds all grants records the remainder
with overshoot on the original source bucket.
"""
import pytest

from ctc.accounting.engine import AccountingEngine
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.domain.types import Bucket, Role
from ctc.routing.attribution import AttributionService, Source
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


class _PoolEnabledConfig:
    shared_pool_enabled = True
    free_allowance = 300 * 1_000_000_000
    default_pledge_pct = 0
    participants_mode = "givers_and_consumers"


@pytest.fixture
def spill_ctx():
    """
    Participants:
        yas  — giver, quota 500, personal_remaining 500 (no pledge)
        zed  — giver, quota 500, personal_remaining 500 (no pledge)
        kef  — non-PAT consumer with two active grants: A (yas→kef, 25) and B (zed→kef, 40)

    Grant A is the FIRST active grant for kef (created first), so select_source
    picks it as the source.
    """
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_PoolEnabledConfig())
    eng.start_cycle("c1", "June", 0, 10_000_000)

    # Set up givers
    eng.set_quota("c1", "yas", 500)
    eng.set_quota("c1", "zed", 500)

    # Grant A: yas funds kef for 25
    reqA = eng.create_request("c1", "kef", Role.CONSUMER, 25, "test A", None, 0, 10_000_000)
    grantA = eng.fund_request(reqA.id, "yas", 25, now=1)

    # Grant B: zed funds kef for 40
    reqB = eng.create_request("c1", "kef", Role.CONSUMER, 40, "test B", None, 0, 10_000_000)
    grantB = eng.fund_request(reqB.id, "zed", 40, now=2)

    idp = InMemoryIdentityProvider({
        "fake_kef": ConsumerIdentity("kef", is_giver=False),
        "fake_yas": ConsumerIdentity("yas", is_giver=True),
    })
    reg = InMemoryPatRegistry({"yas": "ghp_yas", "zed": "ghp_zed"})
    svc = AttributionService(eng, idp, reg)

    ids = {
        "cycle": "c1",
        "kef_consumer": ConsumerIdentity("kef", is_giver=False),
        "yas_consumer": ConsumerIdentity("yas", is_giver=True),
        "grantA": grantA.id,
        "grantB": grantB.id,
    }
    return svc, ids


def test_debit_spills_across_grants(spill_ctx):
    """Core case: 50 AIU debit on grant A (25 remaining) drains A to 0 and
    spills the remaining 25 into grant B (B: 40 -> 15). Neither goes negative."""
    svc, ids = spill_ctx
    src = svc.select_source(ids["cycle"], ids["kef_consumer"])  # picks grant A
    assert src is not None
    assert src.bucket == Bucket.GRANT
    assert src.grant_id == ids["grantA"]

    svc.debit(ids["cycle"], ids["kef_consumer"], src, 50, ts=1)

    assert svc.engine.grant_remaining(ids["cycle"], ids["grantA"]) == 0
    assert svc.engine.grant_remaining(ids["cycle"], ids["grantB"]) == 15


def test_debit_own_source_single_record(spill_ctx):
    """OWN source must still behave as a single record (no spill loop).
    yas uses OWN bucket; consuming 10 from personal remaining, no side-effects
    on grant B."""
    svc, ids = spill_ctx
    src = svc.select_source(ids["cycle"], ids["yas_consumer"])
    assert src is not None
    assert src.bucket == Bucket.OWN

    before_b = svc.engine.grant_remaining(ids["cycle"], ids["grantB"])
    svc.debit(ids["cycle"], ids["yas_consumer"], src, 10, ts=2)

    # yas consumed from personal; grant B untouched
    assert svc.engine.consumed_total(ids["cycle"], "yas") == 10
    assert svc.engine.grant_remaining(ids["cycle"], ids["grantB"]) == before_b


def test_debit_exceeds_all_grants_records_remainder_on_source(spill_ctx):
    """When the debit exceeds all available grant headroom, the residual is
    recorded with overshoot=True on the original source grant, so total consumed
    equals the full cost.  Grant B is drained to 0; grant A absorbs the residual
    overshoot (it was the original source bucket)."""
    svc, ids = spill_ctx
    # Grant A has 25, grant B has 40 — total 65.  Debit 100.
    src = svc.select_source(ids["cycle"], ids["kef_consumer"])  # grant A
    assert src is not None

    svc.debit(ids["cycle"], ids["kef_consumer"], src, 100, ts=3)

    # Grant B fully drained; grant A carries the overshoot residual (35 - 65 = -35)
    assert svc.engine.grant_remaining(ids["cycle"], ids["grantB"]) == 0
    # Total consumed equals full cost regardless of per-grant distribution
    assert svc.engine.consumed_total(ids["cycle"], "kef") == 100


def test_debit_fits_within_source_grant_no_spill(spill_ctx):
    """When debit fits entirely within the source grant, only the source grant
    is touched and grant B is unchanged."""
    svc, ids = spill_ctx
    src = svc.select_source(ids["cycle"], ids["kef_consumer"])  # grant A (25)
    svc.debit(ids["cycle"], ids["kef_consumer"], src, 10, ts=4)

    assert svc.engine.grant_remaining(ids["cycle"], ids["grantA"]) == 15
    assert svc.engine.grant_remaining(ids["cycle"], ids["grantB"]) == 40


def test_debit_zero_is_noop(spill_ctx):
    """Zero-cost debit is a no-op (no records written)."""
    svc, ids = spill_ctx
    src = svc.select_source(ids["cycle"], ids["kef_consumer"])
    svc.debit(ids["cycle"], ids["kef_consumer"], src, 0, ts=5)

    assert svc.engine.grant_remaining(ids["cycle"], ids["grantA"]) == 25
    assert svc.engine.grant_remaining(ids["cycle"], ids["grantB"]) == 40
