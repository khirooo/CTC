from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig
from ctc.domain.config import NANO_PER_AIU
from ctc.accounting.engine import AccountingEngine


def test_engine_allowance_uses_override():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn)
    # pool on so the allowance is live (it's 0 when the pool is off)
    s.set_many({"shared_pool_enabled": "on", "free_allowance_aiu": "10"}, "admin1", 1000)
    eng = AccountingEngine(AccountingStore(conn), config=EffectiveConfig(s))
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    assert eng.allowance_remaining("c1", "u_x") == 10 * NANO_PER_AIU


def test_engine_allowance_zeroed_when_pool_off():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn)
    s.set_many({"shared_pool_enabled": "off", "free_allowance_aiu": "10"}, "admin1", 1000)
    eng = AccountingEngine(AccountingStore(conn), config=EffectiveConfig(s))
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    assert eng.allowance_remaining("c1", "u_x") == 0


def test_engine_defaults_to_env_config_when_unset():
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn))   # no config arg → raw env Config
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    from ctc.domain.config import config
    # the raw env Config has no pool-off zeroing (that lives in EffectiveConfig),
    # so it returns the configured allowance verbatim
    assert eng.allowance_remaining("c1", "u_x") == config.free_allowance
