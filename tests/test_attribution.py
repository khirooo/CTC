from ctc.accounting.engine import AccountingEngine
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.domain.types import Bucket, Role
from ctc.routing.attribution import AttributionService, Source
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


class _PoolEnabledConfig:
    """Config with shared pool enabled for testing."""
    shared_pool_enabled = True
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


def test_non_pat_without_grants_gets_nothing():
    # The shared pool no longer auto-routes: a consumer with no grants has no
    # credit source even when pool capacity exists.
    svc, _ = _service()
    assert svc.select_source("c1", ConsumerIdentity("carol", is_giver=False)) is None


def test_non_pat_routes_through_pool_fill_grant():
    # Pool credit reaches a consumer as a source='pool' grant created in the
    # marketplace; routing then treats it like any other grant.
    svc, eng = _service()
    req = eng.create_request("c1", "carol", Role.CONSUMER, 80, "need", None, 1, 10_000_000)
    grants = eng.fund_request_from_pool(req.id, "carol", 80, 2)
    assert [g.donor_id for g in grants] == ["alice"]
    src = svc.select_source("c1", ConsumerIdentity("carol", is_giver=False))
    assert src == Source(bucket=Bucket.GRANT, giver_id="alice", pat="ghp_alice",
                         grant_id=grants[0].id)


def test_giver_falls_to_grant_when_own_exhausted():
    svc, eng = _service(quota_alice=0)  # alice (consumer) has no own credit
    # bob funds a request alice opened, creating a grant from bob.
    eng.set_quota("c1", "bob", 500)
    req = eng.create_request("c1", "alice", Role.GIVER, 100, "need", None, 1, 10_000_000)
    grant = eng.fund_request(req.id, "bob", 100, 2)
    src = svc.select_source("c1", ConsumerIdentity("alice", is_giver=True))
    assert src == Source(bucket=Bucket.GRANT, giver_id="bob", pat="ghp_bob", grant_id=grant.id)


def _carol_with_pool_grant(svc, eng):
    req = eng.create_request("c1", "carol", Role.CONSUMER, 80, "need", None, 1, 10_000_000)
    eng.fund_request_from_pool(req.id, "carol", 80, 2)
    return ConsumerIdentity("carol", is_giver=False)


def test_debit_records_actual_cost_against_source():
    svc, eng = _service()
    consumer = _carol_with_pool_grant(svc, eng)
    src = svc.select_source("c1", consumer)
    svc.debit("c1", consumer, src, cost_nano_aiu=37, ts=5)
    assert eng.consumed_total("c1", "carol") == 37


def test_debit_zero_is_noop():
    svc, eng = _service()
    consumer = _carol_with_pool_grant(svc, eng)
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


class _HealthReg:
    """PatRegistry stub with an explicit per-giver health verdict."""
    def __init__(self, pats, health):
        self._pats = pats
        self._health = health
    def pat_for(self, gid): return self._pats.get(gid)
    def list_givers(self): return list(self._pats)
    def pat_health_status(self, gid): return self._health.get(gid)


def _empty_engine():
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_PoolEnabledConfig())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    return eng


def test_any_giver_pat_prefers_valid_health():
    # A dead PAT must not be borrowed for a non-billable call when a valid one
    # exists (same shape as the /responses incident).
    reg = _HealthReg({"dead": "ghp_dead", "ok": "ghp_ok"},
                     {"dead": "expired", "ok": "valid"})
    svc = AttributionService(_empty_engine(), InMemoryIdentityProvider({}), reg)
    assert svc.any_giver_pat() == "ghp_ok"


def test_any_giver_pat_falls_back_when_none_valid():
    # Unknown/never-checked health (None) is not treated as dead — still usable.
    reg = _HealthReg({"a": "ghp_a"}, {"a": None})
    svc = AttributionService(_empty_engine(), InMemoryIdentityProvider({}), reg)
    assert svc.any_giver_pat() == "ghp_a"


def test_pinned_own_source_gated_by_headroom():
    svc, eng = _service(quota_alice=200, pledge_alice=0)
    src = Source(bucket=Bucket.OWN, giver_id="alice", pat="ghp_alice")
    svc.pin_source(("alice", "sess-1"), src, expires_at=2000, now=1000)
    # headroom present → pin honored
    assert svc.pinned_source(("alice", "sess-1"), cycle_id="c1", now=1500) == src
    # drain alice's personal credit → no headroom → pin dropped (falls back)
    eng.record_consumption("c1", "alice", "alice", Bucket.OWN, 200, ts=1, allow_overshoot=True)
    assert svc.pinned_source(("alice", "sess-1"), cycle_id="c1", now=1500) is None
    # legacy callers that omit cycle_id skip the headroom re-check
    assert svc.pinned_source(("alice", "sess-1"), now=1500) == src


