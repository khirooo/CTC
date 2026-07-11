import pytest
from urllib.parse import urlparse, parse_qs
from aiohttp.test_utils import TestClient, TestServer

from api_server import make_app
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.accounting.engine import AccountingEngine
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db
from ctc.domain.deployment import DeploymentConfig
from ctc.domain.types import Role
from ctc.domain.config import NANO_PER_AIU as N

_DEFAULT_DEPLOYMENT = DeploymentConfig(web_transport="https")


class StubOAuth:
    def authorize_url(self, state): return f"https://ghe/authorize?state={state}"
    async def exchange_code(self, code): return "gho_TEST"
    async def fetch_identity(self, token): return {"login": "octocat", "name": "Octo"}


async def _giver_user(pat):
    # remaining == entitlement: fresh cycle, nothing spent yet
    return {"login": "octocat", "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 4000}}}


def _make(now=lambda: 1000, shared_pool=False):
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    config = None
    if shared_pool:
        from ctc.store.settings_store import SettingsStore
        from ctc.domain.settings import EffectiveConfig
        s = SettingsStore(conn)
        s.set_many({"shared_pool_enabled": "on"}, "admin", now())
        config = EffectiveConfig(s)
    eng = AccountingEngine(AccountingStore(conn), config=config)
    eng.start_cycle("c1", "June", 0, 10**12)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10**9)  # large so clock-advancing tests keep the session
    return make_app(store=store, engine=eng, registry=reg, sessions=sess,
                    oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                    secret="sek", app_origin="http://app", now=now,
                    deployment=_DEFAULT_DEPLOYMENT)


async def _login(cli):
    r = await cli.get("/auth/login", allow_redirects=False)
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    await cli.get(f"/auth/callback?code=abc&state={state}", allow_redirects=False)


@pytest.mark.asyncio
async def test_create_list_donate_lifecycle_in_aiu():
    # Build inline so we can seed a request owned by a DIFFERENT user (you can't
    # fund your own request, so the donor and requester must differ).
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10**12)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10**9)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   deployment=_DEFAULT_DEPLOYMENT)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)                         # logged in as octocat (consumer by default)
        # consumer creates a 100-AIU request — it's their own
        body = await (await cli.post("/api/requests", json={"amountNeeded": 100, "reason": "ran out", "target": None})).json()
        rid = body["id"]
        assert body["requesterName"] == "Octo" and body["requesterRole"] == "noob"
        assert body["amountNeeded"] == 100 and body["amountFunded"] == 0 and body["isOwn"] is True

        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert [x["id"] for x in lst["requests"]] == [rid]
        assert lst["counts"] == {"all": 1, "pro": 0, "noob": 1}

        # a different user's open request (seeded directly)
        foreign = eng.create_request("c1", "other_uid", Role.CONSUMER, 100, "help", None, 1000, 10**12)

        # become a giver by adding a PAT (sets real quota = 4000 AIU)
        await cli.post("/api/pat", json={"pat": "ghp_x"})
        # cannot fund your OWN request
        assert (await cli.post(f"/api/requests/{rid}/donate", json={"amount": 100})).status == 422
        # funds the foreign request → fulfilled
        d = await (await cli.post(f"/api/requests/{foreign.id}/donate", json={"amount": 100})).json()
        assert d["amountFunded"] == 100 and d["status"] == "fulfilled" and d["donorCount"] == 1


@pytest.mark.asyncio
async def test_donate_requires_session():
    async with TestClient(TestServer(_make())) as cli:
        r = await cli.post("/api/requests/x/donate", json={"amount": 5})
        assert r.status == 401


@pytest.mark.asyncio
async def test_create_request_rejects_invalid_amount_and_reason():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        # amount must be > 0
        assert (await cli.post("/api/requests",
                json={"amountNeeded": 0, "reason": "x", "target": None})).status == 422
        # amount must be <= 10,000 AIU
        assert (await cli.post("/api/requests",
                json={"amountNeeded": 10_000 * N + 1, "reason": "x", "target": None})).status == 422
        # reason must be non-empty
        r = await cli.post("/api/requests",
                           json={"amountNeeded": 10, "reason": "", "target": None})
        assert r.status == 422
        body = await r.json()
        assert "error" in body and "message" in body
        # reason too long
        assert (await cli.post("/api/requests",
                json={"amountNeeded": 10, "reason": "z" * 501, "target": None})).status == 422


@pytest.mark.asyncio
async def test_donate_rejects_non_positive_amount():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 50, "reason": "x", "target": None})).json())["id"]
        assert (await cli.post(f"/api/requests/{rid}/donate", json={"amount": 0})).status == 422


