import json
import aiohttp
import pytest
import proxy as proxy_mod
from tests.conftest import TEST_HOST


@pytest.mark.asyncio
async def test_capture_writes_redacted_exchange(running_proxy, mock_upstream, client_ssl, tmp_path, monkeypatch):
    monkeypatch.setattr(proxy_mod, "CAPTURE_DIR", str(tmp_path))
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.get(f"https://{TEST_HOST}/copilot_internal/user",
                         proxy=f"http://127.0.0.1:{running_proxy['port']}",
                         headers={"Authorization": "Bearer github_pat_FAKE0000000000000000000000"}) as r:
            await r.read()

    line = (tmp_path / "exchanges.ndjson").read_text().strip().splitlines()[0]
    rec = json.loads(line)
    assert rec["path"] == "/copilot_internal/user"
    assert rec["request_headers"]["authorization"] == "***REDACTED***"
    assert "github_pat_" not in line


@pytest.mark.asyncio
async def test_no_capture_when_dir_unset(running_proxy, mock_upstream, client_ssl, tmp_path, monkeypatch):
    monkeypatch.setattr(proxy_mod, "CAPTURE_DIR", None)
    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.get(f"https://{TEST_HOST}/copilot_internal/user",
                         proxy=f"http://127.0.0.1:{running_proxy['port']}",
                         headers={"Authorization": "token x"}) as r:
            await r.read()
    assert not (tmp_path / "exchanges.ndjson").exists()
