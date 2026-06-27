"""Tests for the read endpoints: /api/leaderboard, /api/dashboard, /api/history, /api/profile.

Wire-unit invariant: all credit values are RAW nano-AIU (the frontend `aiu()`
helper divides by NANO_PER_AIU for display). Nano is the wire unit everywhere.
"""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from ctc.accounting.engine import AccountingEngine
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.domain.config import NANO_PER_AIU
from ctc.domain.types import Bucket
from ctc.store.accounting_store import AccountingStore
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db
from api_server import make_app
from ctc.domain.deployment import DeploymentConfig

# Reuse the OAuth stub + login helper from the marketplace test harness.
from test_web_routes import StubOAuth, _giver_user, _login

_DEFAULT_DEPLOYMENT = DeploymentConfig(web_transport="https")


def _build(now=lambda: 1000, shared_pool=False):
    """Build the app and expose store+engine so tests can seed engine state."""
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    config = None
    if shared_pool:
        from ctc.store.settings_store import SettingsStore
        from ctc.domain.settings import EffectiveConfig
        s = SettingsStore(conn)
        s.set_many({"shared_pool_enabled": "on"}, "admin", now())
        config = EffectiveConfig(s)
    engine = AccountingEngine(AccountingStore(conn), config=config)
    engine.start_cycle("c1", "June", 0, 10**12)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10**9)
    app = make_app(store=store, engine=engine, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=now,
                   deployment=_DEFAULT_DEPLOYMENT)
    return app, store, engine


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/leaderboard", "/api/dashboard", "/api/history", "/api/profile"])
async def test_read_endpoints_require_session(path):
    app, _store, _engine = _build()
    async with TestClient(TestServer(app)) as cli:
        assert (await cli.get(path)).status == 401


@pytest.mark.asyncio
async def test_leaderboard_tracks_in_nano():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)                       # octocat, consumer
        octo = store.get_user_by_login("octocat")["id"]
        await cli.post("/api/pat", json={"pat": "ghp_x"})   # octocat -> giver, quota 4000 AIU
        # seed a non-giver consumer "bob"
        store.upsert_user("bob", "bob", "Bob", "consumer", 1000)

        # octocat consumes own credit (giver consumption -> topPro)
        engine.record_consumption("c1", octo, octo, Bucket.OWN, 2 * NANO_PER_AIU, ts=1, allow_overshoot=True)
        # bob consumes from the pool sourced by octocat (octocat donated_live -> generous; bob -> topNoob)
        engine.record_consumption("c1", "bob", octo, Bucket.POOL, 3 * NANO_PER_AIU, ts=2, allow_overshoot=True)

        lb = await (await cli.get("/api/leaderboard")).json()
        assert lb["generous"] == [{"name": "Octo", "value": 3 * NANO_PER_AIU}]
        assert lb["topPro"] == [{"name": "Octo", "value": 2 * NANO_PER_AIU}]
        assert lb["topNoob"] == [{"name": "Bob", "value": 3 * NANO_PER_AIU}]


@pytest.mark.asyncio
async def test_dashboard_shape_and_units():
    app, store, engine = _build(shared_pool=True)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        octo = store.get_user_by_login("octocat")["id"]
        await cli.post("/api/pat", json={"pat": "ghp_x"})
        await cli.patch("/api/settings", json={"pledgedSurplus": 1000 * NANO_PER_AIU})   # pledge 1000 AIU

        d = await (await cli.get("/api/dashboard")).json()
        # exact key set matches DashboardData in web/src/domain/types.ts
        assert set(d) == {
            "pledged", "retained", "rotated", "donatedToNonPat", "donatedThisWeek",
            "fulfillmentRate", "activeGivers", "activeConsumers",
            "openCount", "closedCount", "activity", "leaderboardSnapshot",
        }
        assert d["pledged"] == 1000 * NANO_PER_AIU          # raw nano, not 1000
        assert set(d["leaderboardSnapshot"]) == {"generous", "topConsumers"}


@pytest.mark.asyncio
async def test_active_host_counts_connected_pat_with_pool_off():
    # Pool off (default), giver connects a PAT but has run nothing yet.
    # An "active host" = license connected, so it counts as 1 (not 0).
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "ghp_x"})   # octocat -> giver, no usage
        d = await (await cli.get("/api/dashboard")).json()
        assert d["activeGivers"] == 1


