import pytest
from aiohttp.test_utils import TestClient, TestServer
from tests.test_api_server import _client, _login


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
        assert got["free_allowance_aiu"]["is_override"] is False

        r = await cli.patch("/api/admin/settings", json={"free_allowance_aiu": 50})
        assert r.status == 200
        body = await r.json()
        assert body["free_allowance_aiu"] == {"value": 50, "is_override": True}

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
        assert body["boot"]["auth_mode"] in ("email", "ghe_oauth")
        assert body["boot"]["source"] == "env"


@pytest.mark.asyncio
async def test_admin_can_toggle_pool():
    app = await _client(admins=frozenset({"octocat"}))
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.patch("/api/admin/settings", json={"shared_pool_enabled": "on"})
        r = await cli.get("/api/admin/settings")
        assert (await r.json())["shared_pool_enabled"]["value"] is True
