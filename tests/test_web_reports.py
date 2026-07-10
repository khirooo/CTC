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
        assert lb["generous"] == [{"userId": octo, "name": "Octo", "value": 3 * NANO_PER_AIU}]
        assert lb["topPro"] == [{"userId": octo, "name": "Octo", "value": 2 * NANO_PER_AIU}]
        bob_id = store.get_user_by_login("bob")["id"]
        assert lb["topNoob"] == [{"userId": bob_id, "name": "Bob", "value": 3 * NANO_PER_AIU}]


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
            "fulfillmentRate", "activeGivers", "activeConsumers", "poolAvailable",
            "openCount", "closedCount", "activity", "leaderboardSnapshot",
            "cycleLabel", "cycleNumber", "resetDate", "daysLeft",
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
        assert "allowance" not in p
        assert p["consumed"] == 2 * NANO_PER_AIU


@pytest.mark.asyncio
async def test_profile_consumer_shows_donations():
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
        assert "allowance" not in p                      # allowance concept removed
        assert p["donationsReceived"] == 40 * NANO_PER_AIU
        assert p["donationsReceivedFromPool"] == 0       # personal chip-in, not a pool fill


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


@pytest.mark.asyncio
async def test_search_users_blank_q_returns_empty():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        store.upsert_user("u1", "alice", "Alice Smith", "consumer", 1000)
        store.upsert_user("u2", "bobdev", "Bob Jones", "giver", 1001)

        r = await cli.get("/api/users/search?q=")
        assert r.status == 200
        body = await r.json()
        assert body == {"users": []}


@pytest.mark.asyncio
async def test_search_users_matches_name_and_login_case_insensitive():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        store.upsert_user("u1", "alice", "Alice Smith", "consumer", 1000)
        store.upsert_user("u2", "bobdev", "Bob Jones", "giver", 1001)

        # case-insensitive name match
        r = await cli.get("/api/users/search?q=ALICE")
        assert r.status == 200
        body = await r.json()
        assert len(body["users"]) == 1
        hit = body["users"][0]
        assert set(hit.keys()) == {"id", "login", "name", "initials", "role"}
        assert hit["login"] == "alice"
        assert hit["name"] == "Alice Smith"
        assert hit["initials"] == "AS"
        assert hit["role"] == "consumer"

        # login match
        r2 = await cli.get("/api/users/search?q=bobdev")
        body2 = await r2.json()
        assert len(body2["users"]) == 1
        assert body2["users"][0]["login"] == "bobdev"

        # substring matching both name and login
        r3 = await cli.get("/api/users/search?q=ob")
        body3 = await r3.json()
        logins = {u["login"] for u in body3["users"]}
        # "bobdev" has "ob" in login; "Bob Jones" has "ob" in name
        assert "bobdev" in logins


@pytest.mark.asyncio
async def test_search_users_caps_at_8():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        for i in range(10):
            store.upsert_user(f"u{i}", f"user{i}", f"Alpha User {i}", "consumer", 1000 + i)

        r = await cli.get("/api/users/search?q=alpha")
        body = await r.json()
        assert len(body["users"]) <= 8


@pytest.mark.asyncio
async def test_search_users_requires_session():
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        # no login
        r = await cli.get("/api/users/search?q=alice")
        assert r.status == 401


# ---------------------------------------------------------------------------
# Public profile endpoint  GET /api/users/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_public_profile_giver_exact_keys_and_matches_leaderboard():
    """Public profile has EXACTLY the allowed keys, no sensitive fields, and
    tier/net must match the leaderboard standings entry for the same user."""
    from ctc.domain.types import Bucket
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)  # logs in as octocat (consumer by default)
        octo = store.get_user_by_login("octocat")["id"]
        await cli.post("/api/pat", json={"pat": "ghp_x"})  # octocat -> giver, quota 4000 AIU
        # give octocat some usage so tier is deterministic
        engine.record_consumption("c1", octo, octo, Bucket.OWN, 1 * NANO_PER_AIU, ts=1, allow_overshoot=True)

        r = await cli.get(f"/api/users/{octo}")
        assert r.status == 200
        body = await r.json()

        # exact public field set — no more, no less
        assert set(body.keys()) == {"id", "name", "login", "initials", "role",
                                    "tier", "net", "donated", "donationsMade"}

        # deny-list: none of these may ever appear
        for forbidden in ("totalCredit", "pledgedSurplus", "entitlement", "remaining",
                          "allowance", "allowanceMax", "allowanceLeft", "resetDate", "email"):
            assert forbidden not in body, f"forbidden field {forbidden!r} present in public profile"

        # tier and net must match the leaderboard standings for the same user
        lb = await (await cli.get("/api/leaderboard")).json()
        entry = next((s for s in lb["standings"] if s["userId"] == octo), None)
        assert entry is not None, f"user {octo!r} not in leaderboard standings"
        assert body["tier"] == entry["tier"]
        assert body["net"] == entry["net"]


@pytest.mark.asyncio
async def test_public_profile_unknown_id_404():
    """Requesting a non-existent user id returns 404."""
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        r = await cli.get("/api/users/does-not-exist")
        assert r.status == 404


@pytest.mark.asyncio
async def test_public_profile_consumer_has_null_reputation():
    """Consumer profile is served but tier/net/donated/donationsMade are null."""
    app, store, engine = _build()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)  # octocat stays a consumer (no PAT)
        octo = store.get_user_by_login("octocat")["id"]

        r = await cli.get(f"/api/users/{octo}")
        assert r.status == 200
        body = await r.json()

        assert set(body.keys()) == {"id", "name", "login", "initials", "role",
                                    "tier", "net", "donated", "donationsMade"}
        assert body["tier"] is None
        assert body["net"] is None
        assert body["donated"] is None
        assert body["donationsMade"] is None
