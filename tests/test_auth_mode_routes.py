import time
import pytest
from aiohttp.test_utils import TestClient, TestServer
from api_server import make_app
from ctc.store.db import connect, init_db
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.store.settings_store import SettingsStore
from ctc.domain.settings import EffectiveConfig
from ctc.domain.deployment import DeploymentConfig
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.auth.crypto import derive_key


class StubOAuth:
    def authorize_url(self, state): return f"https://gitlab/oauth/authorize?state={state}"
    async def exchange_code(self, code): return "glpat_TEST"
    async def fetch_identity(self, token): return {"login": "octo", "name": "Octo"}


def _app():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    ec = EffectiveConfig(SettingsStore(conn))
    engine = AccountingEngine(AccountingStore(conn), config=ec)
    engine.ensure_active_cycle(int(time.time()))
    reg = AuthRegistry(store, derive_key("k" * 32))
    sessions = SessionService(store, secret="k" * 32)
    dep = DeploymentConfig(web_transport="http")
    return make_app(store=store, engine=engine, registry=reg, sessions=sessions,
                    oauth=StubOAuth(), http_get_user=None, secret="k" * 32,
                    app_origin="http://app", deployment=dep, ca_cert_path="/nonexistent.pem")


@pytest.mark.asyncio
async def test_oauth_login_redirects():
    async with TestClient(TestServer(_app())) as cli:
        r = await cli.get("/auth/login", allow_redirects=False)
        assert r.status in (301, 302, 303)
        assert "gitlab" in r.headers["Location"]


@pytest.mark.asyncio
async def test_email_route_is_gone():
    async with TestClient(TestServer(_app())) as cli:
        r = await cli.post("/auth/email", json={"email": "a@b.com"})
        assert r.status == 404


@pytest.mark.asyncio
async def test_config_route_is_gone():
    async with TestClient(TestServer(_app())) as cli:
        r = await cli.get("/api/config")
        assert r.status == 404
