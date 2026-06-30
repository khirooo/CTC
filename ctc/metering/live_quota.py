from __future__ import annotations
import time
from typing import Awaitable, Callable

class LiveQuotaCache:
    """On-read + TTL cache for a giver's live GitHub premium_interactions quota.
    One instance per process (proxy and control plane each own one). Failed
    fetches are NOT cached (always retried). `set_exhausted` lets the 402
    failover path mark a giver dead without an extra round-trip."""

    def __init__(self, pat_for: Callable[[str], str | None],
                 fetch_user: Callable[[str], Awaitable[dict]],
                 ttl: int = 60, clock: Callable[[], float] = time.time):
        self._pat_for = pat_for
        self._fetch_user = fetch_user
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}  # giver_id -> (ts, value)

    async def get(self, giver_id: str) -> dict | None:
        hit = self._cache.get(giver_id)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        pat = self._pat_for(giver_id)
        if not pat:
            return None
        try:
            u = await self._fetch_user(pat)
        except Exception:
            return None  # do not cache failures; never block the caller
        pi = (u.get("quota_snapshots") or {}).get("premium_interactions") or {}
        value = {"entitlement": pi.get("entitlement"),
                 "remaining": pi.get("remaining"),
                 "reset_date": u.get("quota_reset_date")}
        self._cache[giver_id] = (self._clock(), value)
        return value

    async def remaining(self, giver_id: str) -> int | None:
        v = await self.get(giver_id)
        if v is None:
            return None
        r = v.get("remaining")
        return int(r) if r is not None else None

    def invalidate(self, giver_id: str) -> None:
        self._cache.pop(giver_id, None)

    def set_exhausted(self, giver_id: str) -> None:
        self._cache[giver_id] = (self._clock(),
            {"entitlement": None, "remaining": 0, "reset_date": None})
