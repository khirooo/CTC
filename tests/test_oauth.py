import pytest
from ctc.auth.oauth import GitLabOAuth, OAuthExchangeError


class FakeHttp:
    def __init__(self):
        self.calls = []
    async def post_json(self, url, data, headers):
        self.calls.append(("POST", url, data))
        return {"access_token": "glpat_TEST", "token_type": "bearer"}
    async def get_json(self, url, headers):
        self.calls.append(("GET", url, headers.get("Authorization")))
        return {"username": "octo", "name": "Octo Cat", "id": 1}


def _oauth(http):
    return GitLabOAuth("cid", "csecret", "https://app/cb", "https://gitlab.company.com", http=http)


def test_authorize_url_contains_params():
    url = _oauth(FakeHttp()).authorize_url("st8")
    assert url.startswith("https://gitlab.company.com/oauth/authorize?")
    assert "client_id=cid" in url and "state=st8" in url
    assert "response_type=code" in url
    assert "scope=read_user" in url
    assert "redirect_uri=https%3A%2F%2Fapp%2Fcb" in url


@pytest.mark.asyncio
async def test_exchange_code_posts_token_endpoint():
    http = FakeHttp()
    tok = await _oauth(http).exchange_code("abc")
    assert tok == "glpat_TEST"
    method, url, data = http.calls[0]
    assert method == "POST" and url == "https://gitlab.company.com/oauth/token"
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "abc"


@pytest.mark.asyncio
async def test_fetch_identity_maps_username_to_login():
    http = FakeHttp()
    ident = await _oauth(http).fetch_identity("glpat_TEST")
    assert ident["login"] == "octo" and ident["name"] == "Octo Cat"
    method, url, auth = http.calls[0]
    assert url == "https://gitlab.company.com/api/v4/user"
    assert auth == "Bearer glpat_TEST"


@pytest.mark.asyncio
async def test_fetch_identity_falls_back_to_username_when_name_missing():
    class NoName(FakeHttp):
        async def get_json(self, url, headers):
            return {"username": "octo", "id": 1}
    ident = await _oauth(NoName()).fetch_identity("glpat_TEST")
    assert ident["name"] == "octo"


@pytest.mark.asyncio
async def test_exchange_code_raises_without_access_token():
    class NoTok(FakeHttp):
        async def post_json(self, url, data, headers):
            return {"error": "invalid_grant"}
    with pytest.raises(OAuthExchangeError):
        await _oauth(NoTok()).exchange_code("abc")


@pytest.mark.asyncio
async def test_fetch_identity_raises_without_username():
    class NoUser(FakeHttp):
        async def get_json(self, url, headers):
            return {"id": 1}
    with pytest.raises(OAuthExchangeError):
        await _oauth(NoUser()).fetch_identity("glpat_TEST")
