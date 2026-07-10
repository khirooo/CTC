import pytest
from test_web_routes import _make, _login  # reuse harness
from aiohttp.test_utils import TestClient, TestServer
from ctc.domain.config import NANO_PER_AIU


@pytest.mark.asyncio
async def test_settings_consumer_then_giver_after_pat():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        s = await (await cli.get("/api/settings")).json()
        assert s["role"] == "consumer"
        assert "allowance" not in s      # allowance concept removed
        assert s["hasPat"] is False
        # add PAT -> becomes giver with real quota (4000 AIU == 4000 * NANO nano)
        await cli.post("/api/pat", json={"pat": "ghp_x"})
        s2 = await (await cli.get("/api/settings")).json()
        assert s2["role"] == "giver"
        assert s2["hasPat"] is True
        assert s2["totalCredit"] == 4000 * NANO_PER_AIU


@pytest.mark.asyncio
async def test_patch_pledge_persists_in_nano():
    async with TestClient(TestServer(_make(shared_pool=True))) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "ghp_x"})   # quota 4000 AIU
        pledge = 1500 * NANO_PER_AIU
        r = await cli.patch("/api/settings", json={"pledgedSurplus": pledge})
        assert r.status == 200
        assert (await r.json())["pledgedSurplus"] == pledge
        assert (await (await cli.get("/api/settings")).json())["pledgedSurplus"] == pledge


@pytest.mark.asyncio
async def test_patch_pledge_rejected_when_pool_off():
    # Shared pool off (the default) → pledging is locked at 0; any non-zero
    # pledge is rejected with 422.
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "ghp_x"})
        r = await cli.patch("/api/settings", json={"pledgedSurplus": 1500 * NANO_PER_AIU})
        assert r.status == 422
        # a 0 pledge is still accepted (idempotent no-op)
        assert (await cli.patch("/api/settings", json={"pledgedSurplus": 0})).status == 200


@pytest.mark.asyncio
async def test_settings_requires_session():
    async with TestClient(TestServer(_make())) as cli:
        assert (await cli.get("/api/settings")).status == 401


@pytest.mark.asyncio
async def test_settings_carries_pat_health():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        s = await (await cli.get("/api/settings")).json()
        assert s["patHealth"] is None                 # no PAT yet
        await cli.post("/api/pat", json={"pat": "ghp_x"})
        s2 = await (await cli.get("/api/settings")).json()
        assert s2["patHealth"] == "valid"             # upload just validated it
        assert isinstance(s2["patHealthCheckedAt"], int)
