from __future__ import annotations

from urllib.parse import urlencode


class AiohttpJson:
    """Production http dependency wrapping an aiohttp session."""
    def __init__(self, session):
        self.session = session
    async def post_json(self, url, data, headers):
        async with self.session.post(url, data=data, headers=headers) as r:
            return await r.json()
    async def get_json(self, url, headers):
        async with self.session.get(url, headers=headers) as r:
            return await r.json()


class GitLabOAuth:
    def __init__(self, client_id, client_secret, redirect_uri, base, http=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.base = base.rstrip("/")
        self.http = http

    def authorize_url(self, state: str) -> str:
        q = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "read_user",
            "state": state,
        })
        return f"{self.base}/oauth/authorize?{q}"

    async def exchange_code(self, code: str) -> str:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        body = await self.http.post_json(
            f"{self.base}/oauth/token", data, {"Accept": "application/json"}
        )
        return body["access_token"]

    async def fetch_identity(self, access_token: str) -> dict:
        # GitLab /api/v4/user returns `username`; map it to our `login` field.
        body = await self.http.get_json(
            f"{self.base}/api/v4/user", {"Authorization": f"Bearer {access_token}"}
        )
        return {"login": body["username"], "name": body.get("name") or body["username"]}