@pytest.mark.asyncio
async def test_profile_giver_in_nano():
    app, store, engine = _build(shared_pool=True)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        octo = store.get_user_by_login("octocat")["id"]
        await cli.post("/api/pat", json={"pat": "ghp_x"})            # quota 4000 AIU
        await cli.patch("/api/settings", json={"pledgedSurplus": 1000 * NANO_PER_AIU})
        engine.record_consumption("c1", octo, octo, Bucket.OWN, 2 * NANO_PER_AIU, ts=1, allow_overshoot=True)

        p = await (await cli.get("/api/profile")).json()
        assert p["user"]["role"] == "giver"
        assert p["user"]["initials"] == "O"
        assert p["totalCredit"] == 4000 * NANO_PER_AIU
        assert p["pledgedSurplus"] == 1000 * NANO_PER_AIU
        # retained = personal_remaining = quota - pledge - own_consumed - granted_out
        assert p["retained"] == (4000 - 1000 - 2) * NANO_PER_AIU
        assert p["allowance"] is None
        assert p["consumed"] == 2 * NANO_PER_AIU


@pytest.mark.asyncio
async def test_profile_consumer_shows_allowance_and_donations():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)                       # octocat stays a consumer (no PAT)
        octo = store.get_user_by_login("octocat")["id"]
        # a giver funds octocat's request -> grant received by octocat
        store.upsert_user("g", "giverlogin", "Giver One", "giver", 1000)
        engine.set_quota("c1", "g", 5000 * NANO_PER_AIU)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 50 * NANO_PER_AIU, "reason": "x", "target": None})).json())["id"]
        engine.fund_request(rid, "g", 40 * NANO_PER_AIU, 5)

        p = await (await cli.get("/api/profile")).json()
        assert p["user"]["role"] == "consumer"
        assert p["totalCredit"] is None
        assert p["pledgedSurplus"] is None
        assert p["retained"] is None
        assert p["allowance"] == 300 * NANO_PER_AIU      # full free allowance, unconsumed
        assert p["donationsReceived"] == 40 * NANO_PER_AIU


@pytest.mark.asyncio
async def test_profile_includes_tier_for_giver():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        octo = store.get_user_by_login("octocat")["id"]
        await cli.post("/api/pat", json={"pat": "ghp_x"})   # octocat -> giver, quota 4000 AIU
        # donate some, consume some so tier is deterministic
        engine.record_consumption("c1", octo, octo, Bucket.OWN, 1 * NANO_PER_AIU, ts=1, allow_overshoot=True)

        p = await (await cli.get("/api/profile")).json()
        assert p["tier"] in {
            "aristocrat", "baron", "bourgeois", "commoner", "peasant", "beggar", "newcomer",
        }
        assert isinstance(p["net"], int)
        assert "netToNext" in p


@pytest.mark.asyncio
async def test_profile_tier_matches_leaderboard_standings():
    """profile tier must equal the tier shown for the same user in leaderboard standings."""
    from ctc.domain.types import GiverCycle
    app, store, engine = _build(shared_pool=True)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        octo = store.get_user_by_login("octocat")["id"]
        await cli.post("/api/pat", json={"pat": "ghp_x"})  # octocat -> giver, quota 4000 AIU

        # Seed a second giver directly (different net so tiers diverge)
        store.upsert_user("g2", "givertwo", "Giver Two", "giver", 1000)
        engine.store.upsert_giver_cycle(GiverCycle("c1", "g2", 1000 * NANO_PER_AIU, 500 * NANO_PER_AIU))

        # g2 draws from the pool (sourced by octocat) → octocat donated_live > 0, g2 pool_consumed_by > 0
        engine.record_consumption("c1", "g2", octo, Bucket.POOL, 200 * NANO_PER_AIU, ts=2, allow_overshoot=True)

        # Get profile tier for octocat
        p = await (await cli.get("/api/profile")).json()
        profile_tier = p["tier"]
        assert profile_tier is not None

        # Get leaderboard standings tier for octocat
        lb = await (await cli.get("/api/leaderboard")).json()
        octo_name = p["user"]["name"]
        standings_entry = next((s for s in lb["standings"] if s["name"] == octo_name), None)
        assert standings_entry is not None, f"{octo_name!r} not found in standings"
        assert profile_tier == standings_entry["tier"], (
            f"profile tier {profile_tier!r} != leaderboard tier {standings_entry['tier']!r}"
        )


@pytest.mark.asyncio
async def test_history_lists_active_cycle():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        hist = await (await cli.get("/api/history")).json()
        assert isinstance(hist, list) and len(hist) == 1
        assert hist[0]["id"] == "c1" and hist[0]["label"] == "June"
        # CycleReport shape sanity
        assert {"pledged", "donated", "toPat", "toNonPat", "fills", "winners"} <= set(hist[0])