def test_pinned_grant_source_gated_by_headroom():
    svc, eng = _service(quota_alice=0)
    eng.set_quota("c1", "bob", 500)
    req = eng.create_request("c1", "carol", Role.CONSUMER, 100, "need", None, 1, 10_000_000)
    grant = eng.fund_request(req.id, "bob", 100, 2)
    src = Source(bucket=Bucket.GRANT, giver_id="bob", pat="ghp_bob", grant_id=grant.id)
    svc.pin_source(("carol", "s"), src, expires_at=2000, now=1000)
    assert svc.pinned_source(("carol", "s"), cycle_id="c1", now=1500) == src
    eng.record_consumption("c1", "carol", "bob", Bucket.GRANT, 100,
                           grant_id=grant.id, ts=3, allow_overshoot=True)
    assert svc.pinned_source(("carol", "s"), cycle_id="c1", now=1500) is None


def test_pinned_source_returns_pinned_giver_before_expiry():
    """A giver pinned from a /models/session bootstrap call is returned as-is
    (not re-derived from select_source) as long as it hasn't expired."""
    svc, _ = _service()
    src = Source(bucket=Bucket.POOL, giver_id="bob", pat="ghp_bob")
    svc.pin_source(("carol", "sess-1"), src, expires_at=2000, now=1000)
    assert svc.pinned_source(("carol", "sess-1"), now=1500) == src


def test_pinned_source_none_after_expiry():
    svc, _ = _service()
    src = Source(bucket=Bucket.POOL, giver_id="bob", pat="ghp_bob")
    svc.pin_source(("carol", "sess-1"), src, expires_at=1100, now=1000)
    # expires_at - now (100s) is clamped up to SESSION_PIN_MIN_TTL_S (60s), so
    # this hasn't expired yet at +90s...
    assert svc.pinned_source(("carol", "sess-1"), now=1090) == src
    # ...but has by +9000s (well past even the max clamp).
    assert svc.pinned_source(("carol", "sess-1"), now=10000) is None


def test_pinned_source_ttl_clamped_to_max():
    """A bogus far-future expires_at doesn't pin forever -- clamped to
    SESSION_PIN_MAX_TTL_S (30 min)."""
    svc, _ = _service()
    src = Source(bucket=Bucket.POOL, giver_id="bob", pat="ghp_bob")
    svc.pin_source(("carol", "sess-1"), src, expires_at=10**9, now=1000)
    assert svc.pinned_source(("carol", "sess-1"), now=1000 + 30 * 60 - 1) == src
    assert svc.pinned_source(("carol", "sess-1"), now=1000 + 30 * 60 + 1) is None


def test_pinned_source_missing_or_malformed_expiry_uses_max_ttl():
    svc, _ = _service()
    src = Source(bucket=Bucket.POOL, giver_id="bob", pat="ghp_bob")
    svc.pin_source(("carol", "sess-1"), src, expires_at=None, now=1000)
    assert svc.pinned_source(("carol", "sess-1"), now=1000 + 30 * 60 - 1) == src
    assert svc.pinned_source(("carol", "sess-1"), now=1000 + 30 * 60 + 1) is None


def test_pinned_source_none_when_no_pin():
    svc, _ = _service()
    assert svc.pinned_source(("carol", "sess-1")) is None
    assert svc.pinned_source(None) is None


def test_pinned_source_none_when_giver_reported_dead():
    """A pin is not resurrected if the pinned giver has since gone dead in the
    live-quota health map (mirrors select_source's own health gating)."""
    svc, _ = _service()
    src = Source(bucket=Bucket.POOL, giver_id="bob", pat="ghp_bob")
    svc.pin_source(("carol", "sess-1"), src, expires_at=2000, now=1000)
    assert svc.pinned_source(("carol", "sess-1"), health={"bob": 0}, now=1500) is None
    assert svc.pinned_source(("carol", "sess-1"), health={"bob": 5}, now=1500) == src
    assert svc.pinned_source(("carol", "sess-1"), health={"alice": 0}, now=1500) == src


def test_pinned_source_scoped_per_consumer_and_session_id():
    """Different (consumer, x-client-session-id) pairs don't collide, even for
    the same consumer running two concurrent CLI sessions."""
    svc, _ = _service()
    src_a = Source(bucket=Bucket.POOL, giver_id="alice", pat="ghp_alice")
    src_b = Source(bucket=Bucket.POOL, giver_id="bob", pat="ghp_bob")
    svc.pin_source(("carol", "sess-a"), src_a, expires_at=2000, now=1000)
    svc.pin_source(("carol", "sess-b"), src_b, expires_at=2000, now=1000)
    assert svc.pinned_source(("carol", "sess-a"), now=1500) == src_a
    assert svc.pinned_source(("carol", "sess-b"), now=1500) == src_b
    assert svc.pinned_source(("dave", "sess-a"), now=1500) is None


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
