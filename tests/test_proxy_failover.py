import proxy

from ctc.accounting.engine import AccountingEngine
from ctc.auth.identity import ConsumerIdentity
from ctc.domain.types import Role
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


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
import asyncio


def test_reconcile_exhausted_marks_cache_and_drives_quota_to_floor():
    eng = _engine()
    eng.set_quota("c1", "bob", 500)
    cache = _FakeLiveCache()
    floor = eng.store.pool_consumed_from("c1", "bob")  # 0, nothing consumed yet
    asyncio.run(proxy.reconcile_exhausted(eng, cache, "c1", "bob", 100))
    assert cache.exhausted == ["bob"]
    # quota driven down to the consumed floor
    assert eng.personal_remaining("c1", "bob") == 0


def test_reconcile_exhausted_swallows_set_quota_failure():
    eng = _engine()
    cache = _FakeLiveCache()
    # giver_id with no giver-cycle row: set_quota may raise; reconcile must not.
    asyncio.run(proxy.reconcile_exhausted(eng, cache, "c1", "ghost", 100))
    # cache still marked even if the ledger write failed
    assert cache.exhausted == ["ghost"]


def test_reconcile_exhausted_none_cache_is_safe():
    eng = _engine()
    eng.set_quota("c1", "bob", 500)
    # must not raise when live_cache is None
    asyncio.run(proxy.reconcile_exhausted(eng, None, "c1", "bob", 100))