@pytest.mark.asyncio
async def test_get_public_user_unknown_is_404_middleware_shape():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        r = await cli.get("/api/users/does-not-exist")
        assert r.status == 404
        body = await r.json()
        assert "error" in body and "message" in body


@pytest.mark.asyncio
async def test_revoke_pat_full_disconnect():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10**12)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10**9)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   deployment=_DEFAULT_DEPLOYMENT)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        await cli.post("/api/pat", json={"pat": "ghp_x"})       # become a giver
        uid = store.get_user_by_login("octocat")["id"]
        assert reg.pat_for(uid) == "ghp_x"
        me = await (await cli.get("/api/me")).json()
        assert me["role"] == "giver" and me["has_pat"] is True

        r = await cli.delete("/api/pat")
        assert r.status == 204

        # PAT gone, role reverted, cycle credit zeroed
        assert reg.pat_for(uid) is None
        gc = eng.store.get_giver_cycle("c1", uid)
        assert gc.quota == 0 and gc.pledge == 0
        me = await (await cli.get("/api/me")).json()
        assert me["role"] == "consumer" and me["has_pat"] is False


@pytest.mark.asyncio
async def test_revoke_pat_idempotent_without_pat():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)                                       # consumer, no PAT
        r = await cli.delete("/api/pat")
        assert r.status == 204
        me = await (await cli.get("/api/me")).json()
        assert me["role"] == "consumer" and me["has_pat"] is False


@pytest.mark.asyncio
async def test_revoke_pat_requires_session():
    async with TestClient(TestServer(_make())) as cli:
        assert (await cli.delete("/api/pat")).status == 401


@pytest.mark.asyncio
async def test_giver_without_pat_cannot_fund():
    async with TestClient(TestServer(_make())) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests", json={"amountNeeded": 50, "reason": "x", "target": None})).json())["id"]
        # no PAT -> no quota -> personal_remaining 0 -> 422
        r = await cli.post(f"/api/requests/{rid}/donate", json={"amount": 10})
        assert r.status == 422


@pytest.mark.asyncio
async def test_list_requires_session():
    async with TestClient(TestServer(_make())) as cli:
        assert (await cli.get("/api/requests")).status == 401


@pytest.mark.asyncio
async def test_request_expires_after_window():
    # Timestamps are seconds; a request expires request_expiry_hours (24h) after creation.
    clock = [1000]
    async with TestClient(TestServer(_make(now=lambda: clock[0]))) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 10, "reason": "x", "target": None})).json())["id"]
        clock[0] += 24 * 3600 + 1            # past the expiry window
        lst = await (await cli.get("/api/requests?filter=all")).json()
        req = next(r for r in lst["requests"] if r["id"] == rid)
        assert req["status"] == "expired"


@pytest.mark.asyncio
async def test_request_honors_chosen_expiry_hours():
    async with TestClient(TestServer(_make(now=lambda: 1000))) as cli:
        await _login(cli)
        await cli.post("/api/requests",
                       json={"amountNeeded": 10, "reason": "x", "target": None, "expiryHours": 6})
        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert lst["requests"][0]["expiresAt"] == 1000 + 6 * 3600


@pytest.mark.asyncio
async def test_request_defaults_to_24h_when_expiry_omitted():
    async with TestClient(TestServer(_make(now=lambda: 1000))) as cli:
        await _login(cli)
        await cli.post("/api/requests",
                       json={"amountNeeded": 10, "reason": "x", "target": None})
        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert lst["requests"][0]["expiresAt"] == 1000 + 24 * 3600


@pytest.mark.asyncio
async def test_request_expiry_capped_to_cycle_end():
    # Cycle ends at 10**12; create 1h before end with a 24h request -> capped to cycle end.
    end = 10**12
    async with TestClient(TestServer(_make(now=lambda: end - 3600))) as cli:
        await _login(cli)
        await cli.post("/api/requests",
                       json={"amountNeeded": 10, "reason": "x", "target": None, "expiryHours": 24})
        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert lst["requests"][0]["expiresAt"] == end


@pytest.mark.asyncio
async def test_request_rejects_out_of_range_expiry():
    async with TestClient(TestServer(_make(now=lambda: 1000))) as cli:
        await _login(cli)
        r0 = await cli.post("/api/requests",
                            json={"amountNeeded": 10, "reason": "x", "target": None, "expiryHours": 0})
        assert r0.status == 422
        rbig = await cli.post("/api/requests",
                              json={"amountNeeded": 10, "reason": "x", "target": None, "expiryHours": 200})
        assert rbig.status == 422
        body = await rbig.json()
        assert "error" in body and "message" in body


