"""Periodic giver-PAT health checks.

A PAT is validated once at upload and then silently rots: when it expires or
is revoked, the CLI just starts failing and the owner never learns why. This
module re-checks every stored PAT against GET /copilot_internal/user and
persists a verdict on the giver_pats row so the profile and admin panel can
display it.

The verdict itself is routing-neutral: attribution is untouched (the proxy
already fails over at request time). Only DEFINITIVE outcomes overwrite the
stored status; a network error or GHE 5xx (the whole instance can 502 during an
outage) must never flip a working PAT to "expired" — it is recorded as
health_error and the API layer renders it as "unreachable" while the last
definitive verdict survives underneath.

The sweep is no longer purely display: when an `engine` is supplied it also
feeds each VALID giver's live quota into `AccountingEngine.reconcile_giver`, so
out-of-band GitHub burn (usage outside the proxy) is detected and booked as
BYPASS even for a giver with zero proxy/profile activity. Because the sweep
interval (default 1200s) exceeds the engine's confirm window (900s), a single
periodic observation can never confirm a drift; `run_once` therefore runs in two
phases — a first sweep that records pending drift, then a short `confirm_delay_s`
sleep and a fresh re-check of just the pending givers so the two observations
land inside the confirm window. With `engine=None` the sweep behaves exactly as
before (verdicts + quota snapshots only).
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

    def __init__(self, store, pat_for, fetch_raw, now, interval_s: int = 1200,
                 engine=None, confirm_delay_s: int = 95, sleep=asyncio.sleep):
        self.store = store
        self.pat_for = pat_for
        self.fetch_raw = fetch_raw
        self.now = now
        self.interval_s = interval_s
        # Optional accounting engine: when set, the sweep also reconciles each
        # VALID giver's out-of-band burn (see module docstring). None = exactly
        # the legacy display-only behaviour.
        self.engine = engine
        self.confirm_delay_s = confirm_delay_s
        self.sleep = sleep

    async def check_one(self, giver_id: str, cycle_id: str | None = None) -> str | None:
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
            # Feed the same live numbers into the accounting reconcile so
            # out-of-band burn is booked. A reconcile failure must never lose the
            # health verdict already persisted above.
            if self.engine is not None:
                if cycle_id is None:
                    cycle_id = self.engine.ensure_active_cycle(self.now()).id
                self._reconcile_valid(cycle_id, giver_id, body)
        return verdict

    def _reconcile_valid(self, cycle_id: str, giver_id: str, body: dict) -> None:
        pi = body.get("quota_snapshots", {}).get("premium_interactions", {})
        live = {"entitlement": pi.get("entitlement"), "remaining": pi.get("remaining")}
        try:
            self.engine.reconcile_giver(cycle_id, giver_id, live, ts=self.now())
        except Exception:
            log.exception("reconcile failed for giver %s (health verdict kept)", giver_id)

    async def run_once(self) -> None:
        # Phase 1: sweep every giver (verdict + snapshot, and — when an engine is
        # wired — a first reconcile observation that may record pending drift).
        cycle_id = self.engine.ensure_active_cycle(self.now()).id if self.engine else None
        for giver_id in self.store.list_giver_ids():
            try:
                await self.check_one(giver_id, cycle_id=cycle_id)
            except Exception:
                # One giver's failure (bad row, DB hiccup) must not skip the rest.
                log.exception("pat health check failed for giver %s", giver_id)

        if self.engine is None:
            return

        # Phase 2: the sweep interval is wider than the engine's confirm window,
        # so a pending drift recorded in phase 1 can never be confirmed by the
        # NEXT periodic sweep. Re-check just the pending givers after a short delay
        # (>= CONFIRM_MIN_S) so the second observation lands inside the window.
        pending = [g for g in self.store.list_giver_ids()
                   if (gc := self.engine.store.get_giver_cycle(cycle_id, g))
                   and gc.pending_drift is not None]
        if not pending:
            return
        await self.sleep(self.confirm_delay_s)
        # The month may have rolled over during the sleep — re-resolve the cycle.
        cycle_id = self.engine.ensure_active_cycle(self.now()).id
        for giver_id in pending:
            try:
                await self.check_one(giver_id, cycle_id=cycle_id)
            except Exception:
                log.exception("pat health confirm check failed for giver %s", giver_id)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("pat health sweep failed")
            await asyncio.sleep(self.interval_s)
