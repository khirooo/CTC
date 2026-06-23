import pytest
from ctc.store.db import connect, init_db
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig, effective_view, validate_patch


def _ec():
    conn = connect(":memory:")
    init_db(conn)
    store = SettingsStore(conn)
    return EffectiveConfig(store), store


def test_mode_defaults_are_target_shape():
    ec, _ = _ec()
    assert ec.participants_mode == "givers_only"
    assert ec.shared_pool_enabled is False


def test_pool_off_forces_default_pledge_zero():
    ec, _ = _ec()
    assert ec.shared_pool_enabled is False
    assert ec.default_pledge_pct == 0


def test_db_override_wins(monkeypatch):
    ec, store = _ec()
    store.set_many({"shared_pool_enabled": "on",
                    "participants_mode": "givers_and_consumers"}, "admin", 1)
    assert ec.shared_pool_enabled is True
    assert ec.participants_mode == "givers_and_consumers"


def test_validate_patch_accepts_modes():
    out = validate_patch({"participants_mode": "givers_only",
                          "shared_pool_enabled": "off"})
    assert out["participants_mode"] == "givers_only"
    assert out["shared_pool_enabled"] == "off"


@pytest.mark.parametrize("patch", [
    {"participants_mode": "nope"},
    {"shared_pool_enabled": "maybe"},
])
def test_validate_patch_rejects_bad_modes(patch):
    with pytest.raises(ValueError):
        validate_patch(patch)


def test_effective_view_includes_modes():
    ec, store = _ec()
    view = effective_view(ec, store)
    assert view["participants_mode"]["value"] == "givers_only"
    assert view["shared_pool_enabled"]["value"] is False
