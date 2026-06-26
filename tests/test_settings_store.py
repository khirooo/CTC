# tests/test_settings_store.py
import pytest
from ctc.store.db import connect, init_db
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig, effective_view, validate_patch
from ctc.domain.config import config
from ctc.domain.config import NANO_PER_AIU


def _store():
    conn = connect(":memory:"); init_db(conn)
    return SettingsStore(conn)


def test_empty_store_falls_back_to_env_defaults():
    ec = EffectiveConfig(_store())
    # free_allowance returns 0 when shared_pool_enabled is False (the default),
    # mirroring default_pledge_pct — the allowance is meaningless without the pool
    assert ec.free_allowance == 0
    assert ec.request_expiry_hours == config.request_expiry_hours
    assert ec.request_expiry_max_hours == config.request_expiry_max_hours
    assert ec.credit_to_euro_rate == config.credit_to_euro_rate
    # default_pledge_pct returns 0 when shared_pool_enabled is False (the default)
    assert ec.default_pledge_pct == 0


def test_override_is_read_back_typed():
    s = _store()
    # Enable shared pool so default_pledge_pct is not forced to 0
    s.set_many({"shared_pool_enabled": "on", "free_allowance_aiu": "500",
                "default_pledge_pct": "40", "credit_to_euro_rate": "0.25"}, "admin1", 1000)
    ec = EffectiveConfig(s)
    assert ec.free_allowance == 500 * NANO_PER_AIU   # stored as AIU, exposed as nano
    assert ec.default_pledge_pct == 40
    assert ec.credit_to_euro_rate == 0.25


def test_effective_view_reports_overrides_and_aiu():
    s = _store()
    # pool on so the allowance isn't forced to 0
    s.set_many({"shared_pool_enabled": "on", "free_allowance_aiu": "500"}, "admin1", 1000)
    view = effective_view(EffectiveConfig(s), s)
    assert view["free_allowance_aiu"] == {"value": 500, "is_override": True}      # AIU, not nano
    assert view["credit_to_euro_rate"]["is_override"] is False


def test_free_allowance_zeroed_when_pool_off():
    s = _store()
    # allowance is configured but the pool is off → effective value is 0, but the
    # stored override is preserved (comes back when the pool is re-enabled)
    s.set_many({"shared_pool_enabled": "off", "free_allowance_aiu": "500"}, "admin1", 1000)
    assert EffectiveConfig(s).free_allowance == 0
    s.set_many({"shared_pool_enabled": "on"}, "admin1", 1001)
    assert EffectiveConfig(s).free_allowance == 500 * NANO_PER_AIU


def test_validate_patch_bounds():
    with pytest.raises(ValueError):
        validate_patch({"default_pledge_pct": "150"})       # > 100
    with pytest.raises(ValueError):
        validate_patch({"free_allowance_aiu": "0"})         # must be > 0
    with pytest.raises(ValueError):
        validate_patch({"request_expiry_max_hours": "5", "request_expiry_hours": "10"})  # max < default
    out = validate_patch({"free_allowance_aiu": "300", "credit_to_euro_rate": "0.1"})
    assert out == {"free_allowance_aiu": "300", "credit_to_euro_rate": "0.1"}


def test_validate_patch_rejects_unknown_key():
    with pytest.raises(ValueError):
        validate_patch({"bogus": "1"})


def test_validate_patch_cross_field_uses_current_state():
    # only max patched, but current override already raised the default above it
    with pytest.raises(ValueError):
        validate_patch({"request_expiry_max_hours": "36"}, current={"request_expiry_hours": 48})
    # and the inverse passes
    out = validate_patch({"request_expiry_max_hours": "100"}, current={"request_expiry_hours": 48})
    assert out == {"request_expiry_max_hours": "100"}
