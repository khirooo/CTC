from ctc.domain.config import config, NANO_PER_AIU
from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine


def _engine():
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn))
    eng.start_cycle("c1", "June", 0, 10**12)
    return eng


def test_nano_per_aiu_value():
    assert NANO_PER_AIU == 1_000_000_000


def test_free_allowance_is_stored_in_nano():
    # config.free_allowance is nano-AIU (300 AIU default), so it is a multiple of NANO_PER_AIU.
    assert config.free_allowance % NANO_PER_AIU == 0
    assert config.free_allowance >= NANO_PER_AIU


def test_allowance_remaining_is_full_allowance_when_unconsumed():
    eng = _engine()
    # A consumer who has consumed nothing has the full (nano-AIU) allowance.
    assert eng.allowance_remaining("c1", "u_consumer") == config.free_allowance
