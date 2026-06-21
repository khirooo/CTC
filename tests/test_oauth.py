import pytest
from ctc.auth.oauth import GheOAuth


class FakeHttp:
    def __init__(self):
        self.calls = []
    async def post_json(self, url, data, headers):
        self.calls.append(("POST", url, data))
        return {"access_token": "gho_TEST", "token_type": "bearer"}
    async def get_json(self, url, headers):
        self.calls.append(("GET", url, headers.get("Authorization")))
        return {"login": "octocat", "name": "Octo Cat", "id": 1}


def _oauth(http):
    return GheOAuth("cid", "csecret", "https://app/cb", "https://example.ghe.com", http=http)


def test_authorize_url_contains_params():
    url = _oauth(FakeHttp()).authorize_url("st8")
    assert url.startswith("https://example.ghe.com/login/oauth/authorize?")
    assert "client_id=cid" in url and "state=st8" in url
    assert "redirect_uri=https%3A%2F%2Fapp%2Fcb" in url


@pytest.mark.asyncio
async def test_exchange_code_returns_token():
    http = FakeHttp()
    tok = await _oauth(http).exchange_code("abc")
    assert tok == "gho_TEST"
    assert http.calls[0][0] == "POST"


@pytest.mark.asyncio
async def test_fetch_identity_returns_login():
    http = FakeHttp()
    ident = await _oauth(http).fetch_identity("gho_TEST")
    assert ident["login"] == "octocat" and ident["name"] == "Octo Cat"
    assert http.calls[0][2] == "Bearer gho_TEST"
