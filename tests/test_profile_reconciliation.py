import pytest
from aiohttp.test_utils import TestClient, TestServer
from tests.test_api_server import _client, _login
from ctc.domain.config import NANO_PER_AIU as N


async def _user_4000_1200(pat):
    return {"login": "octocat", "quota_reset_date": "2026-07-01",
            "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 1200}}}


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
async def test_consumer_profile_has_allowance_segments():
    app = await _client()   # default identity, no PAT → consumer
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        p = await (await cli.get("/api/profile")).json()
        assert p["allowanceMax"] is not None
        assert p["allowanceUsed"] == 0
        assert p["allowanceLeft"] == p["allowanceMax"]
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
