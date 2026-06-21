import pytest

from ctc.accounting.engine import AccountingEngine
from ctc.accounting.errors import InsufficientCredit, InvalidConsumption
from ctc.domain.types import Bucket
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


def _engine():
    conn = connect(":memory:")
    init_db(conn)
    eng = AccountingEngine(AccountingStore(conn))
    eng.start_cycle("c1", "June", 0, 10_000_000)
    eng.set_quota("c1", "alice", 100)
    return eng


def test_overshoot_false_still_raises_over_cap():
    eng = _engine()
    with pytest.raises(InsufficientCredit):
        eng.record_consumption("c1", "alice", "alice", Bucket.OWN, 150, ts=1)


def test_overshoot_true_records_past_cap():
    eng = _engine()
    ev = eng.record_consumption("c1", "alice", "alice", Bucket.OWN, 150, ts=1, allow_overshoot=True)
    assert ev.credits == 150
    # personal_remaining goes negative — the overshoot is recorded as fact.
    assert eng.personal_remaining("c1", "alice") == 100 - 150


def test_overshoot_true_still_enforces_consistency():
    eng = _engine()
    # OWN must be self-sourced regardless of overshoot.
    with pytest.raises(InvalidConsumption):
        eng.record_consumption("c1", "alice", "bob", Bucket.OWN, 10, ts=1, allow_overshoot=True)


def test_overshoot_true_still_enforces_grant_consistency():
    """With allow_overshoot=True, a GRANT bucket with an unknown grant_id still raises
    InvalidConsumption — consistency checks are not bypassed by overshoot."""
    eng = _engine()
    with pytest.raises(InvalidConsumption):
        eng.record_consumption("c1", "alice", "alice", Bucket.GRANT, 10, ts=1,
                               grant_id="nonexistent-grant-id", allow_overshoot=True)
