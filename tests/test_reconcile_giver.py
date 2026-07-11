from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.domain.types import Cycle, GiverCycle, Bucket
from ctc.domain.config import NANO_PER_AIU as N

CYC = "2026-06"


def seed():
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 4000 * N, 0))  # quota = entitlement ceiling
    return AccountingEngine(s), s


def seed_anchored():
    """Seed with burn_baseline anchored at 0 (mimics onboarding), so the first
    real observation is measured as drift rather than absorbed into the baseline."""
    e, s = seed()
    s.set_burn_baseline(CYC, "g1", 0)
    return e, s


# --------------------------------------------------------------------------- #
# Baseline capture (P1-3): the first observation anchors the baseline, books
# nothing, so a rollover / reset-lag github_burn isn't re-booked as one big BYPASS.
# --------------------------------------------------------------------------- #
def test_first_observation_captures_baseline_books_nothing():
    e, s = seed()
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1)
    assert ev is None
    assert s.bypass_consumed(CYC, "g1") == 0
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.burn_baseline == 2500 * N          # github_burn(2500) - tracked(0)


def test_drift_measured_relative_to_baseline():
    e, s = seed()
    # baseline captured at 2500 (nothing tracked yet)
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1)
    # another 500 burned upstream → drift 500, confirmed across two observations
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1000}, ts=1000)   # obs1
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1000}, ts=1100)  # obs2
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 500 * N   # only the post-baseline drift


def test_github_reset_re_anchors_baseline():
    e, s = seed()
    s.set_burn_baseline(CYC, "g1", 500 * N)      # some prior baseline
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1000}, ts=1000)  # burn 3000, drift 2500 pending
    # GitHub quota resets: burn drops below the baseline (remaining jumps up)
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 4000}, ts=2000)  # burn 0 < 500
    assert ev is None
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.burn_baseline == 0                 # re-anchored to github_burn(0) - tracked(0)
    assert gc.pending_drift is None              # stale pending cleared


# --------------------------------------------------------------------------- #
# Two-observation debounce (P1-2)
# --------------------------------------------------------------------------- #
def test_debounce_single_observation_books_nothing():
    e, s = seed_anchored()
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)
    assert ev is None
    assert s.bypass_consumed(CYC, "g1") == 0
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.pending_drift == 2500 * N and gc.pending_drift_at == 1000


def test_debounce_two_observations_books_min():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)   # drift 2500
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1200}, ts=1100)  # drift 2800
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 2500 * N   # min(2500, 2800)
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.pending_drift is None


def test_debounce_books_min_when_second_is_smaller():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1200}, ts=1000)   # drift 2800
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1100)  # drift 2500
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 2500 * N   # min(2800, 2500)


def test_debounce_holds_between_throttle_and_confirm_min():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)   # obs1
    # 80s later: past the 60s throttle but below CONFIRM_MIN_S=90 → not yet confirmed
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1080)
    assert ev is None
    assert s.bypass_consumed(CYC, "g1") == 0
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.pending_drift == 2500 * N and gc.pending_drift_at == 1000   # obs1 preserved


def test_debounce_stale_observation_restarts():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)   # obs1
    # far beyond CONFIRM_WINDOW_MAX=900 → obs1 is stale, this becomes a fresh obs1
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1200}, ts=5000)
    assert ev is None
    assert s.bypass_consumed(CYC, "g1") == 0
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.pending_drift == 2800 * N and gc.pending_drift_at == 5000


# --------------------------------------------------------------------------- #
# immediate=True: skip debounce + throttle, book confirmed drift now.
# --------------------------------------------------------------------------- #
def test_immediate_books_drift_as_bypass():
    e, s = seed_anchored()
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1, immediate=True)
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 2500 * N


def test_immediate_excludes_tracked_proxied_burn():
    e, s = seed_anchored()
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 200 * N, ts=1)
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=2, immediate=True)
    assert s.bypass_consumed(CYC, "g1") == 2300 * N   # 2500 - 200 tracked own


def test_immediate_captures_no_baseline_treats_as_zero():
    # No baseline set (None): immediate books everything above tracked (this is the
    # confirmed-402 / reconcile_exhausted case where the giver really is spent).
    e, s = seed()
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 0}, ts=1, immediate=True)
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 4000 * N


def test_immediate_is_idempotent():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1, immediate=True)
    assert s.bypass_consumed(CYC, "g1") == 2500 * N
    second = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=2, immediate=True)
    assert second is None                        # drift now 0 (tracked includes the bypass)
    assert s.bypass_consumed(CYC, "g1") == 2500 * N


def test_immediate_bypasses_throttle():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)   # records pending
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000, immediate=True)
    assert ev is not None and s.bypass_consumed(CYC, "g1") == 2500 * N


# --------------------------------------------------------------------------- #
# Throttle (P1-11): a repeat within 60s is skipped entirely (no state change).
# --------------------------------------------------------------------------- #
def test_throttle_skips_repeat_within_window():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)   # obs1 recorded
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1000}, ts=1030)  # +30s
    assert ev is None
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.pending_drift == 2500 * N and gc.pending_drift_at == 1000   # untouched


# --------------------------------------------------------------------------- #
# No-op guards (fire before throttle/baseline for unusable input).
# --------------------------------------------------------------------------- #
def test_reconcile_noop_on_missing_quota():
    e, s = seed()
    assert e.reconcile_giver(CYC, "g1", None) is None
    assert e.reconcile_giver(CYC, "g1", {"entitlement": None, "remaining": 5}) is None
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": None}) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_reconcile_noop_on_unlimited_sentinel():
    e, s = seed()
    assert e.reconcile_giver(CYC, "g1", {"entitlement": -1, "remaining": 0}) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_reconcile_noop_on_negative_remaining():
    e, s = seed()
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": -5}) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_reconcile_never_books_when_tracked_exceeds_github():
    e, s = seed_anchored()
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 3000 * N, ts=1)
    # github says only 2500 burned (lag); drift negative → never write, never reverse
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000) is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_zero_drift_does_not_book_and_clears_stale_pending():
    e, s = seed_anchored()
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1500}, ts=1000)   # pending 2500
    # burn drops back to baseline → drift 0; a lingering pending is cleared
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 4000}, ts=2000)
    assert ev is None
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.pending_drift is None
    assert s.bypass_consumed(CYC, "g1") == 0
