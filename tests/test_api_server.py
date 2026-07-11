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
from ctc.domain.config import NANO_PER_AIU as N
from ctc.domain.types import Bucket, GiverCycle

_DEFAULT_DEPLOYMENT = DeploymentConfig(web_transport="https")


class StubOAuth:
    def authorize_url(self, state): return f"https://ghe/authorize?state={state}"
    async def exchange_code(self, code): return "gho_TEST"
    async def fetch_identity(self, token): return {"login": "octocat", "name": "Octo"}


async def _default_user(pat):
    # remaining == entitlement: fresh cycle, nothing spent yet
    return {"login": "octocat", "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 4000}}}


async def _client(http_get_user=_default_user, admins=frozenset(), now=lambda: 1000):
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10_000)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=http_get_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=now, admins=admins,
                   deployment=_DEFAULT_DEPLOYMENT)
    return app


async def _login(cli):
    """Drive the OAuth flow to seed the session cookie in the client jar."""
    r = await cli.get("/auth/login", allow_redirects=False)
    assert r.status in (301, 302, 303)
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    r = await cli.get(f"/auth/callback?code=abc&state={state}", allow_redirects=False)
    assert r.status in (302, 303)


@pytest.mark.asyncio
async def test_me_requires_session():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.get("/api/me")
        assert r.status == 401
        body = await r.json()
        assert "error" in body and "message" in body
        assert body["message"] == "no session"


@pytest.mark.asyncio
async def test_cors_header_on_api_me():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.get("/api/me")
        assert r.headers.get("Access-Control-Allow-Origin") == "http://app"


@pytest.mark.asyncio
async def test_cors_preflight_options():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.options("/api/me")
        assert r.status == 204
        assert r.headers.get("Access-Control-Allow-Origin") == "http://app"
        assert "GET" in r.headers.get("Access-Control-Allow-Methods", "")


@pytest.mark.asyncio
async def test_full_login_then_me_then_pat_then_token():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        # Step 1: GET /auth/login to seed state cookie in client jar
        r = await cli.get("/auth/login", allow_redirects=False)
        assert r.status in (301, 302, 303)
        location = r.headers["Location"]
        # StubOAuth.authorize_url echoes state in URL: "https://ghe/authorize?state=<state>"
        parsed = urlparse(location)
        state = parse_qs(parsed.query)["state"][0]

        # Step 2: OAuth callback with the same state extracted from login redirect
        r = await cli.get(f"/auth/callback?code=abc&state={state}", allow_redirects=False)
        assert r.status in (302, 303)

        # session cookie now stored in the client jar
        me = await (await cli.get("/api/me")).json()
        assert me["ghe_login"] == "octocat" and me["role"] == "consumer" and me["has_pat"] is False

        # submit PAT
        r = await cli.post("/api/pat", json={"pat": "github_pat_X"})
        assert r.status == 200 and (await r.json())["quota_aiu"] == 4000
        assert (await (await cli.get("/api/me")).json())["role"] == "giver"

        # mint a proxy token (shown once)
        r = await cli.post("/api/proxy-token")
        body = await r.json()
        assert body["token"].startswith("github_pat_") and "id" in body

        # it appears in the list (without the raw token)
        lst = await (await cli.get("/api/proxy-token")).json()
        assert lst[0]["id"] == body["id"] and "token" not in lst[0]


@pytest.mark.asyncio
async def test_pat_identity_mismatch_is_accepted():
    # enforce_identity=False unconditionally: GitLab username never matches the GHE PAT owner,
    # so a PAT from a different GHE login is accepted without a 409.
    async def http_get_user_mismatch(pat):
        return {"login": "someone-else",
                "quota_snapshots": {"premium_interactions": {"entitlement": 4000, "remaining": 4000}}}
    app = await _client(http_get_user=http_get_user_mismatch)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)  # identity is "octocat" (from StubOAuth.fetch_identity)
        r = await cli.post("/api/pat", json={"pat": "github_pat_X"})
        assert r.status == 200


@pytest.mark.asyncio
async def test_me_reports_onboarded_false_then_true():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        r = await cli.get("/api/me")
        assert r.status == 200
        assert (await r.json())["onboarded"] is False
        r = await cli.post("/api/onboarding/complete")
        assert r.status == 204
        r = await cli.get("/api/me")
        assert (await r.json())["onboarded"] is True


