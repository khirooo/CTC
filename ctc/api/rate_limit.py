from __future__ import annotations

import time

from aiohttp import web


def client_ip(req) -> str:
    """Best-effort real client IP for rate-limit keying.

    Behind the shipped Caddy front (`reverse_proxy` appends the peer IP to
    `X-Forwarded-For`), `req.remote` is always Caddy's address — so keying on it
    collapses every user into one bucket. The rightmost `X-Forwarded-For` entry is
    the client as Caddy observed it; it's spoof-resistant with a single trusted hop
    (a client-injected value is pushed left by Caddy's appended peer IP). With no
    proxy (http/LAN transport) the header is absent and we fall back to `req.remote`.
    """
    xff = req.headers.get("X-Forwarded-For", "")
    if xff:
        last = xff.split(",")[-1].strip()
        if last:
            return last
    return req.remote or "unknown"


# Per-scope limits (requests per WINDOW_S). Module constants so callers and tests
# agree on the numbers.
WINDOW_S = 60
PAT_LIMIT = 5           # POST /api/pat, per user (a PAT-validation oracle to GHE)
LOGIN_LIMIT = 10        # GET  /auth/login, per client IP
PROXY_TOKEN_LIMIT = 10  # POST /api/proxy-token, per user

# Cap on simultaneously-active proxy tokens per user; minting at the cap
# auto-revokes the oldest active token.
MAX_ACTIVE_PROXY_TOKENS = 10


class RateLimiter:
    """In-process token-bucket rate limiter keyed by (scope, key).

    Each key gets a bucket of `limit` tokens that refills at limit/window_s tokens
    per second. `check` consumes one token or raises HTTPTooManyRequests (429).
    Not shared across processes — adequate for the single control-plane process;
    a hostile multi-node deployment would need a shared store."""

    def __init__(self, now=None):
        self._now = now if now is not None else time.time
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def check(self, scope: str, key: str, limit: int, window_s: int = WINDOW_S) -> None:
        now = float(self._now())
        k = (scope, key)
        rate = limit / window_s
        tokens, last = self._buckets.get(k, (float(limit), now))
        tokens = min(float(limit), tokens + max(0.0, now - last) * rate)
        if tokens < 1.0:
            self._buckets[k] = (tokens, now)
            raise web.HTTPTooManyRequests(text="rate limit exceeded")
        self._buckets[k] = (tokens - 1.0, now)
