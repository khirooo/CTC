import asyncio
import aiohttp
import pytest

from conftest import TEST_HOST, _free_port
import proxy as proxy_mod


async def test_sse_streams_incrementally(running_proxy, client_ssl):
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    loop = asyncio.get_running_loop()
    stamps = []
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.get(f"https://{TEST_HOST}/sse",
                         proxy=f"http://127.0.0.1:{running_proxy['port']}",
                         headers={"Authorization": "token x"}) as r:
            async for line in r.content:
                if line.strip():
                    stamps.append(loop.time())
    assert len(stamps) >= 3
    assert stamps[-1] - stamps[0] > 0.15  # spread over time, not delivered all at once


async def test_chunked_request_forwarded_intact(running_proxy, mock_upstream, client_ssl):
    async def gen():
        yield b"hello "
        yield b"world"

    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.post(f"https://{TEST_HOST}/echo", data=gen(),
                          proxy=f"http://127.0.0.1:{running_proxy['port']}",
                          headers={"Authorization": "token x"}) as r:
            await r.read()
    assert mock_upstream["received"]["body"] == b"hello world"


async def test_fake_token_swapped_to_bearer_pat(running_proxy, mock_upstream, client_ssl):
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.get(f"https://{TEST_HOST}/copilot_internal/user",
                         proxy=f"http://127.0.0.1:{running_proxy['port']}",
                         headers={"Authorization": "token github_pat_FAKE000"}) as r:
            await r.read()
    assert mock_upstream["received"]["auth"] == f"Bearer {running_proxy['pat']}"


async def test_proxy_accepts_verifying_client(running_proxy, client_ssl):
    # PROXY-SIDE test: a client whose SSL context trusts the proxy cert and verifies
    # fully completes the MITM handshake (no insecure bypass). NOTE: this uses a Python
    # aiohttp client and does NOT model the real copilot CLI's trust path — copilot
    # bundles its own Node runtime and ignores NODE_EXTRA_CA_CERTS, requiring OS-keychain
    # trust instead (see TDD.md §6.1 / §11). This asserts the proxy's behavior, not copilot's.
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.get(f"https://{TEST_HOST}/copilot_internal/user",
                         proxy=f"http://127.0.0.1:{running_proxy['port']}",
                         headers={"Authorization": "token x"}) as r:
            assert r.status == 200


async def test_blind_tunnel_passthrough(running_proxy, monkeypatch):
    monkeypatch.setattr(proxy_mod, "_LOCALHOST_ALIASES", frozenset())

    async def echo(r, w):
        data = await r.read(100)
        w.write(data)
        await w.drain()
        w.close()

    echo_port = _free_port()
    srv = await asyncio.start_server(echo, "127.0.0.1", echo_port)
    reader, writer = await asyncio.open_connection("127.0.0.1", running_proxy["port"])
    writer.write(f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    resp = await reader.readuntil(b"\r\n\r\n")
    assert b"200" in resp
    writer.write(b"PING")
    await writer.drain()
    assert await reader.readexactly(4) == b"PING"
    writer.close()
    await writer.wait_closed()
    srv.close()
    await srv.wait_closed()


async def test_no_content_response_not_chunked(running_proxy, client_ssl):
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.get(f"https://{TEST_HOST}/empty",
                         proxy=f"http://127.0.0.1:{running_proxy['port']}",
                         headers={"Authorization": "token x"}) as r:
            body = await r.read()
    assert r.status == 204
    assert body == b""
    assert r.headers.get("Transfer-Encoding") is None
