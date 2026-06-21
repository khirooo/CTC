import pytest
from ctc.auth.crypto import derive_key
from ctc.auth.onboarding import validate_and_store_pat, PatIdentityMismatch, PatInvalid
from ctc.auth.registry import AuthRegistry
from ctc.accounting.engine import AccountingEngine
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


def _setup():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn))
    eng.start_cycle("c1", "June", 0, 10_000_000_000)
    store.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    reg = AuthRegistry(store, derive_key("k"))
    return store, eng, reg


async def _user_ok(pat):
    return {"login": "octocat", "quota_snapshots": {"premium_interactions": {"entitlement": 4000}}}
async def _user_partial(pat):
    # entitlement 4000 but only 1200 left this cycle
    return {"login": "octocat",
            "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 1200}}}
async def _user_mismatch(pat):
    return {"login": "someone-else", "quota_snapshots": {"premium_interactions": {"entitlement": 4000}}}
async def _user_403(pat):
    raise PatInvalid("403")


@pytest.mark.asyncio
async def test_valid_pat_stored_and_quota_set():
    store, eng, reg = _setup()
    res = await validate_and_store_pat(reg, eng, _user_ok, "c1", "u1", "octocat", "github_pat_X", now=2)
    assert res["quota_aiu"] == 4000
    assert reg.pat_for("u1") == "github_pat_X"
    assert store.get_user_by_id("u1")["role"] == "giver"
    assert eng.personal_remaining("c1", "u1") == 4000 * 1_000_000_000  # quota in nano, no pledge yet


@pytest.mark.asyncio
async def test_quota_sized_by_remaining_not_entitlement():
    store, eng, reg = _setup()
    res = await validate_and_store_pat(reg, eng, _user_partial, "c1", "u1", "octocat", "github_pat_X", now=2)
    assert res["quota_aiu"] == 1200  # remaining, not the 4000 entitlement
    assert eng.personal_remaining("c1", "u1") == 1200 * 1_000_000_000


@pytest.mark.asyncio
async def test_identity_mismatch_rejected():
    store, eng, reg = _setup()
    with pytest.raises(PatIdentityMismatch):
        await validate_and_store_pat(reg, eng, _user_mismatch, "c1", "u1", "octocat", "github_pat_X", now=2)
    assert reg.pat_for("u1") is None  # nothing stored on rejection


@pytest.mark.asyncio
async def test_invalid_pat_rejected():
    store, eng, reg = _setup()
    with pytest.raises(PatInvalid):
        await validate_and_store_pat(reg, eng, _user_403, "c1", "u1", "octocat", "bad", now=2)