# ---------------------------------------------------------------------------
# DELETE /api/requests/{id} + POST /api/requests/{id}/pool-fund
# ---------------------------------------------------------------------------

def _make_seeded(shared_pool=False):
    """_make + direct handles on (app, store, eng) for seeding."""
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    config = None
    if shared_pool:
        from ctc.store.settings_store import SettingsStore
        from ctc.domain.settings import EffectiveConfig
        s = SettingsStore(conn)
        s.set_many({"shared_pool_enabled": "on"}, "admin", 1000)
        config = EffectiveConfig(s)
    eng = AccountingEngine(AccountingStore(conn), config=config)
    eng.start_cycle("c1", "June", 0, 10**12)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10**9)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=_giver_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   deployment=_DEFAULT_DEPLOYMENT)
    return app, store, eng


@pytest.mark.asyncio
async def test_delete_request_owner_lifecycle():
    app, store, eng = _make_seeded()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 100, "reason": "x", "target": None})).json())["id"]
        # someone else's request → 403
        foreign = eng.create_request("c1", "other_uid", Role.CONSUMER, 100, "help", None, 1000, 10**12)
        assert (await cli.delete(f"/api/requests/{foreign.id}")).status == 403
        # unknown → 404
        assert (await cli.delete("/api/requests/nope")).status == 404
        # own → 204, then hidden from the list
        assert (await cli.delete(f"/api/requests/{rid}")).status == 204
        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert [x["id"] for x in lst["requests"]] == [foreign.id]


@pytest.mark.asyncio
async def test_delete_fulfilled_request_conflicts():
    app, store, eng = _make_seeded()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 100, "reason": "x", "target": None})).json())["id"]
        store.upsert_user("g", "giverlogin", "Giver One", "giver", 1000)
        eng.set_quota("c1", "g", 5000)
        eng.fund_request(rid, "g", 100, 5)          # fully funds → fulfilled
        assert (await cli.delete(f"/api/requests/{rid}")).status == 409


@pytest.mark.asyncio
async def test_pool_fund_endpoint_own_request():
    app, store, eng = _make_seeded(shared_pool=True)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        # a pledging giver seeds the pool
        store.upsert_user("g", "giverlogin", "Giver One", "giver", 1000)
        eng.set_quota("c1", "g", 5000)
        eng.set_pledge("c1", "g", 500)

        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert lst["poolEnabled"] is True and lst["poolAvailable"] == 500

        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 300, "reason": "x", "target": None})).json())["id"]
        # requester fills their OWN request from the pool
        body = await (await cli.post(f"/api/requests/{rid}/pool-fund", json={"amount": 200})).json()
        assert body["amountFunded"] == 200 and body["poolFunded"] == 200
        assert body["status"] == "partially_funded" and body["donorCount"] == 0

        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert lst["poolAvailable"] == 300

        # cannot pool-fund someone else's request → 403
        foreign = eng.create_request("c1", "other_uid", Role.CONSUMER, 100, "help", None, 1000, 10**12)
        assert (await cli.post(f"/api/requests/{foreign.id}/pool-fund", json={"amount": 50})).status == 403
        assert (await (await cli.get("/api/requests?filter=all")).json())["poolAvailable"] == 300  # untouched

        # over-draw is capped by remaining need; a dry/over request 422s
        await cli.post(f"/api/requests/{rid}/pool-fund", json={"amount": 999})
        r = await cli.post(f"/api/requests/{rid}/pool-fund", json={"amount": 10})
        assert r.status == 409   # fulfilled now → closed


@pytest.mark.asyncio
async def test_pool_fund_rejected_when_pool_off_or_dry():
    app, store, eng = _make_seeded()   # pool off (default)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 100, "reason": "x", "target": None})).json())["id"]
        assert (await cli.post(f"/api/requests/{rid}/pool-fund", json={"amount": 10})).status == 409
        lst = await (await cli.get("/api/requests?filter=all")).json()
        assert lst["poolEnabled"] is False and lst["poolAvailable"] == 0

    app2, store2, eng2 = _make_seeded(shared_pool=True)   # pool on but empty
    async with TestClient(TestServer(app2)) as cli:
        await _login(cli)
        rid = (await (await cli.post("/api/requests",
               json={"amountNeeded": 100, "reason": "x", "target": None})).json())["id"]
        assert (await cli.post(f"/api/requests/{rid}/pool-fund", json={"amount": 10})).status == 422
