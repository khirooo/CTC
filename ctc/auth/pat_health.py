"""Periodic giver-PAT health checks.

A PAT is validated once at upload and then silently rots: when it expires or
is revoked, the CLI just starts failing and the owner never learns why. This
module re-checks every stored PAT against GET /copilot_internal/user and
persists a verdict on the giver_pats row so the profile and admin panel can
display it.

Verdicts are display-only: routing/attribution is untouched (the proxy already
fails over at request time). Only DEFINITIVE outcomes overwrite the stored
status; a network error or GHE 5xx (the whole instance can 502 during an
outage) must never flip a working PAT to "expired" — it is recorded as
health_error and the API layer renders it as "unreachable" while the last
definitive verdict survives underneath.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("ctc.pat_health")

VALID = "valid"
EXPIRED = "expired"                # 401: expired, revoked, or otherwise rejected
FORBIDDEN = "forbidden"            # 403: token accepted but lacks permission
NO_ENTITLEMENT = "no_entitlement"  # token fine, but no Copilot premium quota

DEFINITIVE = {VALID, EXPIRED, FORBIDDEN, NO_ENTITLEMENT}


UNREACHABLE = "unreachable"  # display-only: last check errored; stored verdict kept


def display_status(health: dict | None) -> str | None:
    """Derive what the UI should show from a get_pat_health() row.

    An errored last check displays as "unreachable" without discarding the
    stored verdict; None means no PAT or never checked.
    """
    if not health:
        return None
    if health.get("error"):
        return UNREACHABLE
    return health.get("status")


def classify(status: int, body: dict | None) -> str | None:
    """Map a /copilot_internal/user response to a stored verdict.

    Returns None for indefinitive outcomes (5xx, unexpected codes): the caller
    must keep the previous verdict and record only health_error.
    """
    if status == 200:
        ent = ((body or {}).get("quota_snapshots", {})
               .get("premium_interactions", {}).get("entitlement"))
        return VALID if ent and ent > 0 else NO_ENTITLEMENT
    if status == 401:
        return EXPIRED
    if status == 403:
        return FORBIDDEN
    return None


class PatHealthChecker:
    """Checks all giver PATs on an interval and persists verdicts.

    fetch_raw(pat) -> (status:int, body:dict|None); network errors may raise.
    """

    def __init__(self, store, pat_for, fetch_raw, now, interval_s: int = 1200):
        self.store = store
        self.pat_for = pat_for
        self.fetch_raw = fetch_raw
        self.now = now
        self.interval_s = interval_s

    async def check_one(self, giver_id: str) -> str | None:
        pat = self.pat_for(giver_id)
        if pat is None:  # row deleted between listing and checking
            return None
        try:
            status, body = await self.fetch_raw(pat)
        except Exception as e:
            self.store.set_pat_health_error(giver_id, str(e) or type(e).__name__, self.now())
            return None
        verdict = classify(status, body)
        if verdict is None:
            self.store.set_pat_health_error(
                giver_id, f"/copilot_internal/user -> {status}", self.now())
            return None
        self.store.set_pat_health_ok(giver_id, verdict, self.now())
        if verdict == VALID:
            # Body is already in hand — refresh the quota snapshot so the
            # profile's stale-quota fallback shows recent numbers.
            pi = body.get("quota_snapshots", {}).get("premium_interactions", {})
            remaining = pi.get("remaining")
            self.store.set_giver_quota_snapshot(
                giver_id, int(pi.get("entitlement") or 0),
                max(0, int(remaining if remaining is not None else 0)),
                body.get("quota_reset_date"), self.now())
        return verdict

    async def run_once(self) -> None:
        for giver_id in self.store.list_giver_ids():
            try:
                await self.check_one(giver_id)
            except Exception:
                # One giver's failure (bad row, DB hiccup) must not skip the rest.
                log.exception("pat health check failed for giver %s", giver_id)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("pat health sweep failed")
            await asyncio.sleep(self.interval_s)
