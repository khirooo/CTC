import pytest
from aiohttp.test_utils import TestClient, TestServer
from ctc.auth.admin import admins_from_env, is_admin
from tests.test_api_server import _client, _login   # reuse harness


def test_admins_from_env_parsing():
    assert admins_from_env({}) == frozenset()
    assert admins_from_env({"CTC_ADMINS": ""}) == frozenset()
    assert admins_from_env({"CTC_ADMINS": " Octo , bob ,"}) == frozenset({"octo", "bob"})


def test_is_admin_case_insensitive():
    admins = admins_from_env({"CTC_ADMINS": "Octo"})
    assert is_admin("octo", admins) is True
    assert is_admin("OCTO", admins) is True
    assert is_admin("alice", admins) is False


@pytest.mark.asyncio
async def test_me_reports_is_admin_true_for_listed_login():
    app = await _client(admins=frozenset({"octocat"}))   # StubOAuth identity = octocat
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        me = await (await cli.get("/api/me")).json()
        assert me["is_admin"] is True


@pytest.mark.asyncio
async def test_me_reports_is_admin_false_when_not_listed():
    app = await _client()    # default: no admins
    async with TestClient(TestServer(app)) as cli:
        await _login(cli)
        me = await (await cli.get("/api/me")).json()
        assert me["is_admin"] is False
