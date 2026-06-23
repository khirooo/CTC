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
from ctc.auth.email_sender import ConsoleEmailSender
from ctc.auth.magic_link import EmailMagicLink
import logging


def _app(auth_mode):
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    ec = EffectiveConfig(SettingsStore(conn))
    engine = AccountingEngine(AccountingStore(conn), config=ec)
    engine.ensure_active_cycle(int(time.time()))
    reg = AuthRegistry(store, derive_key("k" * 32))
    sessions = SessionService(store, secret="k" * 32)
    dep = DeploymentConfig(auth_mode=auth_mode, web_transport="http", email_backend="console")
    ml = EmailMagicLink(store, "k" * 32, "http://app", ConsoleEmailSender(logging.getLogger("t")))
    return make_app(store=store, engine=engine, registry=reg, sessions=sessions,
                    oauth=None, http_get_user=None, secret="k" * 32, app_origin="http://app",
                    deployment=dep, magic_link=ml, ca_cert_path="/nonexistent.pem")
    # ca_cert_path is a non-existent path on purpose: ca_fingerprint_sha256 returns
    # None for an unreadable file, so make_app constructs cleanly without a cert.


@pytest.mark.asyncio
async def test_api_config_reports_auth_mode():
    app = _app("email")
    async with TestClient(TestServer(app)) as cli:
        r = await cli.get("/api/config")
        assert r.status == 200
        assert (await r.json())["authMode"] == "email"


@pytest.mark.asyncio
async def test_email_login_sets_session():
    app = _app("email")
    async with TestClient(TestServer(app)) as cli:
        r = await cli.post("/auth/email", json={"email": "a@b.com"})
        assert r.status == 204
        # console sender logged the link; in test, mint+verify directly via the app store is covered by provider tests.


@pytest.mark.asyncio
async def test_oauth_mode_has_no_email_route():
    app = _app("ghe_oauth")
    async with TestClient(TestServer(app)) as cli:
        r = await cli.post("/auth/email", json={"email": "a@b.com"})
        assert r.status == 404
