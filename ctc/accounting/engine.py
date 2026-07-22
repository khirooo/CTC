from __future__ import annotations

import datetime
import uuid

from ..domain.config import NANO_PER_AIU
from ..domain.config import config as _env_config
from ..domain.rules import derive_status
from ..domain.types import (Bucket, Cycle, Event, Grant, GiverCycle, PoolContribution,
                            Request, RequestStatus, Role)
from ..store.accounting_store import AccountingStore
from .errors import InsufficientCredit, InvalidConsumption, InvalidPledge, RequestClosed

# reconcile_giver debounce/throttle tuning (module constants).
# A positive drift must persist across two observations at least CONFIRM_MIN_S
# apart before it is booked as BYPASS (fixes the watermark race that double-booked
# in-flight cost, P1-2). An observation older than CONFIRM_WINDOW_MAX is stale and
# restarts the debounce. The in-memory throttle skips repeat reconciles of the same
# (cycle, giver) within THROTTLE_S unless the caller passes immediate=True.
RECONCILE_CONFIRM_MIN_S = 90
RECONCILE_CONFIRM_WINDOW_MAX = 900
RECONCILE_THROTTLE_S = 60


class AccountingEngine:
    def __init__(self, store: AccountingStore, config=None):
        self.store = store
        self.conn = store.conn
        self.config = config if config is not None else _env_config
        # Per-engine in-memory throttle: (cycle_id, giver_id) -> last reconcile ts.
        # Best-effort; not shared across processes (proxy vs control plane each keep
        # their own), which is fine — it only suppresses redundant hot-path work.
        self._reconcile_seen: dict[tuple[str, str], int] = {}

    # --- balance reads ---
    def personal_remaining(self, cycle_id: str, giver_id: str) -> int:
        gc = self.store.get_giver_cycle(cycle_id, giver_id)
        if gc is None:
            return 0
        return (gc.quota - gc.pledge
                - self.store.own_consumed(cycle_id, giver_id)
                - self.store.bypass_consumed(cycle_id, giver_id)
                - self.store.granted_out(cycle_id, giver_id))

    def pledge_used(self, cycle_id: str, giver_id: str) -> int:
        # Pledge is consumed two ways: legacy auto-routed POOL events, and pool
        # fills booked as source='pool' grants (net of cancelled-request refunds).
        return (self.store.pool_consumed_from(cycle_id, giver_id)
                + self.store.pool_granted_out(cycle_id, giver_id))

    def pledge_remaining(self, cycle_id: str, giver_id: str) -> int:
        gc = self.store.get_giver_cycle(cycle_id, giver_id)
        if gc is None:
            return 0
        return max(0, gc.pledge - self.pledge_used(cycle_id, giver_id))

    def pool_available(self, cycle_id: str) -> int:
        # Pledged capacity plus received credit recipients returned to the pool.
        return (sum(self.pledge_remaining(cycle_id, gc.giver_id)
                    for gc in self.store.all_giver_cycles(cycle_id))
                + sum(cap for _, cap in self.store.contributions_with_capacity(cycle_id)))

    def grant_remaining(self, cycle_id: str, grant_id: str) -> int:
        g = self.store.get_grant(grant_id)
        if g is None:
            return 0
        r = self.store.get_request(g.request_id)
        if r is not None and r.cancelled_at is not None:
            return 0
        return (g.amount - self.store.grant_consumed(cycle_id, grant_id)
                - self.store.transferred_out(grant_id)
                - self.store.contributed_out(grant_id))

    def re_donatable_remaining(self, cycle_id: str, user_id: str) -> int:
        # Received credit this user can still re-donate or return to the pool.
        # Only original (origin-null) grants qualify — re-donation depth is
        # capped at 1 so the cancelled-charge accounting stays non-recursive.
        return sum(self.grant_remaining(cycle_id, g.id)
                   for g in self.store.grants_for_recipient(cycle_id, user_id)
                   if g.origin_grant_id is None)

    def donated_live(self, cycle_id: str, giver_id: str) -> int:
        return self.store.donated_live(cycle_id, giver_id)

    def consumed_total(self, cycle_id: str, user_id: str) -> int:
        return self.store.consumed_total(cycle_id, user_id)

    def pool_consumed_by(self, cycle_id: str, user_id: str) -> int:
        return self.store.pool_consumed_by(cycle_id, user_id)

    def consumed_from_others(self, cycle_id: str, user_id: str) -> int:
        return self.store.consumed_from_others(cycle_id, user_id)

    def givers_with_pool_capacity(self, cycle_id: str) -> list[tuple[str, int]]:
        out = []
        for gc in self.store.all_giver_cycles(cycle_id):
            rem = self.pledge_remaining(cycle_id, gc.giver_id)
            if rem > 0:
                out.append((gc.giver_id, rem))
        return out

    def active_grants(self, cycle_id: str, consumer_id: str) -> list[Grant]:
        return [g for g in self.store.grants_for_recipient(cycle_id, consumer_id)
                if self.grant_remaining(cycle_id, g.id) > 0]

    def request_status(self, request_id: str, now: int) -> RequestStatus:
        r = self.store.get_request(request_id)
        if r is None:
            raise InvalidConsumption("unknown request")
        funded = self.store.request_funded(request_id)
        return derive_status(funded, r.amount_needed, r.expires_at, now, r.cancelled_at)

    # --- cycle ---
    def start_cycle(self, cycle_id: str, label: str, starts_at: int, ends_at: int) -> Cycle:
        c = Cycle(cycle_id, label, starts_at, ends_at, "active")
        self.store.add_cycle(c)
        return c

    def current_cycle(self) -> Cycle | None:
        return self.store.active_cycle()

    @staticmethod
    def _month_cycle(now: int) -> Cycle:
        """Build (without persisting) the Cycle for the calendar month containing
        `now` (UTC). Used by both the no-cycle-gap path and rollover.

        `ends_at` is EXCLUSIVE — the first second of the *next* month — so that
        liveness (`now < ends_at`) covers the whole final day. The old inclusive
        23:59:59 end left a one-second window at month-end where a request would
        roll the cycle over onto itself and orphan the active cycle (P0-1)."""
        d = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
        start = int(datetime.datetime(d.year, d.month, 1, tzinfo=datetime.timezone.utc).timestamp())
        ny, nm = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        end = int(datetime.datetime(ny, nm, 1, tzinfo=datetime.timezone.utc).timestamp())
        return Cycle(f"cycle-{d.year:04d}-{d.month:02d}", d.strftime("%B %Y"), start, end, "active")

    def _open_month_cycle(self, now: int, prev_cycle_id: str | None) -> Cycle:
        """Insert-or-reactivate the calendar-month cycle for `now` and seed its
        giver_cycles from the connected PATs (quota = entitlement, prior pledge
        carried forward from `prev_cycle_id` and clamped to the new quota).

        MUST be called inside an open transaction (BEGIN IMMEDIATE). Rows that
        already exist in the target cycle are left untouched, so this is safe on
        reactivation and re-entry."""
        new = self._month_cycle(now)
        if self.store.get_cycle(new.id) is None:
            self.store.add_cycle(new)
        else:
            # Revisited a month whose cycle row already exists (rollover onto an
            # archived row, dormancy edge): reactivate rather than duplicate the id.
            self.conn.execute("UPDATE cycles SET status='active' WHERE id=?", (new.id,))
        # Seed giver_cycles from connected PATs: full entitlement as the new quota
        # (GitHub resets the real quota at the boundary too), prior pledge carried
        # forward and clamped. Skip PATs with no usable entitlement and rows that
        # already exist in this cycle. Seeding here (not only on the archive path)
        # is what fixes the gap path never seeding givers (P0-1).
        for row in self.conn.execute("SELECT user_id, entitlement FROM giver_pats"):
            ent = row["entitlement"]
            if not ent or ent <= 0:
                continue
            if self.store.get_giver_cycle(new.id, row["user_id"]) is not None:
                continue
            quota = int(ent) * NANO_PER_AIU
            prev_gc = (self.store.get_giver_cycle(prev_cycle_id, row["user_id"])
                       if prev_cycle_id else None)
            pledge = min(prev_gc.pledge, quota) if prev_gc else 0
            self.store.upsert_giver_cycle(GiverCycle(new.id, row["user_id"], quota, pledge))
            # Carry the burn baseline forward so early-cycle out-of-band burn isn't
            # swallowed by the lazy first-observation capture (the incident: GitHub
            # showed 2600 AIU burned, CTC only 800). The carried value is the prev
            # cycle's LAST-KNOWN GitHub burn — its baseline plus everything CTC
            # attributed there (own/pool/grant + already-booked bypass). While
            # GitHub still reports the old (pre-rollover) window, drift ≈ 0 so
            # nothing books; once GitHub resets its counter the existing
            # `github_burn < base` branch in reconcile_giver re-anchors to ~0.
            # Deliberately EXCLUDES prev pending_drift (unconfirmed — it may be
            # in-flight proxied cost that will be debited in the new cycle).
            if prev_gc is not None and prev_gc.burn_baseline is not None:
                carried = prev_gc.burn_baseline + self._tracked_burn(prev_cycle_id, row["user_id"])
                self.store.set_burn_baseline(new.id, row["user_id"], carried)
        return new

    def ensure_active_cycle(self, now: int) -> Cycle:
        """Guarantee a *live* active cycle exists. Behaviour:

        - Active cycle still within its window (`now < ends_at`) → return unchanged.
        - Otherwise (no active cycle, or it has ended) → roll over: open the cycle
          for the month containing `now` and seed giver_cycles from the connected
          PATs. Both the no-cycle gap (fresh/empty DB) and the month-ended case go
          through the same `BEGIN IMMEDIATE`-guarded path.

        Idempotent and concurrency-safe (in-transaction double-check + BEGIN
        IMMEDIATE), so it's safe to call on startup and on every request that needs
        the live cycle, from both the control plane and the proxy process."""
        cur = self.current_cycle()
        if cur is not None and now < cur.ends_at:
            return cur
        return self._roll_over(now)

    def _roll_over(self, now: int) -> Cycle:
        """Archive the ended active cycle (if any) and open the month-of-`now`
        cycle, seeding its giver_cycles from connected PATs. Runs in one
        transaction with an in-transaction re-check so a concurrent caller can't
        double-roll and a fresh-DB concurrent first request can't hit a bare-INSERT
        IntegrityError.

        Compute the target cycle BEFORE archiving: if it resolves to the live
        cycle's own id (a legacy inclusive-end row sitting in its final second),
        the month-of-`now` IS the live cycle — commit and return it unarchived
        rather than orphaning it (P0-1 boundary tolerance)."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            live = self.store.active_cycle()
            new = self._month_cycle(now)
            if live is not None:
                if now < live.ends_at:
                    # Another caller already rolled us into a live cycle.
                    self.conn.execute("COMMIT")
                    return live
                if new.id == live.id:
                    # Legacy inclusive-end row in its last second: the target
                    # month cycle is the live one. Don't archive/orphan it.
                    self.conn.execute("COMMIT")
                    return live
                self.conn.execute("UPDATE cycles SET status='archived' WHERE id=?", (live.id,))
            opened = self._open_month_cycle(now, live.id if live is not None else None)
            self.conn.execute("COMMIT")
            return opened
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    # --- pledge / quota ---
    def set_quota(self, cycle_id: str, giver_id: str, quota: int) -> None:
        if quota < 0:
            raise InvalidPledge("quota must be non-negative")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            consumed = self.pledge_used(cycle_id, giver_id)
            if quota < consumed:
                raise InvalidPledge(f"quota cannot be below already-consumed pledge ({consumed})")
            gc = self.store.get_giver_cycle(cycle_id, giver_id)
            pledge = min(gc.pledge, quota) if gc else 0
            self.store.upsert_giver_cycle(GiverCycle(cycle_id, giver_id, quota, pledge))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def set_pledge(self, cycle_id: str, giver_id: str, pledge: int) -> None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            gc = self.store.get_giver_cycle(cycle_id, giver_id)
            quota = gc.quota if gc else 0
            consumed = self.pledge_used(cycle_id, giver_id)
            if pledge < consumed or pledge > quota:
                raise InvalidPledge(f"pledge must be between {consumed} and {quota}")
            self.store.upsert_giver_cycle(GiverCycle(cycle_id, giver_id, quota, pledge))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    # --- marketplace ---
    def create_request(self, cycle_id: str, requester_id: str, role: Role, amount_needed: int,
                       reason: str, target: str | None, created_at: int, expires_at: int) -> Request:
        r = Request(uuid.uuid4().hex, cycle_id, requester_id, role, amount_needed,
                    reason, target, created_at, expires_at)
        self.store.add_request(r)
        return r

    def cancel_request(self, request_id: str, user_id: str, now: int) -> None:
        """Owner retracts their request. Soft delete: the row keeps its history,
        the marketplace list hides it, and the unconsumed part of every grant on
        it returns to the donors (personal or pool) via the derived balances."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            r = self.store.get_request(request_id)
            if r is None:
                raise InvalidConsumption("unknown request")
            if user_id != r.requester_id:
                raise InvalidConsumption("only the requester can cancel their request")
            if r.cancelled_at is not None:
                self.conn.execute("COMMIT")  # idempotent
                return
            funded = self.store.request_funded(request_id)
            status = derive_status(funded, r.amount_needed, r.expires_at, now, r.cancelled_at)
            if status == RequestStatus.FULFILLED:
                raise RequestClosed("request is fulfilled")
            self.store.cancel_request(request_id, now)
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def fund_request(self, request_id: str, donor_id: str, amount: int, now: int) -> Grant:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            r = self.store.get_request(request_id)
            if r is None:
                raise InvalidConsumption("unknown request")
            if donor_id == r.requester_id:
                raise InvalidConsumption("cannot fund your own request")
            funded = self.store.request_funded(request_id)
            status = derive_status(funded, r.amount_needed, r.expires_at, now, r.cancelled_at)
            if status in (RequestStatus.FULFILLED, RequestStatus.EXPIRED, RequestStatus.CANCELLED):
                raise RequestClosed(f"request is {status.value}")
            cap = min(amount, r.amount_needed - funded, self.personal_remaining(r.cycle_id, donor_id))
            if cap <= 0:
                raise InsufficientCredit("donor has no personal credit available")
            g = Grant(uuid.uuid4().hex, r.cycle_id, request_id, donor_id, r.requester_id, cap, now)
            self.store.add_grant(g)
            self.conn.execute("COMMIT")
            return g
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def fund_request_from_pool(self, request_id: str, actor_id: str, amount: int, now: int) -> list[Grant]:
        """Fill your OWN request from the shared pool. Only the requester may draw
        the pool onto their request; the credit comes from the pledged pool, not
        the actor. The fill is booked as source='pool' grants attributed to real
        pledging givers, largest pledge_remaining first, so consumption keeps
        routing through a concrete giver's PAT."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            r = self.store.get_request(request_id)
            if r is None:
                raise InvalidConsumption("unknown request")
            if actor_id != r.requester_id:
                raise InvalidConsumption("only the requester can fill their request from the pool")
            funded = self.store.request_funded(request_id)
            status = derive_status(funded, r.amount_needed, r.expires_at, now, r.cancelled_at)
            if status in (RequestStatus.FULFILLED, RequestStatus.EXPIRED, RequestStatus.CANCELLED):
                raise RequestClosed(f"request is {status.value}")
            cap = min(amount, r.amount_needed - funded, self.pool_available(r.cycle_id))
            if cap <= 0:
                raise InsufficientCredit("shared pool has no credit available")
            grants: list[Grant] = []
            left = cap
            # Recycled contributions drain first (oldest-first) so returned credit
            # moves on before donors' pledges are touched. A contribution draw
            # keeps the origin grant's donor for PAT routing and records the
            # chain (origin_grant_id + contribution_id) for the charge math.
            for pc, pc_cap in self.store.contributions_with_capacity(r.cycle_id):
                take = min(left, pc_cap)
                if take <= 0:
                    continue
                g = Grant(uuid.uuid4().hex, r.cycle_id, request_id, pc.donor_id,
                          r.requester_id, take, now, source="pool",
                          origin_grant_id=pc.origin_grant_id, contribution_id=pc.id)
                self.store.add_grant(g)
                grants.append(g)
                left -= take
                if left <= 0:
                    break
            givers = sorted(self.givers_with_pool_capacity(r.cycle_id),
                            key=lambda t: t[1], reverse=True)
            for giver_id, rem in givers:
                take = min(left, rem)
                if take <= 0:
                    continue
                g = Grant(uuid.uuid4().hex, r.cycle_id, request_id, giver_id,
                          r.requester_id, take, now, source="pool")
                self.store.add_grant(g)
                grants.append(g)
                left -= take
                if left <= 0:
                    break
            self.conn.execute("COMMIT")
            return grants
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def fund_request_from_received(self, request_id: str, actor_id: str, amount: int, now: int) -> list[Grant]:
        """Chip in to someone else's request using credit that was granted TO the
        actor. The child grants keep the origin grant's donor_id so consumption
        still routes to the original PAT holder; the actor is recorded as
        via_user_id (the human supporter shown on the card). Depth is capped at
        1: credit received from a re-donation or a pool draw of returned credit
        cannot be re-donated again."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            r = self.store.get_request(request_id)
            if r is None:
                raise InvalidConsumption("unknown request")
            if actor_id == r.requester_id:
                raise InvalidConsumption("cannot fund your own request")
            funded = self.store.request_funded(request_id)
            status = derive_status(funded, r.amount_needed, r.expires_at, now, r.cancelled_at)
            if status in (RequestStatus.FULFILLED, RequestStatus.EXPIRED, RequestStatus.CANCELLED):
                raise RequestClosed(f"request is {status.value}")
            cap = min(amount, r.amount_needed - funded,
                      self.re_donatable_remaining(r.cycle_id, actor_id))
            if cap <= 0:
                raise InsufficientCredit("no received credit available to re-donate")
            grants: list[Grant] = []
            left = cap
            for g in self.store.grants_for_recipient(r.cycle_id, actor_id):
                if g.origin_grant_id is not None:
                    continue  # depth cap: children can't be re-donated
                if g.donor_id == r.requester_id:
                    continue  # keep the donor≠requester invariant on the child
                take = min(left, self.grant_remaining(r.cycle_id, g.id))
                if take <= 0:
                    continue
                child = Grant(uuid.uuid4().hex, r.cycle_id, request_id, g.donor_id,
                              r.requester_id, take, now, source=g.source,
                              origin_grant_id=g.id, via_user_id=actor_id)
                self.store.add_grant(child)
                grants.append(child)
                left -= take
                if left <= 0:
                    break
            if not grants:
                # cap > 0 but every eligible grant was donor==requester
                raise InsufficientCredit("no received credit available to re-donate")
            self.conn.execute("COMMIT")
            return grants
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def return_received_to_pool(self, actor_id: str, cycle_id: str, amount: int, now: int) -> list[PoolContribution]:
        """Move unspent received credit into the shared pool. Booked as
        pool_contributions charged to the origin grants' donors; drawn by
        fund_request_from_pool before pledges."""
        if amount <= 0:
            raise InvalidConsumption("amount must be positive")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            left = min(amount, self.re_donatable_remaining(cycle_id, actor_id))
            if left <= 0:
                raise InsufficientCredit("no received credit available to return")
            out: list[PoolContribution] = []
            for g in self.store.grants_for_recipient(cycle_id, actor_id):
                if g.origin_grant_id is not None:
                    continue  # depth cap
                take = min(left, self.grant_remaining(cycle_id, g.id))
                if take <= 0:
                    continue
                pc = PoolContribution(uuid.uuid4().hex, cycle_id, actor_id, g.id,
                                      g.donor_id, take, now)
                self.store.add_pool_contribution(pc)
                out.append(pc)
                left -= take
                if left <= 0:
                    break
            self.conn.execute("COMMIT")
            return out
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def _tracked_burn(self, cycle_id: str, giver_id: str) -> int:
        """Total burn CTC has already attributed to this giver this cycle (own +
        pool + all grant draws from their PAT + already-booked bypass)."""
        return (self.store.own_consumed(cycle_id, giver_id)
                + self.store.pool_consumed_from(cycle_id, giver_id)
                + self.store.grants_consumed_from(cycle_id, giver_id)
                + self.store.bypass_consumed(cycle_id, giver_id))

    def reconcile_giver(self, cycle_id: str, giver_id: str,
                        live: dict | None, ts: int = 0,
                        immediate: bool = False) -> Event | None:
        """Book a giver's out-of-band (non-proxied) GitHub burn as a self-sourced
        BYPASS event so every events-based surface reflects reality.

        Drift is measured against a per-giver `burn_baseline` rather than against
        zero. The baseline is carried at rollover from the previous cycle's
        last-known GitHub burn (see `_open_month_cycle`), so early-cycle out-of-band
        burn is no longer swallowed before the first reconcile fires. The lazy
        first-observation capture remains only as a fallback for rows with no
        carryable history (absorbs the GitHub reset lag that used to re-book a whole
        prior month at rollover, P1-3). A positive drift is confirmed across two
        observations >= CONFIRM_MIN_S apart before it is booked (a single in-flight
        cost no longer double-books as BYPASS, P1-2).

        The common case — drift <= 0 with a baseline already set — takes NO write
        lock (P1-11): only baseline capture, the debounce record, and the final
        booking open a short BEGIN IMMEDIATE, each re-reading state in-txn so
        concurrent callers (proxy + control plane) cannot double-write.

        immediate=True skips the debounce and books confirmed drift right away
        (onboarding books pre-connect burn; the proxy books a confirmed 402). An
        immediate call also bypasses the in-memory throttle."""
        if not live:
            return None
        ent, rem = live.get("entitlement"), live.get("remaining")
        if ent is None or rem is None or int(ent) < 0 or int(rem) < 0:  # unknown / unlimited(-1) / corrupt
            return None
        github_burn = (int(ent) - int(rem)) * NANO_PER_AIU

        # In-memory throttle: skip redundant hot-path reconciles of the same giver.
        if not immediate:
            key = (cycle_id, giver_id)
            last = self._reconcile_seen.get(key)
            if last is not None and 0 <= ts - last < RECONCILE_THROTTLE_S:
                return None
            self._reconcile_seen[key] = ts

        # Lock-free read of current state.
        gc = self.store.get_giver_cycle(cycle_id, giver_id)
        tracked = self._tracked_burn(cycle_id, giver_id)
        baseline = gc.burn_baseline if gc else None

        # First observation with no baseline (and not the immediate book-everything
        # path): capture the baseline and book nothing. This absorbs whatever GitHub
        # already reported as burned before CTC started tracking this cycle.
        if baseline is None and not immediate:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.store.set_burn_baseline(cycle_id, giver_id, max(0, github_burn - tracked))
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            return None

        base = baseline if baseline is not None else 0

        # GitHub burn fell below the baseline → quota reset upstream. Re-anchor the
        # baseline and drop any pending observation; book nothing.
        if github_burn < base:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.store.set_burn_baseline(cycle_id, giver_id, max(0, github_burn - tracked))
                self.store.set_pending_drift(cycle_id, giver_id, None, None)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            return None

        drift = github_burn - base - tracked
        if drift <= 0:
            # Common case: nothing to book. No lock. Clear a stale pending only if
            # one is set (rare), so a transient drift doesn't linger forever.
            if gc is not None and gc.pending_drift is not None:
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.store.set_pending_drift(cycle_id, giver_id, None, None)
                    self.conn.execute("COMMIT")
                except BaseException:
                    self.conn.execute("ROLLBACK")
                    raise
            return None

        if immediate:
            return self._book_bypass(cycle_id, giver_id, github_burn, ts)

        # Two-observation debounce (drift > 0).
        pending, pending_at = (gc.pending_drift, gc.pending_drift_at) if gc else (None, None)
        if pending is None or pending_at is None:
            # First observation: record it, book nothing yet.
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.store.set_pending_drift(cycle_id, giver_id, drift, ts)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            return None

        age = ts - pending_at
        if age < RECONCILE_CONFIRM_MIN_S:
            # Too soon to confirm; keep the earlier observation (don't reset clock).
            return None
        if age > RECONCILE_CONFIRM_WINDOW_MAX:
            # Stale observation: treat this as a fresh first observation.
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.store.set_pending_drift(cycle_id, giver_id, drift, ts)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            return None

        # Confirmed across two observations: book the conservative min(obs1, obs2).
        return self._book_bypass(cycle_id, giver_id, github_burn, ts, cap=min(pending, drift))

    def _book_bypass(self, cycle_id: str, giver_id: str, github_burn: int, ts: int,
                     cap: int | None = None) -> Event | None:
        """Book confirmed out-of-band drift as a BYPASS event inside BEGIN
        IMMEDIATE, recomputing drift in-txn so a concurrent writer that already
        booked part of it can't be double-counted. Clears the pending observation.
        `cap` bounds the amount booked (the debounced min of two observations)."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            gc = self.store.get_giver_cycle(cycle_id, giver_id)
            base = gc.burn_baseline if (gc and gc.burn_baseline is not None) else 0
            tracked = self._tracked_burn(cycle_id, giver_id)
            drift = github_burn - base - tracked
            if cap is not None:
                drift = min(drift, cap)
            self.store.set_pending_drift(cycle_id, giver_id, None, None)
            if drift <= 0:
                self.conn.execute("COMMIT")
                return None
            event = Event(uuid.uuid4().hex, cycle_id, ts, giver_id, giver_id,
                          Bucket.BYPASS, None, drift)
            self.store.add_event(event)
            self.conn.execute("COMMIT")
            return event
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def record_consumption(
        self,
        cycle_id: str,
        consumer_id: str,
        source_giver_id: str,
        bucket: Bucket,
        credits: int,
        grant_id: str | None = None,
        ts: int = 0,
        allow_overshoot: bool = False,
    ) -> Event:
        if credits <= 0:
            raise InvalidConsumption("credits must be positive")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if bucket == Bucket.OWN:
                if consumer_id != source_giver_id:
                    raise InvalidConsumption("own consumption must be self-sourced")
                if not allow_overshoot and credits > self.personal_remaining(cycle_id, source_giver_id):
                    raise InsufficientCredit("exceeds personal credit")
            elif bucket == Bucket.BYPASS:
                # Out-of-band burn reconciled from GitHub's real quota. Self-sourced,
                # and never headroom-checked: the spend already happened upstream.
                if consumer_id != source_giver_id:
                    raise InvalidConsumption("bypass consumption must be self-sourced")
            elif bucket == Bucket.POOL:
                # Legacy auto-routed pool draws; new pool fills flow as GRANTs.
                if not allow_overshoot and credits > self.pledge_remaining(cycle_id, source_giver_id):
                    raise InsufficientCredit("exceeds giver pledge")
            elif bucket == Bucket.GRANT:
                g = self.store.get_grant(grant_id) if grant_id else None
                if g is None:
                    raise InvalidConsumption("unknown grant")
                if g.donor_id != source_giver_id:
                    raise InvalidConsumption("grant donor mismatch")
                if not allow_overshoot and credits > self.grant_remaining(cycle_id, grant_id):
                    raise InsufficientCredit("exceeds grant")
            else:
                raise InvalidConsumption(f"unknown bucket {bucket!r}")

            event = Event(uuid.uuid4().hex, cycle_id, ts, consumer_id,
                          source_giver_id, bucket, grant_id, credits)
            self.store.add_event(event)
            self.conn.execute("COMMIT")
            return event
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
