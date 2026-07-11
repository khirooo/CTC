import asyncio
import socket
import ssl
import subprocess

import aiohttp
from aiohttp import web
import pytest
import pytest_asyncio

import proxy as proxy_mod

TEST_HOST = "ghe.test"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _FakeResolver:
    """Redirects the proxy's upstream connection to the local mock port."""
    def __init__(self, port):
        self._port = port

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [{"hostname": host, "host": "127.0.0.1", "port": self._port,
                 "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self):
        pass


@pytest.fixture(scope="session")
def test_cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("certs")
    cert, key = str(d / "cert.pem"), str(d / "key.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
         "-out", cert, "-days", "1", "-nodes", "-subj", "/CN=ghe.test",
         "-addext", f"subjectAltName=DNS:{TEST_HOST},DNS:localhost,IP:127.0.0.1"],
        check=True, capture_output=True)
    return cert, key


@pytest_asyncio.fixture
async def mock_upstream(test_cert):
    cert, key = test_cert
    received = {}

    async def handler(request):
        received["auth"] = request.headers.get("Authorization")
        received["path"] = request.path
        received["body"] = await request.read()
        if request.path == "/sse":
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            for i in range(3):
                await resp.write(f"data: chunk{i}\n\n".encode())
                await asyncio.sleep(0.1)
            await resp.write_eof()
            return resp
        if request.path == "/empty":
            return web.Response(status=204)
        return web.json_response({"login": "ok", "path": request.path})

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
async def running_proxy(test_cert, mock_upstream):
    cert, key = test_cert

    # Save original module globals so we can restore them after the test
    orig_real_ghe_host = proxy_mod.REAL_GHE_HOST
    orig_real_pat = proxy_mod.REAL_PAT
    orig_mitm_hosts = proxy_mod.MITM_HOSTS
    orig_swap_hosts = proxy_mod.SWAP_HOSTS
    orig_upstream_ca_bundle = proxy_mod.UPSTREAM_CA_BUNDLE
    orig_upstream_insecure = proxy_mod.UPSTREAM_INSECURE
    orig_server_ssl = proxy_mod._server_ssl
    orig_http = proxy_mod._http

    proxy_mod.REAL_GHE_HOST = TEST_HOST
    proxy_mod.REAL_PAT = "github_pat_REAL000000000000000000000000000000"
    proxy_mod.MITM_HOSTS = {TEST_HOST}
    proxy_mod.SWAP_HOSTS = {TEST_HOST}
    proxy_mod.UPSTREAM_CA_BUNDLE = cert
    proxy_mod.UPSTREAM_INSECURE = False
    # The upstream SSLContext is cached lazily (B2); reset so it rebuilds from
    # the test CA/insecure globals we just monkeypatched instead of reusing a
    # context built at import time.
    orig_upstream_ssl = proxy_mod._upstream_ssl
    proxy_mod._upstream_ssl = None

    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    sctx.set_alpn_protocols(["http/1.1"])
    proxy_mod._server_ssl = sctx

    connector = aiohttp.TCPConnector(ssl=False, resolver=_FakeResolver(mock_upstream["port"]))
    proxy_mod._http = aiohttp.ClientSession(connector=connector)

    port = _free_port()
    srv = await asyncio.start_server(proxy_mod._dispatch, "127.0.0.1", port)
    yield {"port": port, "pat": proxy_mod.REAL_PAT}
    srv.close()
    await srv.wait_closed()
    await proxy_mod._http.close()

    # Restore original module globals
    proxy_mod.REAL_GHE_HOST = orig_real_ghe_host
    proxy_mod.REAL_PAT = orig_real_pat
    proxy_mod.MITM_HOSTS = orig_mitm_hosts
    proxy_mod.SWAP_HOSTS = orig_swap_hosts
    proxy_mod.UPSTREAM_CA_BUNDLE = orig_upstream_ca_bundle
    proxy_mod.UPSTREAM_INSECURE = orig_upstream_insecure
    proxy_mod._upstream_ssl = orig_upstream_ssl
    proxy_mod._server_ssl = orig_server_ssl
    proxy_mod._http = orig_http
    if orig_http is not None:
        await orig_http.close()


@pytest.fixture
def client_ssl(test_cert):
    cert, _ = test_cert
    return ssl.create_default_context(cafile=cert)
