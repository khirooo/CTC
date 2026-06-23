from ctc.accounting.engine import AccountingEngine
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.domain.types import Bucket, Role
from ctc.routing.attribution import AttributionService, Source
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


class _PoolEnabledConfig:
    """Config with shared pool enabled for testing."""
    shared_pool_enabled = True
    free_allowance = 300 * 1_000_000_000
    default_pledge_pct = 0
    participants_mode = "givers_and_consumers"


def _service(pledge_alice=100, quota_alice=200, quota_bob=0, alice_is_giver=True):
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_PoolEnabledConfig())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    eng.set_quota("c1", "alice", quota_alice)
    eng.set_pledge("c1", "alice", min(pledge_alice, quota_alice))  # pledge capped to quota (engine invariant)
    idp = InMemoryIdentityProvider({
        "fake_alice": ConsumerIdentity("alice", is_giver=alice_is_giver),
        "fake_carol": ConsumerIdentity("carol", is_giver=False),  # non-PAT consumer
    })
    reg = InMemoryPatRegistry({"alice": "ghp_alice", "bob": "ghp_bob"})
    return AttributionService(eng, idp, reg), eng


def test_resolve_consumer():
    svc, _ = _service()
    assert svc.resolve_consumer("fake_alice").user_id == "alice"
    assert svc.resolve_consumer("unknown") is None


def test_giver_uses_own_first():
    svc, _ = _service()
    src = svc.select_source("c1", ConsumerIdentity("alice", is_giver=True))
    assert src == Source(bucket=Bucket.OWN, giver_id="alice", pat="ghp_alice", grant_id=None)


def test_non_pat_uses_pool_with_max_capacity_giver():
    svc, _ = _service()
    src = svc.select_source("c1", ConsumerIdentity("carol", is_giver=False))
    assert src.bucket == Bucket.POOL
    assert src.giver_id == "alice"
    assert src.pat == "ghp_alice"


def test_non_pat_blocked_when_no_pool_capacity():
    svc, _ = _service(pledge_alice=0)  # nothing pledged -> no pool giver
    assert svc.select_source("c1", ConsumerIdentity("carol", is_giver=False)) is None


def test_giver_falls_to_grant_when_own_exhausted():
    svc, eng = _service(quota_alice=0)  # alice (consumer) has no own credit
    # bob funds a request alice opened, creating a grant from bob.
    eng.set_quota("c1", "bob", 500)
    req = eng.create_request("c1", "alice", Role.GIVER, 100, "need", None, 1, 10_000_000)
    grant = eng.fund_request(req.id, "bob", 100, 2)
    src = svc.select_source("c1", ConsumerIdentity("alice", is_giver=True))
    assert src == Source(bucket=Bucket.GRANT, giver_id="bob", pat="ghp_bob", grant_id=grant.id)


def test_debit_records_actual_cost_against_source():
    svc, eng = _service()
    consumer = ConsumerIdentity("carol", is_giver=False)
    src = svc.select_source("c1", consumer)
    svc.debit("c1", consumer, src, cost_nano_aiu=37, ts=5)
    assert eng.consumed_total("c1", "carol") == 37


def test_debit_zero_is_noop():
    svc, eng = _service()
    consumer = ConsumerIdentity("carol", is_giver=False)
    src = svc.select_source("c1", consumer)
    svc.debit("c1", consumer, src, cost_nano_aiu=0, ts=5)
    assert eng.consumed_total("c1", "carol") == 0


def test_any_giver_pat_returns_a_stored_pat():
    """Non-billable bootstrap/validation calls (e.g. /copilot_internal/user) aren't
    metered and have no selected source, but still need a real PAT upstream. The
    proxy grabs any stored giver PAT for those."""
    svc, _ = _service()
    assert svc.any_giver_pat() in {"ghp_alice", "ghp_bob"}


def test_any_giver_pat_none_when_no_pats():
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_PoolEnabledConfig())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    svc = AttributionService(eng, InMemoryIdentityProvider({}), InMemoryPatRegistry({}))
    assert svc.any_giver_pat() is None


def test_giver_with_credit_but_no_pat_falls_through_to_grant():
    """A giver who has personal_remaining > 0 but whose giver_id is NOT in the PAT
    registry must NOT be returned as an OWN Source — select_source should fall through
    to GRANT (or None if no grant exists)."""
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_PoolEnabledConfig())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    eng.set_quota("c1", "alice", 100)
    eng.set_pledge("c1", "alice", 50)
    idp = InMemoryIdentityProvider({
        "fake_alice": ConsumerIdentity("alice", is_giver=True),
    })
    # alice's PAT is intentionally omitted from the registry
    reg = InMemoryPatRegistry({})
    svc = AttributionService(eng, idp, reg)
    src = svc.select_source("c1", ConsumerIdentity("alice", is_giver=True))
    # OWN requires a PAT in the registry; with no PAT and no grant, result must be None
    assert src is None or src.bucket != Bucket.OWN
