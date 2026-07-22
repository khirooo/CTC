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


# --------------------------------------------------------------------------- #
# Carried-baseline incident regressions (D2). At rollover the new cycle's
# burn_baseline is seeded with the prev cycle's last-known GitHub burn instead of
# being left None. These exercise reconcile_giver against such a carried baseline.
# --------------------------------------------------------------------------- #
def test_carried_baseline_stale_phase_books_nothing():
    # Post-rollover, GitHub still reports the OLD (pre-reset) window. The carried
    # baseline matches it exactly → drift 0 across both observations, nothing books.
    e, s = seed()
    s.set_burn_baseline(CYC, "g1", 2600 * N)          # carried last-known burn
    ev1 = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1400}, ts=1000)  # burn 2600
    ev2 = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1400}, ts=1100)
    assert ev1 is None and ev2 is None
    assert s.bypass_consumed(CYC, "g1") == 0
    assert s.get_giver_cycle(CYC, "g1").pending_drift is None


def test_carried_baseline_stale_phase_with_new_proxied_usage_no_double_count():
    # During the stale phase the giver also burns 300 THROUGH the proxy: both
    # github_burn and tracked rise by 300, so drift stays 0 — no double count.
    e, s = seed()
    s.set_burn_baseline(CYC, "g1", 2600 * N)
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 300 * N, ts=500)
    ev1 = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1100}, ts=1000)  # burn 2900
    ev2 = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1100}, ts=1100)
    assert ev1 is None and ev2 is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_carried_baseline_reset_reanchors_then_attributes():
    # GitHub finally resets its counter (burn drops below the carried baseline):
    # the re-anchor branch fires, then later out-of-band burn confirms and books.
    e, s = seed()
    s.set_burn_baseline(CYC, "g1", 2600 * N)
    # reset: burn drops to 50 (< carried 2600) → re-anchor to the new floor.
    assert e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 3950}, ts=1000) is None
    assert s.get_giver_cycle(CYC, "g1").burn_baseline == 50 * N
    # 500 more burned out-of-band above the re-anchored baseline → confirm + book.
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 3450}, ts=2000)   # obs1 drift 500
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 3450}, ts=2100)  # obs2
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 500 * N


def test_early_cycle_oob_burn_no_longer_absorbed():
    # THE BUG (incident: GitHub 2600, CTC 800). With a carried baseline of 800, the
    # giver's 1800 AIU of early-cycle out-of-band burn shows up as drift and two
    # debounced observations book it. Under the OLD lazy capture the first
    # observation set baseline = github_burn and the 1800 vanished forever.
    e, s = seed()
    s.set_burn_baseline(CYC, "g1", 800 * N)           # carried last-known burn
    e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1400}, ts=1000)   # burn 2600, drift 1800
    ev = e.reconcile_giver(CYC, "g1", {"entitlement": 4000, "remaining": 1400}, ts=1100)  # obs2 confirms
    assert ev is not None
    assert s.bypass_consumed(CYC, "g1") == 1800 * N
