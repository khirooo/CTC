"""End-to-end dry-run of the VS Code IDE path — the whole chain in-process,
no real proxy deployment, no real PAT, no real extension:

    aiohttp client ──CONNECT──> ctc_ide_shim ──CONNECT(+Proxy-Auth)──> proxy
                                                                        │ MITM
                                              mock copilot-api <────────┘

Proves the NEW wiring the milestone adds:
  1. the shim injects Proxy-Authorization on the CONNECT, and the proxy answers
     the extension's GET /copilot_internal/v2/token locally (fabricated 200);
  2. the proxy resolves the consumer FROM the shim-injected token, swaps in the
     giver PAT, rewrites copilot-integration-id, and debits that consumer for a
     billable POST /responses;
  3. a bogus shim token is rejected (401) — proving identity really comes from
     the injected header, not the bearer.
"""
import asyncio
import json
import ssl

import aiohttp
from aiohttp import web
import pytest
import pytest_asyncio

from conftest import TEST_HOST, _free_port, _FakeResolver
import proxy as proxy_mod
from ctc import contract
from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.accounting.engine import AccountingEngine
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db
from tools import ctc_ide_shim as shim

CYCLE = "c-e2e"
GIVER = "u-giver"
REAL_PAT = "github_pat_REALcredit0000000000000000000000"
NANO_AIU = 500


@pytest_asyncio.fixture
async def ide_upstream(test_cert):
    """Mock copilot-api: fabricated /copilot_internal/user (health), and a
    billable /responses SSE ending in a message_delta carrying total_nano_aiu."""
    cert, key = test_cert
    received = {}

    async def handler(request):
        received["auth"] = request.headers.get("Authorization")
        received["integration_id"] = request.headers.get("copilot-integration-id")
        received["path"] = request.path
        if request.path == "/copilot_internal/user":
            return web.json_response({
                "quota_snapshots": {"premium_interactions":
                                    {"entitlement": 10_000_000, "remaining": 9_000_000}},
                "quota_reset_date": "2099-01-01"})
        if request.path == "/responses":
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            await resp.write(b'data: {"type":"response.created"}\n\n')
            await resp.write((
                'data: {"type":"message_delta","copilot_usage":'
                f'{{"total_nano_aiu":{NANO_AIU}}}}}\n\n').encode())
            await resp.write_eof()
            return resp
        return web.json_response({"ok": True, "path": request.path})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    port = _free_port()
    site = web.TCPSite(runner, "127.0.0.1", port, ssl_context=ctx)
    await site.start()
    yield {"port": port, "received": received}
    await runner.cleanup()


@pytest_asyncio.fixture
async def mt_proxy(test_cert, ide_upstream, tmp_path, monkeypatch):
    """The real proxy dispatcher, running in multi-tenant (DB) mode, with the
    billable host redirected to the mock and TLS MITM via the test cert."""
    cert, key = test_cert

    # Seed a DB: one giver who is also the consumer (OWN bucket), with credit.
    db = str(tmp_path / "ide-e2e.db")
    conn = connect(db); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn))
    eng.start_cycle(CYCLE, "e2e", 0, 9_999_999_999)
    eng.set_quota(CYCLE, GIVER, 100_000_000)
    store.upsert_user(GIVER, "giver-login", "Giver", "giver", 1)
    reg = AuthRegistry(store, derive_key("e2e-secret-key-16chars"))
    _, consumer_token, _ = reg.issue_proxy_token(GIVER, now=1)
    reg.store_pat(GIVER, REAL_PAT, now=1)

    monkeypatch.setenv("CTC_DB_PATH", db)
    monkeypatch.setenv("CTC_SECRET_KEY", "e2e-secret-key-16chars")
    monkeypatch.delenv("CTC_IDENTITY_JSON", raising=False)
    monkeypatch.delenv("CTC_PATS_JSON", raising=False)

    # Route everything at the billable host; redirect its TCP connect to the mock.
    monkeypatch.setattr(contract, "BILLABLE_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "_COPILOT_API_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "REAL_GHE_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "REAL_PAT", "")          # multi-tenant
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {TEST_HOST})
    monkeypatch.setattr(proxy_mod, "SWAP_HOSTS", {TEST_HOST})
    monkeypatch.setattr(proxy_mod, "UPSTREAM_CA_BUNDLE", cert)
    monkeypatch.setattr(proxy_mod, "UPSTREAM_INSECURE", False)
    monkeypatch.setattr(proxy_mod, "_upstream_ssl", None)
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", proxy_mod._build_attribution())

    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    sctx.set_alpn_protocols(["http/1.1"])
    monkeypatch.setattr(proxy_mod, "_server_ssl", sctx)

    connector = aiohttp.TCPConnector(ssl=False, resolver=_FakeResolver(ide_upstream["port"]))
    http = aiohttp.ClientSession(connector=connector)
    monkeypatch.setattr(proxy_mod, "_http", http)

    port = _free_port()
    srv = await asyncio.start_server(proxy_mod._dispatch, "127.0.0.1", port)
    yield {"port": port, "consumer_token": consumer_token, "engine": eng}
    srv.close()
    await srv.wait_closed()
    await http.close()


