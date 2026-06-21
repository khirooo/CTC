import pytest
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.auth.onboarding import validate_and_store_pat


def _setup():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10_000_000_000)
    store.upsert_user("u1", "octocat", "Octo", "consumer", 1)
    reg = AuthRegistry(store, derive_key("k"))
    return store, eng, reg


async def _user(pat):
    return {"login": "octocat", "quota_reset_date": "2026-07-01",
            "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 1200}}}


@pytest.mark.asyncio
async def test_pat_submit_persists_snapshot_and_returns_quota_fields():
    store, eng, reg = _setup()
    res = await validate_and_store_pat(reg, eng, _user, "c1", "u1", "octocat", "github_pat_X", now=2)
    assert res["entitlement_aiu"] == 4000
    assert res["remaining_aiu"] == 1200
    assert res["reset_date"] == "2026-07-01"
    snap = store.get_giver_quota_snapshot("u1")
    assert snap == {"entitlement": 4000, "remaining_at_submit": 1200, "quota_reset_date": "2026-07-01"}


def test_get_quota_snapshot_none_when_no_pat():
    store, _, _ = _setup()
    assert store.get_giver_quota_snapshot("nobody") is None
