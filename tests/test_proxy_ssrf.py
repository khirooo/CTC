"""SSRF / open-relay guard (P0-2): connect_allowed unit tests + raw-TCP
integration tests exercising both the CONNECT and plain-HTTP dispatch branches
with CTC_RESTRICT_CONNECT on."""
import asyncio

import pytest

import proxy as proxy_mod
from conftest import TEST_HOST


# --------------------------------------------------------------------------- #
# connect_allowed unit tests
# --------------------------------------------------------------------------- #
def test_connect_allowed_permits_mitm_and_ecosystem_hosts(monkeypatch):
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {"copilot-api.example.ghe.com"})
    monkeypatch.setattr(proxy_mod, "EXTRA_ALLOWED_HOSTS", set())
    assert proxy_mod.connect_allowed("copilot-api.example.ghe.com")
    assert proxy_mod.connect_allowed("api.github.com")
    assert proxy_mod.connect_allowed("github.com")
    assert proxy_mod.connect_allowed("api.githubcopilot.com")
    assert proxy_mod.connect_allowed("api.localhost")


def test_connect_allowed_rejects_evil_hosts(monkeypatch):
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {"copilot-api.example.ghe.com"})
    monkeypatch.setattr(proxy_mod, "EXTRA_ALLOWED_HOSTS", set())
    assert not proxy_mod.connect_allowed("evilgithub.com")
    assert not proxy_mod.connect_allowed("example.com")
    assert not proxy_mod.connect_allowed("169.254.169.254")


def test_connect_allowed_honors_extra_allowed_hosts(monkeypatch):
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {"copilot-api.example.ghe.com"})
    monkeypatch.setattr(proxy_mod, "EXTRA_ALLOWED_HOSTS", {"jira.internal"})
    assert proxy_mod.connect_allowed("jira.internal")
    assert not proxy_mod.connect_allowed("other.internal")


# --------------------------------------------------------------------------- #
# Integration: plain-HTTP (non-CONNECT) branch guarded by RESTRICT_CONNECT
# --------------------------------------------------------------------------- #
async def _raw_http_get(port, host_header, path="/copilot_internal/user"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\n"
        f"Authorization: token x\r\n\r\n".encode())
    await writer.drain()
    data = await reader.read(4096)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return data


async def test_plain_http_to_evil_host_rejected(running_proxy, monkeypatch):
    monkeypatch.setattr(proxy_mod, "RESTRICT_CONNECT", True)
    data = await _raw_http_get(running_proxy["port"], "evil.example.com")
    assert b"403 Forbidden" in data


async def test_plain_http_to_allowed_host_forwarded(running_proxy, monkeypatch):
    # TEST_HOST is in MITM_HOSTS (set by the fixture) → allowed → forwarded to
    # the mock upstream, which returns 200.
    monkeypatch.setattr(proxy_mod, "RESTRICT_CONNECT", True)
    data = await _raw_http_get(running_proxy["port"], TEST_HOST)
    assert b"200" in data.split(b"\r\n", 1)[0]


async def test_connect_to_evil_host_rejected(running_proxy, monkeypatch):
    monkeypatch.setattr(proxy_mod, "RESTRICT_CONNECT", True)
    reader, writer = await asyncio.open_connection("127.0.0.1", running_proxy["port"])
    writer.write(b"CONNECT evil.example.com:443 HTTP/1.1\r\nHost: evil.example.com\r\n\r\n")
    await writer.drain()
    data = await reader.read(4096)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    assert b"403 Forbidden" in data
