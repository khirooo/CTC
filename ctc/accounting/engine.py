from __future__ import annotations

import calendar
import datetime
import uuid

from ..domain.config import NANO_PER_AIU
from ..domain.config import config as _env_config
from ..domain.rules import derive_status
from ..domain.types import Bucket, Cycle, Event, Grant, GiverCycle, Request, RequestStatus, Role
from ..store.accounting_store import AccountingStore
from .errors import InsufficientCredit, InvalidConsumption, InvalidPledge, RequestClosed


class AccountingEngine:
    def __init__(self, store: AccountingStore, config=None):
        self.store = store
        self.conn = store.conn
        self.config = config if config is not None else _env_config

    # --- balance reads ---
    def personal_remaining(self, cycle_id: str, giver_id: str) -> int:
        gc = self.store.get_giver_cycle(cycle_id, giver_id)
        if gc is None:
            return 0
        return (gc.quota - gc.pledge
                - self.store.own_consumed(cycle_id, giver_id)
                - self.store.bypass_consumed(cycle_id, giver_id)
                - self.store.granted_out(cycle_id, giver_id))

    def pledge_remaining(self, cycle_id: str, giver_id: str) -> int:
        gc = self.store.get_giver_cycle(cycle_id, giver_id)
        if gc is None:
            return 0
        return max(0, gc.pledge - self.store.pool_consumed_from(cycle_id, giver_id))

    def pool_available(self, cycle_id: str) -> int:
        return sum(self.pledge_remaining(cycle_id, gc.giver_id)
                   for gc in self.store.all_giver_cycles(cycle_id))

    def allowance_remaining(self, cycle_id: str, consumer_id: str) -> int:
        return max(0, self.config.free_allowance - self.store.pool_consumed_by(cycle_id, consumer_id))

    def grant_remaining(self, cycle_id: str, grant_id: str) -> int:
        g = self.store.get_grant(grant_id)
        if g is None:
            return 0
        return g.amount - self.store.grant_consumed(cycle_id, grant_id)

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
        return derive_status(funded, r.amount_needed, r.expires_at, now)

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
        `now` (UTC). Used by both the no-cycle-gap path and rollover."""
        d = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
        start = int(datetime.datetime(d.year, d.month, 1, tzinfo=datetime.timezone.utc).timestamp())
        last = calendar.monthrange(d.year, d.month)[1]
        end = int(datetime.datetime(d.year, d.month, last, 23, 59, 59,
                                    tzinfo=datetime.timezone.utc).timestamp())
        return Cycle(f"cycle-{d.year:04d}-{d.month:02d}", d.strftime("%B %Y"), start, end, "active")

    def ensure_active_cycle(self, now: int) -> Cycle:
        """Guarantee a *live* active cycle exists. Behaviour:

        - No active cycle  → open the current calendar month's cycle (the
          no-cycle gap; e.g. a fresh/empty DB on startup).
        - Active cycle still within its window (`now < ends_at`) → return unchanged.
        - Active cycle has ended (`now >= ends_at`) → roll over: archive it, open
          the cycle for the month containing `now`, and seed giver_cycles from the
          connected PATs (quota = entitlement, pledge carried forward & clamped).

        Idempotent and concurrency-safe (in-transaction double-check + BEGIN
        IMMEDIATE), so it's safe to call on startup and on every request that needs
        the live cycle, from both the control plane and the proxy process."""
        cur = self.current_cycle()
        if cur is not None and now < cur.ends_at:
            return cur
        if cur is not None:
            return self._roll_over(now)
        c = self._month_cycle(now)
        return self.start_cycle(c.id, c.label, c.starts_at, c.ends_at)

    def _roll_over(self, now: int) -> Cycle:
        """Archive the ended active cycle, open the month-of-`now` cycle, and seed
        its giver_cycles from connected PATs. All in one transaction with an
        in-transaction re-check so a concurrent caller can't double-roll."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            live = self.store.active_cycle()
            if live is None:
                # Someone archived prev but left no active cycle — open the gap.
                new = self._month_cycle(now)
                if self.store.get_cycle(new.id) is None:
                    self.store.add_cycle(new)
                else:
                    self.conn.execute("UPDATE cycles SET status='active' WHERE id=?", (new.id,))
                self.conn.execute("COMMIT")
                return new
            if now < live.ends_at:
                # Another caller already rolled us into a live cycle.
                self.conn.execute("COMMIT")
                return live

            # 1. archive the ended cycle
            self.conn.execute("UPDATE cycles SET status='archived' WHERE id=?", (live.id,))

            # 2. open the cycle for the month containing `now`
            new = self._month_cycle(now)
            existing = self.store.get_cycle(new.id)
            if existing is None:
                self.store.add_cycle(new)
            elif existing.id != live.id:
                # Revisited a month whose cycle row already exists (e.g. dormancy
                # edge): reactivate it rather than inserting a duplicate id.
                self.conn.execute("UPDATE cycles SET status='active' WHERE id=?", (new.id,))

            # 3. seed giver_cycles from connected PATs: full entitlement as the
            #    new quota (GitHub resets the real quota at the boundary too),
            #    prior pledge carried forward and clamped to the new quota.
            for row in self.conn.execute("SELECT user_id, entitlement FROM giver_pats"):
                ent = row["entitlement"]
                if not ent or ent <= 0:
                    continue
                quota = int(ent) * NANO_PER_AIU
                prev_gc = self.store.get_giver_cycle(live.id, row["user_id"])
                pledge = min(prev_gc.pledge, quota) if prev_gc else 0
                self.store.upsert_giver_cycle(GiverCycle(new.id, row["user_id"], quota, pledge))

            self.conn.execute("COMMIT")
            return new
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    # --- pledge / quota ---
    def set_quota(self, cycle_id: str, giver_id: str, quota: int) -> None:
        if quota < 0:
            raise InvalidPledge("quota must be non-negative")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            consumed = self.store.pool_consumed_from(cycle_id, giver_id)
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
            consumed = self.store.pool_consumed_from(cycle_id, giver_id)
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

    def fund_request(self, request_id: str, donor_id: str, amount: int, now: int) -> Grant:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            r = self.store.get_request(request_id)
            if r is None:
                raise InvalidConsumption("unknown request")
            if donor_id == r.requester_id:
                raise InvalidConsumption("cannot fund your own request")
            funded = self.store.request_funded(request_id)
            status = derive_status(funded, r.amount_needed, r.expires_at, now)
            if status in (RequestStatus.FULFILLED, RequestStatus.EXPIRED):
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

    def reconcile_giver(self, cycle_id: str, giver_id: str,
                        live: dict | None, ts: int = 0) -> Event | None:
        """Book a giver's out-of-band (non-proxied) GitHub burn as a self-sourced
        BYPASS event so every events-based surface reflects reality. Idempotent:
        only the positive delta over already-booked bypass is written (watermark =
        sum of existing bypass events). No-op on unusable/unlimited/unknown quota
        or when CTC has tracked at least as much as GitHub reports. The read of the
        four sums and the insert run in one BEGIN IMMEDIATE so concurrent callers
        (proxy + control plane) cannot double-write."""
        if not live:
            return None
        ent, rem = live.get("entitlement"), live.get("remaining")
        if ent is None or rem is None or int(ent) < 0 or int(rem) < 0:  # unknown / unlimited(-1) / corrupt
            return None
        github_burn = (int(ent) - int(rem)) * NANO_PER_AIU
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            tracked = (self.store.own_consumed(cycle_id, giver_id)
                       + self.store.pool_consumed_from(cycle_id, giver_id)
                       + self.store.grants_consumed_from(cycle_id, giver_id)
                       + self.store.bypass_consumed(cycle_id, giver_id))
            drift = github_burn - tracked
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
                if not allow_overshoot and credits > self.pledge_remaining(cycle_id, source_giver_id):
                    raise InsufficientCredit("exceeds giver pledge")
                if not allow_overshoot and credits > self.allowance_remaining(cycle_id, consumer_id):
                    raise InsufficientCredit("exceeds consumer allowance")
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