async def _start_shim(token: str, proxy_port: int) -> tuple:
    server = await asyncio.start_server(
        shim._make_handler(token, "127.0.0.1", proxy_port), "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_ide_full_chain_through_shim(mt_proxy, test_cert):
    cert, _ = test_cert
    client_ssl = ssl.create_default_context(cafile=cert)
    shim_srv, shim_port = await _start_shim(mt_proxy["consumer_token"], mt_proxy["port"])
    proxy_url = f"http://127.0.0.1:{shim_port}"
    eng = mt_proxy["engine"]
    before = eng.personal_remaining(CYCLE, GIVER)

    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with shim_srv, aiohttp.ClientSession(connector=connector) as s:
        # 1) the extension's mandatory token exchange — answered locally
        async with s.get(f"https://{TEST_HOST}/copilot_internal/v2/token",
                         proxy=proxy_url) as r:
            assert r.status == 200
            tok = await r.json()
        assert tok["token"].startswith("tid=ctc")
        assert tok["endpoints"]["api"].startswith("https://copilot-api.")

        # 2) a billable chat via the Responses API
        async with s.post(f"https://{TEST_HOST}/responses",
                          proxy=proxy_url,
                          data=json.dumps({"model": "gpt", "input": "hi"}),
                          headers={"copilot-integration-id": "vscode-chat",
                                   "content-type": "application/json"}) as r:
            assert r.status == 200
            await r.read()

    # the billable turn was debited to the consumer (swap + spoof asserted in the
    # sibling test that inspects the mock's recorded headers)
    after = eng.personal_remaining(CYCLE, GIVER)
    assert before - after == NANO_AIU


async def test_ide_upstream_saw_swapped_pat_and_spoofed_id(mt_proxy, ide_upstream, test_cert):
    cert, _ = test_cert
    client_ssl = ssl.create_default_context(cafile=cert)
    shim_srv, shim_port = await _start_shim(mt_proxy["consumer_token"], mt_proxy["port"])
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with shim_srv, aiohttp.ClientSession(connector=connector) as s:
        async with s.post(f"https://{TEST_HOST}/responses",
                          proxy=f"http://127.0.0.1:{shim_port}",
                          data="{}",
                          headers={"copilot-integration-id": "vscode-chat",
                                   "content-type": "application/json"}) as r:
            await r.read()
    assert ide_upstream["received"]["auth"] == f"Bearer {REAL_PAT}"
    assert ide_upstream["received"]["integration_id"] == "copilot-developer-cli"


async def test_ide_bogus_shim_token_rejected(mt_proxy, test_cert):
    cert, _ = test_cert
    client_ssl = ssl.create_default_context(cafile=cert)
    shim_srv, shim_port = await _start_shim("github_pat_BOGUS_not_in_db", mt_proxy["port"])
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with shim_srv, aiohttp.ClientSession(connector=connector) as s:
        async with s.post(f"https://{TEST_HOST}/responses",
                          proxy=f"http://127.0.0.1:{shim_port}",
                          data="{}",
                          headers={"content-type": "application/json"}) as r:
            assert r.status == 401
            body = await r.read()
    assert b"not recognized" in body
