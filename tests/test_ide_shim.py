import asyncio
import base64

import pytest

from tools import ctc_ide_shim as shim


def _b64(cred: str) -> str:
    return base64.b64encode(cred.encode()).decode()


# ── pure header-injection unit tests ────────────────────────────────────────

def test_inject_proxy_auth_adds_header_on_connect():
    raw = (b"CONNECT api.example.ghe.com:443 HTTP/1.1\r\n"
           b"Host: api.example.ghe.com:443\r\n\r\n")
    rewritten, leftover = shim.inject_proxy_auth(raw, "github_pat_abc")
    assert b"Proxy-Authorization: Basic " + _b64("ctc:github_pat_abc").encode() in rewritten
    assert rewritten.startswith(b"CONNECT api.example.ghe.com:443 HTTP/1.1\r\n")
    assert rewritten.endswith(b"\r\n\r\n")
    assert leftover == b""


def test_inject_proxy_auth_replaces_not_duplicates():
    raw = (b"CONNECT h:443 HTTP/1.1\r\n"
           b"Proxy-Authorization: Basic " + _b64("stale:stale").encode() + b"\r\n"
           b"Host: h:443\r\n\r\n")
    rewritten, _ = shim.inject_proxy_auth(raw, "github_pat_new")
    # exactly one Proxy-Authorization line, and it's ours
    assert rewritten.lower().count(b"proxy-authorization:") == 1
    assert _b64("ctc:github_pat_new").encode() in rewritten
    assert _b64("stale:stale").encode() not in rewritten


def test_inject_proxy_auth_forwards_plain_http_body():
    raw = (b"POST http://h/x HTTP/1.1\r\nHost: h\r\n"
           b"Content-Length: 4\r\n\r\nbody")
    rewritten, leftover = shim.inject_proxy_auth(raw, "tok")
    assert leftover == b"body"
    assert b"Proxy-Authorization: Basic " in rewritten


def test_inject_proxy_auth_drops_proxy_connection():
    raw = (b"CONNECT h:443 HTTP/1.1\r\nHost: h\r\nProxy-Connection: keep-alive\r\n\r\n")
    rewritten, _ = shim.inject_proxy_auth(raw, "tok")
    assert b"proxy-connection:" not in rewritten.lower()


# ── end-to-end forwarding against a local stub "central proxy" ───────────────

@pytest.mark.asyncio
async def test_shim_forwards_injected_head_and_pipes(unused_tcp_port_factory=None):
    received: dict = {}

    async def stub(reader, writer):
        raw = await shim._read_head(reader)
        received["head"] = raw
        # emulate the central proxy answering a CONNECT, then echo
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        data = await reader.read(1024)
        writer.write(b"echo:" + data)
        await writer.drain()
        writer.close()

    stub_server = await asyncio.start_server(stub, "127.0.0.1", 0)
    stub_port = stub_server.sockets[0].getsockname()[1]

    handler = shim._make_handler("github_pat_e2e", "127.0.0.1", stub_port)
    shim_server = await asyncio.start_server(handler, "127.0.0.1", 0)
    shim_port = shim_server.sockets[0].getsockname()[1]

    async with stub_server, shim_server:
        reader, writer = await asyncio.open_connection("127.0.0.1", shim_port)
        writer.write(b"CONNECT api.example.ghe.com:443 HTTP/1.1\r\n"
                     b"Host: api.example.ghe.com:443\r\n\r\n")
        await writer.drain()
        # read the stub's 200, then send tunnel bytes
        resp = await reader.read(1024)
        assert b"200 Connection established" in resp
        writer.write(b"hello")
        await writer.drain()
        echoed = await reader.read(1024)
        writer.close()

    assert b"Proxy-Authorization: Basic " + _b64("ctc:github_pat_e2e").encode() in received["head"]
    assert echoed == b"echo:hello"


@pytest.mark.asyncio
async def test_shim_returns_502_when_central_proxy_down():
    # point at a port nothing is listening on
    handler = shim._make_handler("tok", "127.0.0.1", 1)
    shim_server = await asyncio.start_server(handler, "127.0.0.1", 0)
    shim_port = shim_server.sockets[0].getsockname()[1]
    async with shim_server:
        reader, writer = await asyncio.open_connection("127.0.0.1", shim_port)
        writer.write(b"CONNECT h:443 HTTP/1.1\r\nHost: h\r\n\r\n")
        await writer.drain()
        resp = await reader.read(1024)
        writer.close()
    assert b"502 Bad Gateway" in resp
