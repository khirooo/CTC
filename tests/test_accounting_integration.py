"""Integration tests covering cross-cycle isolation, pledge/quota guard-rails."""
import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.errors import InvalidPledge
from ctc.domain.types import Bucket, Cycle, Event, Grant, GiverCycle, Request, Role

CYC_ACTIVE = "2026-06"
CYC_ARCHIVED = "2026-05"
GIVER = "g1"
CONSUMER = "c1"


def _engine() -> AccountingEngine:
    conn = connect()
    init_db(conn)
    return AccountingEngine(AccountingStore(conn))


# ── helpers ──────────────────────────────────────────────────────────────────

def _seed_cycle(store: AccountingStore, cycle_id: str, status: str) -> None:
    store.add_cycle(Cycle(cycle_id, cycle_id, 0, 1_000_000, status))
    store.upsert_giver_cycle(GiverCycle(cycle_id, GIVER, 1000, 300))
    # pool draw of 100 against giver in this cycle
    store.add_event(Event(f"ev-pool-{cycle_id}", cycle_id, 1, CONSUMER, GIVER, Bucket.POOL, None, 100))
    # grant of 200 to consumer
    store.add_request(Request(f"req-{cycle_id}", cycle_id, CONSUMER, Role.CONSUMER, 200, "need", None, 0, 1_000_000))
    store.add_grant(Grant(f"gr-{cycle_id}", cycle_id, f"req-{cycle_id}", GIVER, CONSUMER, 200, 2))
    store.add_event(Event(f"ev-grant-{cycle_id}", cycle_id, 3, CONSUMER, GIVER, Bucket.GRANT, f"gr-{cycle_id}", 60))


# ── Test 1: cross-cycle isolation ─────────────────────────────────────────────

class TestCrossCycleIsolation:
    def setup_method(self):
        self.e = _engine()
        _seed_cycle(self.e.store, CYC_ACTIVE, "active")
        _seed_cycle(self.e.store, CYC_ARCHIVED, "archived")

    def test_personal_remaining_isolated(self):
        active = self.e.personal_remaining(CYC_ACTIVE, GIVER)
        archived = self.e.personal_remaining(CYC_ARCHIVED, GIVER)
        # Each cycle: quota 1000 - pledge 300 - own 0 - grant out 200 = 500
        assert active == archived == 500

        # They must be independent: fetching one does not change the other
        assert self.e.personal_remaining(CYC_ACTIVE, GIVER) == active

    def test_pledge_remaining_isolated(self):
        # Each cycle: pledge 300 - pool consumed 100 = 200
        assert self.e.pledge_remaining(CYC_ACTIVE, GIVER) == 200
        assert self.e.pledge_remaining(CYC_ARCHIVED, GIVER) == 200

    def test_allowance_remaining_isolated(self):
        # Each cycle: free_allowance - 100 pool = (allowance - 100)
        # They should be equal and independent; crucially active cycle value must
        # NOT include the archived cycle's consumption.
        active_val = self.e.allowance_remaining(CYC_ACTIVE, CONSUMER)
        archived_val = self.e.allowance_remaining(CYC_ARCHIVED, CONSUMER)
        assert active_val == archived_val  # symmetric seed

        # Sanity: if we add another pool draw in active cycle only, they diverge
        self.e.store.add_event(
            Event("ev-extra", CYC_ACTIVE, 5, CONSUMER, GIVER, Bucket.POOL, None, 50)
        )
        assert self.e.allowance_remaining(CYC_ACTIVE, CONSUMER) == active_val - 50
        assert self.e.allowance_remaining(CYC_ARCHIVED, CONSUMER) == archived_val

    def test_donated_live_isolated(self):
        # Each cycle: pool 100 + grant 60 = 160 donated by giver to others
        assert self.e.donated_live(CYC_ACTIVE, GIVER) == 160
        assert self.e.donated_live(CYC_ARCHIVED, GIVER) == 160

        # Modify archived only; active must be unchanged
        self.e.store.add_event(
            Event("ev-extra2", CYC_ARCHIVED, 6, CONSUMER, GIVER, Bucket.POOL, None, 40)
        )
        assert self.e.donated_live(CYC_ACTIVE, GIVER) == 160
        assert self.e.donated_live(CYC_ARCHIVED, GIVER) == 200

    def test_consumed_total_isolated(self):
        # Each cycle: pool 100 + grant 60 = 160
        assert self.e.consumed_total(CYC_ACTIVE, CONSUMER) == 160
        assert self.e.consumed_total(CYC_ARCHIVED, CONSUMER) == 160


# ── Test 2: set_pledge below already-consumed is rejected ─────────────────────

class TestSetPledgeGuard:
    def setup_method(self):
        self.e = _engine()
        self.e.start_cycle(CYC_ACTIVE, "June", 0, 1_000_000)
        self.e.set_quota(CYC_ACTIVE, GIVER, 1000)
        self.e.set_pledge(CYC_ACTIVE, GIVER, 300)
        # Record a pool consumption of 250 sourced from giver
        self.e.store.add_event(
            Event("ev-pool", CYC_ACTIVE, 1, CONSUMER, GIVER, Bucket.POOL, None, 250)
        )

    def test_set_pledge_below_consumed_raises(self):
        with pytest.raises(InvalidPledge):
            self.e.set_pledge(CYC_ACTIVE, GIVER, 100)  # 100 < 250 consumed

    def test_set_pledge_exactly_at_consumed_succeeds(self):
        self.e.set_pledge(CYC_ACTIVE, GIVER, 260)  # 260 >= 250, <= 1000
        gc = self.e.store.get_giver_cycle(CYC_ACTIVE, GIVER)
        assert gc.pledge == 260

    def test_set_pledge_above_quota_raises(self):
        with pytest.raises(InvalidPledge):
            self.e.set_pledge(CYC_ACTIVE, GIVER, 1001)  # > quota 1000


# ── Test 3: set_quota below consumed is rejected ──────────────────────────────

class TestSetQuotaGuard:
    def setup_method(self):
        self.e = _engine()
        self.e.start_cycle(CYC_ACTIVE, "June", 0, 1_000_000)
        self.e.set_quota(CYC_ACTIVE, GIVER, 1000)
        self.e.set_pledge(CYC_ACTIVE, GIVER, 300)
        # Record a pool consumption of 250 sourced from giver
        self.e.store.add_event(
            Event("ev-pool", CYC_ACTIVE, 1, CONSUMER, GIVER, Bucket.POOL, None, 250)
        )

    def test_set_quota_below_consumed_raises(self):
        with pytest.raises(InvalidPledge):
            self.e.set_quota(CYC_ACTIVE, GIVER, 200)  # 200 < 250 consumed

    def test_set_quota_exactly_at_consumed_succeeds(self):
        self.e.set_quota(CYC_ACTIVE, GIVER, 250)  # exactly at consumed
        gc = self.e.store.get_giver_cycle(CYC_ACTIVE, GIVER)
        assert gc.quota == 250
        # pledge should be capped at new quota (was 300, now capped to 250)
        assert gc.pledge == 250

    def test_set_quota_above_consumed_succeeds(self):
        self.e.set_quota(CYC_ACTIVE, GIVER, 500)
        gc = self.e.store.get_giver_cycle(CYC_ACTIVE, GIVER)
        assert gc.quota == 500
        assert gc.pledge == 300  # pledge unchanged since 300 <= 500
