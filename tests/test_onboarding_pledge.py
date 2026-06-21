import pytest
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig
from ctc.domain.config import NANO_PER_AIU
from ctc.accounting.engine import AccountingEngine
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.auth.onboarding import validate_and_store_pat


async def _http_get_user(pat):
    return {"login": "octo", "quota_snapshots": {"premium_interactions": {"entitlement": 1000}}}


@pytest.mark.asyncio
async def test_onboarding_seeds_pledge_from_default_pct():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn); s.set_many({"default_pledge_pct": "40"}, "admin", 1)
    ec = EffectiveConfig(s)
    eng = AccountingEngine(AccountingStore(conn), config=ec); eng.start_cycle("c1", "J", 0, 99 * 10**12)
    reg = AuthRegistry(AuthStore(conn), derive_key("k"))
    AuthStore(conn).upsert_user("u1", "octo", "Octo", "consumer", 0)
    await validate_and_store_pat(reg, eng, _http_get_user, "c1", "u1", "octo",
                                 "github_pat_X", 10, effective_config=ec)
    gc = eng.store.get_giver_cycle("c1", "u1")
    assert gc.quota == 1000 * NANO_PER_AIU
    assert gc.pledge == 400 * NANO_PER_AIU      # 40% of 1000


@pytest.mark.asyncio
async def test_onboarding_pledge_zero_when_pct_zero():
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn); s.set_many({"default_pledge_pct": "0"}, "admin", 1)  # explicit 0
    ec = EffectiveConfig(s)
    eng = AccountingEngine(AccountingStore(conn), config=ec); eng.start_cycle("c1", "J", 0, 99 * 10**12)
    reg = AuthRegistry(AuthStore(conn), derive_key("k"))
    AuthStore(conn).upsert_user("u1", "octo", "Octo", "consumer", 0)
    await validate_and_store_pat(reg, eng, _http_get_user, "c1", "u1", "octo",
                                 "github_pat_X", 10, effective_config=ec)
    gc = eng.store.get_giver_cycle("c1", "u1")
    assert gc.pledge == 0


@pytest.mark.asyncio
async def test_onboarding_seeds_10pct_by_default():
    # No override set → falls back to the env Config default (now 10%).
    conn = connect(":memory:"); init_db(conn)
    ec = EffectiveConfig(SettingsStore(conn))
    eng = AccountingEngine(AccountingStore(conn), config=ec); eng.start_cycle("c1", "J", 0, 99 * 10**12)
    reg = AuthRegistry(AuthStore(conn), derive_key("k"))
    AuthStore(conn).upsert_user("u1", "octo", "Octo", "consumer", 0)
    await validate_and_store_pat(reg, eng, _http_get_user, "c1", "u1", "octo",
                                 "github_pat_X", 10, effective_config=ec)
    gc = eng.store.get_giver_cycle("c1", "u1")
    assert gc.pledge == 100 * NANO_PER_AIU      # 10% of 1000 remaining


@pytest.mark.asyncio
async def test_resubmit_pat_does_not_overwrite_giver_pledge():
    """A returning giver who changed their pledge keeps it on PAT re-submission."""
    conn = connect(":memory:"); init_db(conn)
    s = SettingsStore(conn); s.set_many({"default_pledge_pct": "40"}, "admin", 1)
    ec = EffectiveConfig(s)
    eng = AccountingEngine(AccountingStore(conn), config=ec); eng.start_cycle("c1", "J", 0, 99 * 10**12)
    reg = AuthRegistry(AuthStore(conn), derive_key("k"))
    AuthStore(conn).upsert_user("u1", "octo", "Octo", "consumer", 0)
    # First onboard — seeds pledge at 40% = 400 AIU
    await validate_and_store_pat(reg, eng, _http_get_user, "c1", "u1", "octo",
                                 "github_pat_X", 10, effective_config=ec)
    # Giver manually lowers their pledge to 100 AIU
    eng.set_pledge("c1", "u1", 100 * NANO_PER_AIU)
    gc = eng.store.get_giver_cycle("c1", "u1")
    assert gc.pledge == 100 * NANO_PER_AIU
    # Giver re-submits PAT (e.g. quota refresh) — pledge must NOT be re-seeded to 400
    await validate_and_store_pat(reg, eng, _http_get_user, "c1", "u1", "octo",
                                 "github_pat_X", 20, effective_config=ec)
    gc = eng.store.get_giver_cycle("c1", "u1")
    assert gc.pledge == 100 * NANO_PER_AIU  # still the giver's own choice
