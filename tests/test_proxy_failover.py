import asyncio

import proxy
import pytest

from ctc.accounting.engine import AccountingEngine
from ctc.auth.identity import ConsumerIdentity
from ctc.domain.config import NANO_PER_AIU as _N
from ctc.domain.types import Cycle, GiverCycle, Role
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


# --------------------------------------------------------------------------- #
# Shared fixture: engine with cycle "c1", giver "g1", quota 4000 AIU
# --------------------------------------------------------------------------- #
@pytest.fixture
def _engine_quota_4000():
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle("c1", "c", 0, 1_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle("c1", "g1", 4000 * _N, 0))
    return AccountingEngine(s)


class _FakeCache:
    def __init__(self, value):
        self._value = value
        self.exhausted = []

    async def get(self, gid):
        return self._value

    def set_exhausted(self, gid):
        self.exhausted.append(gid)


# --------------------------------------------------------------------------- #
# is_quota_exceeded_402
# --------------------------------------------------------------------------- #
def test_is_quota_exceeded_402_true():
    body = b'{"error":{"message":"You have exceeded your monthly quota","code":"quota_exceeded"}}'
    assert proxy.is_quota_exceeded_402(402, body) is True


def test_is_quota_exceeded_402_false_on_ctc_block():
    body = b'{"error":{"message":"...","type":"ctc_error","code":"ctc"}}'
    assert proxy.is_quota_exceeded_402(402, body) is False


def test_is_quota_exceeded_402_false_on_200():
    assert proxy.is_quota_exceeded_402(200, b'{}') is False


def test_is_quota_exceeded_402_false_on_garbage():
    assert proxy.is_quota_exceeded_402(402, b'not json') is False


# --------------------------------------------------------------------------- #
# Engine + service fixtures (mirror tests/test_attribution.py)
# --------------------------------------------------------------------------- #
class _PoolEnabledConfig:
    shared_pool_enabled = True
    free_allowance = 300 * 1_000_000_000
    default_pledge_pct = 0
    participants_mode = "givers_and_consumers"


def _engine():
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_PoolEnabledConfig())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    return eng


class _FakeLiveCache:
    def __init__(self):
        self.exhausted = []

    def set_exhausted(self, giver_id):
        self.exhausted.append(giver_id)


# --------------------------------------------------------------------------- #
# candidate_givers
# --------------------------------------------------------------------------- #
def test_candidate_givers_includes_self_when_giver():
    eng = _engine()
    eng.set_quota("c1", "alice", 100)
    consumer = ConsumerIdentity("alice", is_giver=True)
    assert proxy.candidate_givers(eng, "c1", consumer) == {"alice"}


def test_candidate_givers_excludes_self_when_not_giver():
    eng = _engine()
    consumer = ConsumerIdentity("carol", is_giver=False)
    assert proxy.candidate_givers(eng, "c1", consumer) == set()


def test_candidate_givers_adds_grant_donors():
    eng = _engine()
    eng.set_quota("c1", "bob", 500)
    req = eng.create_request("c1", "carol", Role.CONSUMER, 100, "need", None, 1, 10_000_000)
    eng.fund_request(req.id, "bob", 100, 2)
    consumer = ConsumerIdentity("carol", is_giver=False)
    assert proxy.candidate_givers(eng, "c1", consumer) == {"bob"}


def test_candidate_givers_union_self_and_donors():
    eng = _engine()
    eng.set_quota("c1", "alice", 100)
    eng.set_quota("c1", "bob", 500)
    req = eng.create_request("c1", "alice", Role.GIVER, 100, "need", None, 1, 10_000_000)
    eng.fund_request(req.id, "bob", 100, 2)
    consumer = ConsumerIdentity("alice", is_giver=True)
    assert proxy.candidate_givers(eng, "c1", consumer) == {"alice", "bob"}


# --------------------------------------------------------------------------- #
# reconcile_exhausted
# --------------------------------------------------------------------------- #
def test_reconcile_exhausted_books_bypass_and_marks_cache(_engine_quota_4000):
    eng = _engine_quota_4000
    cache = _FakeCache({"entitlement": 4000, "remaining": 1500})
    asyncio.run(proxy.reconcile_exhausted(eng, cache, "c1", "g1"))
    # treats card as fully spent: bypass = entitlement - tracked = 4000*N
    assert eng.store.bypass_consumed("c1", "g1") == 4000 * _N
    assert "g1" in cache.exhausted


def test_reconcile_exhausted_swallows_reconcile_failure():
    class _Boom:
        store = None
        def reconcile_giver(self, *a, **k):
            raise RuntimeError("boom")
    cache = _FakeCache({"entitlement": 4000, "remaining": 0})
    # must not raise
    asyncio.run(proxy.reconcile_exhausted(_Boom(), cache, "c1", "g1"))
    assert "g1" in cache.exhausted


def test_reconcile_exhausted_none_cache_is_safe(_engine_quota_4000):
    asyncio.run(proxy.reconcile_exhausted(_engine_quota_4000, None, "c1", "g1"))


# --------------------------------------------------------------------------- #
# reconcile_candidate
# --------------------------------------------------------------------------- #
def test_reconcile_candidate_returns_remaining_and_debounces(_engine_quota_4000):
    eng = _engine_quota_4000  # fixture: cycle "c1", giver "g1", quota 4000*N, no events
    cache = _FakeCache({"entitlement": 4000, "remaining": 1500})
    # Hot path is debounced: the first candidate reconcile captures the burn
    # baseline and books nothing (avoids double-booking in-flight cost, P1-2/3),
    # but still returns the giver's live remaining for the health gate.
    rem = asyncio.run(proxy.reconcile_candidate(eng, cache, "c1", "g1"))
    assert rem == 1500
    assert eng.store.bypass_consumed("c1", "g1") == 0
    gc = eng.store.get_giver_cycle("c1", "g1")
    assert gc.burn_baseline == 2500 * _N   # github_burn(4000-1500) - tracked(0)


def test_reconcile_candidate_unknown_quota_returns_none(_engine_quota_4000):
    rem = asyncio.run(proxy.reconcile_candidate(_engine_quota_4000, _FakeCache(None), "c1", "g1"))
    assert rem is None


def test_reconcile_candidate_reconcile_failure_still_returns_remaining(_engine_quota_4000):
    class _BrokenEngine:
        def reconcile_giver(self, *a, **kw):
            raise RuntimeError("db locked")
    cache = _FakeCache({"entitlement": 4000, "remaining": 1500})
    rem = asyncio.run(proxy.reconcile_candidate(_BrokenEngine(), cache, "c1", "g1"))
    assert rem == 1500  # remaining returned despite reconcile failure
