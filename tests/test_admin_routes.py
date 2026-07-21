from dataclasses import replace

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
from ctc.domain.config import config as _env_config, NANO_PER_AIU as N
from ctc.domain.deployment import DeploymentConfig


async def _giver_user(pat):
    return {"login": "octocat",
            "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 4000}}}


async def _pool_app(admins=frozenset({"octocat"}), pool_on=True):
    """App whose engine.config has the shared pool on (the env-config the test
    engine uses ignores the DB settings toggle), so the admin pledge route runs."""
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn),
                           config=replace(_env_config, shared_pool_enabled=pool_on))
    eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10_000)
    return make_app(store=store, engine=eng, registry=reg, sessions=sess,
                    oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                    secret="sek", app_origin="http://app", now=lambda: 1000,
                    admins=admins, deployment=_DEFAULT_DEPLOYMENT)


@pytest.mark.asyncio
async def test_admin_users_requires_admin():
    app = await _client()                       # caller octocat, not admin
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        assert (await cli.get("/api/admin/users")).status == 403


@pytest.mark.asyncio
async def test_admin_users_unauthed_is_401():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        assert (await cli.get("/api/admin/users")).status == 401


@pytest.mark.asyncio
async def test_admin_lists_users_and_reveals_pat_with_audit():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})   # octocat becomes giver
        me = await (await cli.get("/api/me")).json()
        uid = me["user_id"]

        users = await (await cli.get("/api/admin/users")).json()
        row = [u for u in users if u["id"] == uid][0]
        assert row["has_pat"] is True
        assert row["pat_fingerprint"] and "pat" not in row          # never the cleartext
        assert row["quota"] == 4000 * 1_000_000_000

        detail = await (await cli.get(f"/api/admin/users/{uid}")).json()
        assert detail["pat"] == {"fingerprint": row["pat_fingerprint"], "created_at": 1000}
        assert "github_pat_" not in str(detail)            # detail never carries cleartext

        rev = await cli.post(f"/api/admin/users/{uid}/reveal-pat")
        assert rev.status == 200
        assert (await rev.json())["pat"] == "github_pat_SECRET"      # decrypted once


@pytest.mark.asyncio
async def test_reveal_pat_forbidden_over_http_transport():
    # reveal-pat returns cleartext; on a plain-HTTP deployment it must 403.
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10**12)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10**9)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   admins=frozenset({"octocat"}),
                   deployment=DeploymentConfig(web_transport="http"))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        r = await cli.post(f"/api/admin/users/{me['user_id']}/reveal-pat")
        assert r.status == 403


@pytest.mark.asyncio
async def test_reveal_pat_404_when_no_pat():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        me = await (await cli.get("/api/me")).json()       # consumer, no PAT
        r = await cli.post(f"/api/admin/users/{me['user_id']}/reveal-pat")
        assert r.status == 404


@pytest.mark.asyncio
async def test_admin_settings_get_and_patch():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        got = await (await cli.get("/api/admin/settings")).json()
        assert "free_allowance_aiu" not in got   # allowance concept removed
        assert got["default_chip_in_aiu"]["is_override"] is False

        r = await cli.patch("/api/admin/settings", json={"default_chip_in_aiu": 50})
        assert r.status == 200
        body = await r.json()
        assert body["default_chip_in_aiu"] == {"value": 50, "is_override": True}

        # unknown (removed) key rejected
        gone = await cli.patch("/api/admin/settings", json={"free_allowance_aiu": 50})
        assert gone.status == 400

        bad = await cli.patch("/api/admin/settings", json={"default_pledge_pct": 200})
        assert bad.status == 400


@pytest.mark.asyncio
async def test_admin_settings_includes_modes_and_boot():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        r = await cli.get("/api/admin/settings")
        body = await r.json()
        assert body["participants_mode"]["value"] == "givers_only"
        assert body["shared_pool_enabled"]["value"] is False
        assert "web_transport" in body["boot"]
        assert body["boot"]["source"] == "env"


@pytest.mark.asyncio
async def test_admin_can_toggle_pool():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.patch("/api/admin/settings", json={"shared_pool_enabled": "on"})
        r = await cli.get("/api/admin/settings")
        assert (await r.json())["shared_pool_enabled"]["value"] is True


@pytest.mark.asyncio
async def test_admin_routes_giver_credit_to_pool_with_audit():
    app = await _pool_app()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})   # octocat -> giver
        me = await (await cli.get("/api/me")).json()
        uid = me["user_id"]

        # Admin routes the giver's full quota (4000 AIU) into the pool on their behalf.
        r = await cli.post(f"/api/admin/users/{uid}/pledge", json={"pledge": 4000 * N})
        assert r.status == 200
        assert (await r.json())["pledge"] == 4000 * N

        row = [u for u in await (await cli.get("/api/admin/users")).json() if u["id"] == uid][0]
        assert row["pledge"] == 4000 * N                     # reflected in the list
        assert row["pledge_remaining"] == 4000 * N           # nothing drawn yet


@pytest.mark.asyncio
async def test_admin_route_credit_writes_audit_row():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn),
                           config=replace(_env_config, shared_pool_enabled=True))
    eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10_000)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   admins=frozenset({"octocat"}), deployment=_DEFAULT_DEPLOYMENT)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        r = await cli.post(f"/api/admin/users/{me['user_id']}/pledge", json={"pledge": 1000 * N})
        assert r.status == 200
        rows = store.list_admin_audit()
        assert any(a["action"] == "set_pledge" and a["target_user_id"] == me["user_id"]
                   and a["admin_login"] == "octocat" for a in rows)


@pytest.mark.asyncio
async def test_admin_route_credit_requires_admin():
    app = await _pool_app(admins=frozenset())     # caller is not an admin
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        r = await cli.post(f"/api/admin/users/{me['user_id']}/pledge", json={"pledge": 0})
        assert r.status == 403


@pytest.mark.asyncio
async def test_admin_route_credit_409_when_pool_off():
    app = await _pool_app(pool_on=False)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        r = await cli.post(f"/api/admin/users/{me['user_id']}/pledge", json={"pledge": 0})
        assert r.status == 409


@pytest.mark.asyncio
async def test_admin_route_credit_409_for_non_giver():
    app = await _pool_app()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        me = await (await cli.get("/api/me")).json()      # consumer, never connected a PAT
        r = await cli.post(f"/api/admin/users/{me['user_id']}/pledge", json={"pledge": 0})
        assert r.status == 409


@pytest.mark.asyncio
async def test_admin_route_credit_422_over_quota():
    app = await _pool_app()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        r = await cli.post(f"/api/admin/users/{me['user_id']}/pledge", json={"pledge": 999_999 * N})
        assert r.status == 422


@pytest.mark.asyncio
async def test_admin_route_credit_400_bad_body():
    app = await _pool_app()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        r = await cli.post(f"/api/admin/users/{me['user_id']}/pledge", json={"pledge": "lots"})
        assert r.status == 400


@pytest.mark.asyncio
async def test_admin_users_carry_pat_health():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "github_pat_SECRET"})
        me = await (await cli.get("/api/me")).json()
        uid = me["user_id"]

        users = await (await cli.get("/api/admin/users")).json()
        row = [u for u in users if u["id"] == uid][0]
        assert row["pat_health"] == "valid"           # upload just validated it
        assert row["pat_health_error"] is None

        detail = await (await cli.get(f"/api/admin/users/{uid}")).json()
        assert detail["pat_health"] == "valid"

        # a user with no PAT shows no health at all
        no_pat = [u for u in users if u["id"] != uid]
        assert all(u["pat_health"] is None for u in no_pat)
