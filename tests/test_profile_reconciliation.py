import pytest
from aiohttp.test_utils import TestClient, TestServer
from tests.test_api_server import _client, _login, StubOAuth, _DEFAULT_DEPLOYMENT
from api_server import make_app
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.accounting.engine import AccountingEngine
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db
from ctc.domain.config import NANO_PER_AIU as N


async def _user_4000_1200(pat):
    return {"login": "octocat", "quota_reset_date": "2026-07-01",
            "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 1200}}}


async def _client_with_engine(http_get_user):
    """Like _client() but returns (app, engine, auth_store) so tests can
    inspect / mutate accounting state directly (e.g. drive reconcile_giver
    without going through a live HTTP round-trip)."""
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10_000)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=http_get_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   deployment=_DEFAULT_DEPLOYMENT)
    return app, eng, store


@pytest.mark.asyncio
async def test_giver_profile_segments_reconcile_behind_proxy():
    # entitlement 4000, live remaining 1200 → total charged 2800. CTC tracked nothing
    # (no pool/grant consumption), so all 2800 is the giver's own use incl behind-proxy.
    app = await _client(http_get_user=_user_4000_1200)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_X"})   # becomes giver, quota=1200 AIU
        p = await (await cli.get("/api/profile")).json()
        assert p["unlimited"] is False and p["quotaStale"] is False
        assert p["entitlement"] == 4000 * N
        assert p["used"] == 2800 * N            # (4000-1200) - 0 - 0; pledge doesn't affect used
        assert p["donated"] == 0
        assert p["pledged"] == 120 * N          # default 10% of 1200 remaining auto-pledged
        assert p["left"] == (4000 - 2800 - 120) * N   # 1080
        assert p["resetDate"] == "2026-07-01"


@pytest.mark.asyncio
async def test_consumer_profile_has_no_allowance_fields():
    app = await _client()   # default identity, no PAT → consumer
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        p = await (await cli.get("/api/profile")).json()
        # the free-allowance concept is gone from the wire contract
        assert "allowanceMax" not in p and "allowanceUsed" not in p and "allowance" not in p
        assert p["donationsReceived"] == 0
        assert p["donationsReceivedFromPool"] == 0
        assert p["resetDate"] is not None       # from cycle end


@pytest.mark.asyncio
async def test_connect_seeds_entitlement_ceiling_and_books_prior_burn():
    app = await _client(http_get_user=_user_4000_1200)  # ent 4000, remaining 1200
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_X"})
        p = await (await cli.get("/api/profile")).json()
        # quota is the entitlement ceiling; the 2800 already burned before connect
        # is attributed to the owner as their own use.
        assert p["totalCredit"] == 4000 * N      # gc.quota == entitlement
        assert p["used"] == 2800 * N
        assert p["left"] == (4000 - 2800 - 120) * N
        assert p["pledged"] == 120 * N            # still 10% of remaining (1200)


@pytest.mark.asyncio
async def test_leaderboard_consumption_matches_profile_used():
    app = await _client(http_get_user=_user_4000_1200)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_X"})
        await cli.get("/api/profile")                       # triggers reconcile
        lb = await (await cli.get("/api/leaderboard")).json()
        me = next((u for u in lb["topPro"] if u["value"] > 0), None)
        assert me is not None and me["value"] == 2800 * N    # bypass now visible


@pytest.mark.asyncio
async def test_giver_profile_falls_back_to_snapshot_when_live_fetch_fails():
    calls = {"n": 0}
    async def flaky(pat):
        calls["n"] += 1
        if calls["n"] == 1:   # PAT submit succeeds (snapshot persisted)
            return {"login": "octocat", "quota_reset_date": "2026-07-01",
                    "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 1200}}}
        raise RuntimeError("ghe down")          # later profile live-fetch fails
    app = await _client(http_get_user=flaky)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_X"})
        p = await (await cli.get("/api/profile")).json()
        assert p["quotaStale"] is True
        assert p["entitlement"] == 4000 * N     # from persisted snapshot
        assert p["resetDate"] == "2026-07-01"


@pytest.mark.asyncio
async def test_used_is_events_sourced_not_stale_snapshot():
    """Regression: on a stale profile load, `used` must come from events
    (own_consumed + bypass_consumed), NOT from the submit-time snapshot formula
    (E - R) - pledged_consumed - donated_consumed.

    Distinguishing scenario:
    - PAT submit: E=4000, R=1200 → onboarding reconcile books bypass=2800,
      snapshot stores remaining_at_submit=1200.
    - Intermediate reconcile (simulates what a successful live profile fetch
      with remaining=1000 would do): books +200 more bypass → bypass=3000.
    - Profile GET (stale — live fetch raises): snapshot E/R = 4000/1200.
      NEW code: used = own(0) + bypass(3000) = 3000 N  ← correct
      OLD code: used = (4000 - 1200) N - 0 - 0 = 2800 N  ← wrong (stale snapshot)
    """
    calls = {"n": 0}

    async def stub(pat):
        calls["n"] += 1
        if calls["n"] == 1:   # call 1: PAT submit — snapshot persisted at R=1200
            return {"login": "octocat", "quota_reset_date": "2026-07-01",
                    "quota_snapshots": {"premium_interactions":
                                        {"entitlement": 4000, "remaining": 1200}}}
        raise RuntimeError("ghe down")  # call 2+: live-quota fetch fails → stale path

    app, eng, store = await _client_with_engine(http_get_user=stub)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_X"})
        # After PAT submit: bypass_consumed = 2800 N (onboarding reconcile).
        # Snapshot remaining_at_submit = 1200 (stored, never updated).

        # Simulate a later real-world event: 200 more AIU burned since connect,
        # reducing remaining from 1200 → 1000.  A successful live profile fetch
        # would have called engine.reconcile_giver with remaining=1000 and booked
        # the delta.  We do it directly so the events table reflects reality even
        # though the subsequent profile GET will be stale (live fetch raises).
        # Real call count: stub is called once during PAT submit (direct call in
        # validate_and_store_pat); the LiveQuotaCache is separate and not pre-warm
        # by the submit, so the FIRST profile GET hits the cache cold → call 2 →
        # raises → stale.  We therefore drive the intermediate reconcile manually
        # to avoid coupling the test to the cache TTL.
        uid = store.get_user_by_login("octocat")["id"]
        # immediate=True books the delta without the two-observation debounce (the
        # onboarding baseline is 0, so this mirrors a confirmed live reconcile).
        eng.reconcile_giver("c1", uid, {"entitlement": 4000, "remaining": 1000},
                            ts=500, immediate=True)
        # Now bypass_consumed = 3000 N in the events table.

        # Profile GET: live fetch is now call 2 → raises → stale path activated.
        p = await (await cli.get("/api/profile")).json()

        # Stale-path assertions
        assert calls["n"] == 2, f"expected 2 stub calls (submit + stale GET), got {calls['n']}"
        assert p["quotaStale"] is True
        assert p["entitlement"] == 4000 * N   # from snapshot
        # KEY assertion — this is what distinguishes the two implementations:
        # events say 3000, snapshot formula says (4000-1200)=2800.
        assert p["used"] == 3000 * N, (
            f"used={p['used']} expected {3000 * N}; "
            "old formula would yield 2800 N from stale snapshot"
        )


@pytest.mark.asyncio
async def test_profile_exposes_remaining_segment_fields():
    app = await _client(http_get_user=_user_4000_1200)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_X"})
        p = await (await cli.get("/api/profile")).json()
        assert p["donatedRemaining"] == 0
        assert p["pledgedRemaining"] == 120 * N   # full pledge, nothing consumed
