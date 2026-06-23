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

_DEFAULT_DEPLOYMENT = DeploymentConfig(auth_mode="ghe_oauth", web_transport="https",
                                       email_backend="console")


class StubOAuth:
    def authorize_url(self, state): return f"https://ghe/authorize?state={state}"
    async def exchange_code(self, code): return "gho_TEST"
    async def fetch_identity(self, token): return {"login": "octocat", "name": "Octo"}


async def _default_user(pat):
    return {"login": "octocat", "quota_snapshots": {"premium_interactions": {"entitlement": 4000}}}


async def _client(http_get_user=_default_user, admins=frozenset()):
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    sess = SessionService(store, secret="sek", ttl_s=10_000)
    app = make_app(store=store, engine=eng, registry=reg, sessions=sess,
                   oauth=StubOAuth(), http_get_user=http_get_user, cycle_id="c1",
                   secret="sek", app_origin="http://app", now=lambda: 1000, admins=admins,
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
async def test_pat_identity_mismatch_returns_409():
    async def http_get_user_mismatch(pat):
        return {"login": "someone-else",
                "quota_snapshots": {"premium_interactions": {"entitlement": 4000}}}
    app = await _client(http_get_user=http_get_user_mismatch)
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)  # identity is "octocat" (from StubOAuth.fetch_identity)
        r = await cli.post("/api/pat", json={"pat": "github_pat_X"})
        assert r.status == 409
        body = await r.json()
        assert "error" in body and "message" in body


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


def test_build_from_env_takes_session_and_builds_without_a_loop(monkeypatch, tmp_path):
    """Regression: build_from_env must NOT create its own aiohttp ClientSession
    (that needs a running event loop and crashed at startup). It takes the
    session as a param and builds the app synchronously."""
    from aiohttp import web
    import api_server
    from ctc.store.db import connect, init_db
    db = str(tmp_path / "boot.db")
    init_db(connect(db))
    monkeypatch.setenv("CTC_SECRET_KEY", "sek")
    monkeypatch.setenv("CTC_DB_PATH", db)
    monkeypatch.setenv("GHE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GHE_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("GHE_OAUTH_REDIRECT_URI", "http://localhost:8090/auth/callback")
    monkeypatch.setenv("GHE_OAUTH_BASE", "https://example.ghe.com")
    monkeypatch.setenv("GHE_API_BASE", "https://api.example.ghe.com")
    app = api_server.build_from_env(session=object())  # no running loop required
    assert isinstance(app, web.Application)