@pytest.mark.asyncio
async def test_onboarding_complete_requires_session():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.post("/api/onboarding/complete")
        assert r.status == 401


# ---------------------------------------------------------------------------
# A3: client-error handling (JSONDecodeError / non-object body / AccountingError)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_malformed_json_body_is_400_json():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        r = await cli.post("/api/pat", data="{not json",
                           headers={"content-type": "application/json"})
        assert r.status == 400
        body = await r.json()
        assert "error" in body and "message" in body


@pytest.mark.asyncio
async def test_non_object_json_body_is_400():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        r = await cli.post("/api/pat", json=[1, 2, 3])
        assert r.status == 400


@pytest.mark.asyncio
async def test_pat_resubmission_below_consumed_pledge_is_409():
    # A giver with already-booked pool spend, re-submitting a PAT whose entitlement
    # is below that spend, must get 409 (InvalidPledge) — not a 500.
    async def small_ent(pat):
        return {"login": "octocat",
                "quota_snapshots": {"premium_interactions": {"entitlement": 1, "remaining": 1}}}
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10_000)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=small_ent, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000,
                   deployment=_DEFAULT_DEPLOYMENT)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        uid = store.get_user_by_login("octocat")["id"]
        eng.store.upsert_giver_cycle(GiverCycle("c1", uid, 5000 * N, 5000 * N))
        eng.record_consumption("c1", uid, uid, Bucket.POOL, 100 * N, ts=1, allow_overshoot=True)
        r = await cli.post("/api/pat", json={"pat": "github_pat_X"})
        assert r.status == 409
        body = await r.json()
        assert "error" in body and "message" in body


def test_build_from_env_takes_session_and_builds_without_a_loop(monkeypatch, tmp_path):
    """Regression: build_from_env must NOT create its own aiohttp ClientSession
    (that needs a running event loop and crashed at startup). It takes the
    session as a param and builds the app synchronously."""
    from aiohttp import web
    import api_server
    from ctc.store.db import connect, init_db
    db = str(tmp_path / "boot.db")
    init_db(connect(db))
    monkeypatch.setenv("CTC_SECRET_KEY", "sekret-key-at-least-16")
    monkeypatch.setenv("CTC_DB_PATH", db)
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("GITLAB_OAUTH_REDIRECT_URI", "http://localhost:8090/auth/callback")
    monkeypatch.setenv("GITLAB_BASE", "https://gitlab.example.com")
    monkeypatch.setenv("GHE_API_BASE", "https://api.example.ghe.com")
    app = api_server.build_from_env(session=object())  # no running loop required
    assert isinstance(app, web.Application)


def test_build_from_env_rejects_short_secret(monkeypatch, tmp_path):
    import api_server
    from ctc.store.db import connect, init_db
    db = str(tmp_path / "boot.db")
    init_db(connect(db))
    monkeypatch.setenv("CTC_SECRET_KEY", "short")   # < 16 chars
    monkeypatch.setenv("CTC_DB_PATH", db)
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GITLAB_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("GITLAB_OAUTH_REDIRECT_URI", "http://localhost:8090/auth/callback")
    monkeypatch.setenv("GITLAB_BASE", "https://gitlab.example.com")
    monkeypatch.setenv("GHE_API_BASE", "https://api.example.ghe.com")
    with pytest.raises(ValueError):
        api_server.build_from_env(session=object())


@pytest.mark.asyncio
async def test_pat_endpoint_rate_limited_per_user():
    app = await _client()
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        # PAT_LIMIT=5 posts allowed (frozen clock → no refill), 6th is 429.
        statuses = [(await cli.post("/api/pat", json={"pat": "github_pat_X"})).status
                    for _ in range(6)]
        assert statuses[:5] == [200, 200, 200, 200, 200]
        assert statuses[5] == 429


@pytest.mark.asyncio
async def test_proxy_token_cap_auto_revokes_oldest():
    clock = [1000]
    app = await _client(now=lambda: clock[0])
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        ids = []
        for _ in range(11):
            clock[0] += 60          # advance a full window so the rate limit refills
            b = await (await cli.post("/api/proxy-token")).json()
            ids.append(b["id"])
        lst = await (await cli.get("/api/proxy-token")).json()
        active = [t for t in lst if not t["revoked"]]
        assert len(active) == 10                       # capped
        assert ids[0] not in {t["id"] for t in active}  # oldest auto-revoked
