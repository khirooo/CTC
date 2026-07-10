"""
Tests for health-aware select_source + exclude set (Task 4).

Build fixtures with the same _service / engine pattern used in test_attribution.py.
Each fixture returns (svc, ids) where ids is a dict with named user/cycle/grant ids.
"""
import pytest

from ctc.accounting.engine import AccountingEngine
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.domain.types import Bucket, Role
from ctc.routing.attribution import AttributionService, Source
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


class _Cfg:
    shared_pool_enabled = True
    default_pledge_pct = 0
    participants_mode = "givers_and_consumers"


def _make_engine():
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_Cfg())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    return eng


@pytest.fixture
def svc_kef_with_grant():
    """
    kef: giver, personal_remaining=0 (quota=0).
    yas: donor, quota=500.
    Active grant from yas -> kef.
    Returns (svc, ids) where ids has: kef, yas, cycle, grant_id, kef_consumer.
    """
    eng = _make_engine()
    # kef has zero quota -> personal_remaining = 0
    eng.set_quota("c1", "kef", 0)
    # yas has quota so they can fund
    eng.set_quota("c1", "yas", 500)

    idp = InMemoryIdentityProvider({
        "fake_kef": ConsumerIdentity("kef", is_giver=True),
    })
    reg = InMemoryPatRegistry({"kef": "ghp_kef", "yas": "ghp_yas"})
    svc = AttributionService(eng, idp, reg)

    # kef opens a request; yas funds it -> creates a grant
    req = eng.create_request("c1", "kef", Role.GIVER, 100, "need", None, 1, 10_000_000)
    grant = eng.fund_request(req.id, "yas", 100, 2)

    ids = {
        "kef": "kef",
        "yas": "yas",
        "cycle": "c1",
        "grant_id": grant.id,
        "kef_consumer": ConsumerIdentity("kef", is_giver=True),
    }
    return svc, ids


@pytest.fixture
def svc_kef_personal():
    """
    kef: giver, personal_remaining > 0 (quota=200). No grants.
    Returns (svc, ids) where ids has: kef, cycle, kef_consumer.
    """
    eng = _make_engine()
    eng.set_quota("c1", "kef", 200)

    idp = InMemoryIdentityProvider({
        "fake_kef": ConsumerIdentity("kef", is_giver=True),
    })
    reg = InMemoryPatRegistry({"kef": "ghp_kef"})
    svc = AttributionService(eng, idp, reg)

    ids = {
        "kef": "kef",
        "cycle": "c1",
        "kef_consumer": ConsumerIdentity("kef", is_giver=True),
    }
    return svc, ids


# ---------------------------------------------------------------------------
# Health tests
# ---------------------------------------------------------------------------

def test_skips_own_when_health_zero(svc_kef_with_grant):
    """OWN is skipped when health reports giver_id remaining=0; falls to GRANT."""
    svc, ids = svc_kef_with_grant
    # kef has personal_remaining=0 anyway here, but health gate must explicitly skip OWN
    # even if quota were >0. To test the gate, set kef quota>0 first via the engine.
    # Actually the fixture already has kef at quota=0, so OWN is skipped by credit too.
    # For a pure health-gate test we need kef with credit but health=0.
    # Re-use the grant fixture but give kef some quota so OWN *would* win without health.
    svc.engine.set_quota("c1", "kef", 50)
    src = svc.select_source(ids["cycle"], ids["kef_consumer"],
                            health={ids["kef"]: 0})
    assert src is not None
    assert src.bucket == Bucket.GRANT
    assert src.giver_id == ids["yas"]


def test_allows_own_when_health_unknown(svc_kef_personal):
    """OWN is allowed when health is None (unknown -> ALLOW)."""
    svc, ids = svc_kef_personal
    src = svc.select_source(ids["cycle"], ids["kef_consumer"], health=None)
    assert src is not None
    assert src.bucket == Bucket.OWN


def test_allows_own_when_health_absent_for_giver(svc_kef_personal):
    """OWN is allowed when health dict exists but giver_id is absent (treat as unknown)."""
    svc, ids = svc_kef_personal
    src = svc.select_source(ids["cycle"], ids["kef_consumer"], health={})
    assert src is not None
    assert src.bucket == Bucket.OWN


