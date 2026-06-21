from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig
from ctc.domain.config import NANO_PER_AIU
from ctc.accounting.engine import AccountingEngine


def test_engine_allowance_uses_override():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn)
    s.set_many({"free_allowance_aiu": "10"}, "admin1", 1000)   # 10 AIU
    eng = AccountingEngine(AccountingStore(conn), config=EffectiveConfig(s))
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    assert eng.allowance_remaining("c1", "u_x") == 10 * NANO_PER_AIU


def test_engine_defaults_to_env_config_when_unset():
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn))   # no config arg → env default
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    from ctc.domain.config import config
    assert eng.allowance_remaining("c1", "u_x") == config.free_allowance
