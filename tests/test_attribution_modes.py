from ctc.routing.attribution import AttributionService
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.accounting.engine import AccountingEngine
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db
from ctc.domain.types import Bucket


class _Cfg:
    def __init__(self, pool, mode): self.shared_pool_enabled = pool; self.participants_mode = mode
    free_allowance = 300 * 1_000_000_000
    default_pledge_pct = 0


def _engine(pool=True, mode="givers_and_consumers"):
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_Cfg(pool, mode))
    cyc = eng.ensure_active_cycle(1000)
    return eng, cyc


def test_pool_off_consumer_with_no_grant_gets_no_source():
    eng, cyc = _engine(pool=False)
    # a giver exists with pledge, but pool is off → consumer cannot draw pool
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    idp = InMemoryIdentityProvider({"tokC": ConsumerIdentity("c1", is_giver=False)})
    svc = AttributionService(eng, idp, pats)
    assert svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False)) is None


def test_pool_on_consumer_draws_pool():
    eng, cyc = _engine(pool=True)
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    src = svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False))
    assert src is not None and src.bucket == Bucket.POOL


def test_givers_only_blocks_non_giver_even_when_pool_would_fund():
    # pool ON so that WITHOUT the givers_only gate the non-giver would resolve to
    # POOL. The gate must make it None regardless — this is the genuine red.
    eng, cyc = _engine(pool=True, mode="givers_only")
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    assert svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False)) is None


def test_givers_and_consumers_pool_on_still_funds_non_giver():
    # Control: same setup but mode allows consumers → POOL source returned.
    eng, cyc = _engine(pool=True, mode="givers_and_consumers")
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    eng.set_pledge(cyc.id, "g1", 50 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    src = svc.select_source(cyc.id, ConsumerIdentity("c1", is_giver=False))
    assert src is not None and src.bucket == Bucket.POOL


def test_givers_only_allows_giver_with_own_credit():
    eng, cyc = _engine(pool=False, mode="givers_only")
    eng.set_quota(cyc.id, "g1", 100 * 1_000_000_000)
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    src = svc.select_source(cyc.id, ConsumerIdentity("g1", is_giver=True))
    assert src is not None and src.bucket == Bucket.OWN