def test_allows_own_when_health_value_is_none(svc_kef_personal):
    """OWN is allowed when health[giver_id] is None (unknown -> ALLOW)."""
    svc, ids = svc_kef_personal
    src = svc.select_source(ids["cycle"], ids["kef_consumer"],
                            health={ids["kef"]: None})
    assert src is not None
    assert src.bucket == Bucket.OWN


def test_skips_grant_when_donor_exhausted(svc_kef_with_grant):
    """OWN gated (health=0), only grant present but donor also exhausted -> None."""
    svc, ids = svc_kef_with_grant
    # kef has quota=0, no OWN; yas donor health=0 -> grant skipped too
    src = svc.select_source(ids["cycle"], ids["kef_consumer"],
                            health={ids["kef"]: 0, ids["yas"]: 0})
    assert src is None


def test_grant_allowed_when_donor_health_unknown(svc_kef_with_grant):
    """Donor health absent -> GRANT allowed even when OWN is health-gated."""
    svc, ids = svc_kef_with_grant
    # Gate kef OWN (add quota so it would normally win, then health=0)
    svc.engine.set_quota("c1", "kef", 50)
    src = svc.select_source(ids["cycle"], ids["kef_consumer"],
                            health={ids["kef"]: 0})  # yas absent -> unknown -> allowed
    assert src is not None
    assert src.bucket == Bucket.GRANT
    assert src.giver_id == ids["yas"]


# ---------------------------------------------------------------------------
# Exclude tests
# ---------------------------------------------------------------------------

def test_exclude_grant_skips_it(svc_kef_with_grant):
    """Excluding the grant_id skips that GRANT; kef personal_remaining=0 -> None."""
    svc, ids = svc_kef_with_grant
    src = svc.select_source(ids["cycle"], ids["kef_consumer"],
                            exclude=frozenset({ids["grant_id"]}))
    assert src is None  # OWN ineligible (pr=0), only grant excluded


def test_exclude_own_giver_falls_to_grant(svc_kef_with_grant):
    """Excluding kef's giver_id skips OWN; GRANT from yas is returned."""
    svc, ids = svc_kef_with_grant
    # Give kef credit so OWN would normally win
    svc.engine.set_quota("c1", "kef", 50)
    src = svc.select_source(ids["cycle"], ids["kef_consumer"],
                            exclude=frozenset({ids["kef"]}))
    assert src is not None
    assert src.bucket == Bucket.GRANT
    assert src.giver_id == ids["yas"]


# ---------------------------------------------------------------------------
# Backward-compatibility: positional callers must still work unchanged
# ---------------------------------------------------------------------------

def test_existing_positional_call_still_works(svc_kef_personal):
    """select_source(cycle_id, consumer) with NO kwargs must still work."""
    svc, ids = svc_kef_personal
    src = svc.select_source(ids["cycle"], ids["kef_consumer"])
    assert src is not None
    assert src.bucket == Bucket.OWN


def test_pool_fill_grant_excluded_by_grant_id(svc_kef_with_grant):
    """A pool-fill grant behaves like any other grant: excluding its grant_id
    (the failover loop's key for GRANT sources) skips it."""
    svc, ids = svc_kef_with_grant
    # Give kef a pledge so the pool has capacity, then pool-fill carol's request.
    svc.engine.set_quota("c1", "kef", 200)
    svc.engine.set_pledge("c1", "kef", 100)
    req = svc.engine.create_request("c1", "carol", Role.CONSUMER, 80, "need", None, 1, 10_000_000)
    grants = svc.engine.fund_request_from_pool(req.id, "carol", 80, 2)
    assert len(grants) == 1

    carol = ConsumerIdentity("carol", is_giver=False)
    src_normal = svc.select_source(ids["cycle"], carol)
    assert src_normal is not None and src_normal.bucket == Bucket.GRANT
    assert src_normal.grant_id == grants[0].id

    src_excluded = svc.select_source(ids["cycle"], carol,
                                     exclude=frozenset({grants[0].id}))
    assert src_excluded is None
