from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig
from ctc.domain.config import NANO_PER_AIU
from ctc.accounting.engine import AccountingEngine


def test_engine_reads_live_settings_override():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn)
    s.set_many({"shared_pool_enabled": "on", "default_pledge_pct": "25"}, "admin1", 1000)
    eng = AccountingEngine(AccountingStore(conn), config=EffectiveConfig(s))
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    assert eng.config.shared_pool_enabled is True
    assert eng.config.default_pledge_pct == 25


def test_engine_pledge_pct_zeroed_when_pool_off():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn)
    s.set_many({"shared_pool_enabled": "off", "default_pledge_pct": "25"}, "admin1", 1000)
    eng = AccountingEngine(AccountingStore(conn), config=EffectiveConfig(s))
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    assert eng.config.default_pledge_pct == 0


def test_engine_defaults_to_env_config_when_unset():
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn))   # no config arg → raw env Config
    eng.start_cycle("c1", "June", 0, 10 * NANO_PER_AIU)
    from ctc.domain.config import config
    assert eng.config is config
    assert eng.config.request_expiry_hours == config.request_expiry_hours
