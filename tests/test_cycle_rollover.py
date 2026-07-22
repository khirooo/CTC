"""Automatic cycle rollover: when the active cycle's window has ended,
ensure_active_cycle archives it, opens the month-of-now cycle, and seeds the new
cycle's giver_cycles from the connected PATs (quota = entitlement, pledge carried
forward and clamped). See docs/superpowers/specs/2026-06-27-cycle-rollover-design.md.
"""
import datetime

from ctc.accounting.engine import AccountingEngine
from ctc.domain.config import NANO_PER_AIU
from ctc.domain.types import Bucket, Cycle, GiverCycle, Grant
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


def _ts(y, m, d, hh=12):
    return int(datetime.datetime(y, m, d, hh, tzinfo=datetime.timezone.utc).timestamp())


def _sec(y, m, d, hh, mm, ss):
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=datetime.timezone.utc).timestamp())


JUNE = _ts(2026, 6, 9)
JULY = _ts(2026, 7, 9)
AUGUST = _ts(2026, 8, 9)


def _engine():
    conn = connect(":memory:"); init_db(conn)
    return AccountingEngine(AccountingStore(conn))


def _add_pat(eng, user_id, entitlement, now=JUNE):
    """Insert a minimal giver_pats row carrying just the entitlement the rollover
    reads (the encrypted-PAT columns are NOT NULL but their values are irrelevant)."""
    eng.store.conn.execute(
        "INSERT INTO giver_pats (user_id, ciphertext, nonce, fingerprint, created_at, entitlement) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, b"x", b"y", "fp", now, entitlement),
    )


def test_rollover_archives_old_and_opens_month_of_now():
    eng = _engine()
    june = eng.ensure_active_cycle(JUNE)
    assert june.id == "cycle-2026-06"

    rolled = eng.ensure_active_cycle(JULY)
    assert rolled.id == "cycle-2026-07"
    assert rolled.status == "active"
    # the only active cycle is now July; June is archived
    assert eng.current_cycle().id == "cycle-2026-07"
    assert eng.store.get_cycle("cycle-2026-06").status == "archived"


def test_rollover_seeds_quota_from_entitlement_and_carries_pledge():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=100)
    eng.set_quota("cycle-2026-06", "g1", 100 * NANO_PER_AIU)
    eng.set_pledge("cycle-2026-06", "g1", 40 * NANO_PER_AIU)

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    assert gc is not None
    assert gc.quota == 100 * NANO_PER_AIU      # full entitlement, fresh period
    assert gc.pledge == 40 * NANO_PER_AIU      # carried forward


def test_rollover_clamps_carried_pledge_to_new_quota():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=100)
    eng.set_quota("cycle-2026-06", "g1", 100 * NANO_PER_AIU)
    eng.set_pledge("cycle-2026-06", "g1", 80 * NANO_PER_AIU)
    # entitlement drops for next period → new quota is smaller than the old pledge
    eng.store.conn.execute("UPDATE giver_pats SET entitlement=30 WHERE user_id='g1'")

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    assert gc.quota == 30 * NANO_PER_AIU
    assert gc.pledge == 30 * NANO_PER_AIU       # clamped down from 80


def test_rollover_seeds_zero_pledge_when_no_prior_pledge():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    # giver with a PAT but no giver_cycle / no pledge in June (e.g. shared pool off)
    _add_pat(eng, "g1", entitlement=50)

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    assert gc.quota == 50 * NANO_PER_AIU
    assert gc.pledge == 0


def test_no_rollover_while_cycle_is_still_live():
    eng = _engine()
    june = eng.ensure_active_cycle(JUNE)
    again = eng.ensure_active_cycle(JUNE + 5 * 24 * 3600)  # later, still June
    assert again.id == june.id
    n = eng.store.conn.execute("SELECT COUNT(*) AS n FROM cycles").fetchone()["n"]
    assert n == 1
    assert eng.store.get_cycle("cycle-2026-06").status == "active"


def test_rollover_is_idempotent():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    first = eng.ensure_active_cycle(JULY)
    second = eng.ensure_active_cycle(JULY)
    assert first.id == second.id == "cycle-2026-07"
    # exactly two cycle rows: archived June + active July
    rows = eng.store.conn.execute(
        "SELECT id, status FROM cycles ORDER BY starts_at"
    ).fetchall()
    assert [(r["id"], r["status"]) for r in rows] == [
        ("cycle-2026-06", "archived"),
        ("cycle-2026-07", "active"),
    ]


def test_multi_month_dormancy_jumps_to_current_month():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    rolled = eng.ensure_active_cycle(AUGUST)  # skipped all of July
    assert rolled.id == "cycle-2026-08"
    assert eng.store.get_cycle("cycle-2026-07") is None   # no empty intermediate cycle
    assert eng.store.get_cycle("cycle-2026-06").status == "archived"
    assert eng.current_cycle().id == "cycle-2026-08"


def test_rollover_skips_pats_without_entitlement():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=None)   # PAT row with no entitlement captured
    _add_pat(eng, "g2", entitlement=0)

    eng.ensure_active_cycle(JULY)

    assert eng.store.get_giver_cycle("cycle-2026-07", "g1") is None
    assert eng.store.get_giver_cycle("cycle-2026-07", "g2") is None


# --------------------------------------------------------------------------- #
# P0-1: exclusive month-end boundary — no orphaned cycle at the last second.
# --------------------------------------------------------------------------- #

def test_last_second_of_month_is_still_live():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    last = _sec(2026, 6, 30, 23, 59, 59)      # final real second of June (UTC)
    c = eng.ensure_active_cycle(last)
    assert c.id == "cycle-2026-06"            # still live — no orphaning rollover
    assert eng.current_cycle().id == "cycle-2026-06"
    assert eng.store.get_cycle("cycle-2026-06").status == "active"
    # the first second of the next month rolls over cleanly
    rolled = eng.ensure_active_cycle(last + 1)
    assert rolled.id == "cycle-2026-07"
    assert eng.current_cycle().id == "cycle-2026-07"
    assert eng.store.get_cycle("cycle-2026-06").status == "archived"


def test_double_call_at_rollover_boundary_no_integrity_error():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    first_july = _sec(2026, 7, 1, 0, 0, 0)
    a = eng.ensure_active_cycle(first_july)   # rolls over
    b = eng.ensure_active_cycle(first_july)   # second call in the same second
    assert a.id == b.id == "cycle-2026-07"
    rows = eng.store.conn.execute(
        "SELECT id, status FROM cycles ORDER BY starts_at"
    ).fetchall()
    assert [(r["id"], r["status"]) for r in rows] == [
        ("cycle-2026-06", "archived"),
        ("cycle-2026-07", "active"),
    ]


def test_legacy_inclusive_end_row_tolerated_at_last_second():
    # A cycle row persisted with the OLD inclusive 23:59:59 end. A request landing
    # in that exact second must not archive the cycle onto itself (P0-1 root cause).
    eng = _engine()
    last_sec = _sec(2026, 6, 30, 23, 59, 59)
    start = _sec(2026, 6, 1, 0, 0, 0)
    eng.store.add_cycle(Cycle("cycle-2026-06", "June 2026", start, last_sec, "active"))

    c = eng.ensure_active_cycle(last_sec)
    assert c.id == "cycle-2026-06"
    assert eng.current_cycle().id == "cycle-2026-06"       # still active, not archived
    # a second request in the same second is stable (the P0-1 500/gap path)
    c2 = eng.ensure_active_cycle(last_sec)
    assert c2.id == "cycle-2026-06"
    assert eng.store.get_cycle("cycle-2026-06").status == "active"
    n = eng.store.conn.execute("SELECT COUNT(*) AS n FROM cycles").fetchone()["n"]
    assert n == 1


def test_gap_path_seeds_giver_cycles_from_pats():
    # Fresh DB: PATs connected before any cycle exists. The no-cycle gap path must
    # seed giver_cycles too (the old bare start_cycle gap path did not).
    eng = _engine()
    _add_pat(eng, "g1", entitlement=100)
    c = eng.ensure_active_cycle(JUNE)          # gap path via _roll_over
    assert c.id == "cycle-2026-06"
    gc = eng.store.get_giver_cycle("cycle-2026-06", "g1")
    assert gc is not None
    assert gc.quota == 100 * NANO_PER_AIU
    assert gc.pledge == 0


def test_fresh_db_first_ensure_opens_current_month():
    eng = _engine()
    c = eng.ensure_active_cycle(JUNE)
    assert c.id == "cycle-2026-06" and c.status == "active"
    # end is exclusive: first second of July
    assert c.ends_at == _sec(2026, 7, 1, 0, 0, 0)


# --------------------------------------------------------------------------- #
# Baseline carry at rollover (D2): the new cycle's burn_baseline is seeded with
# the prev cycle's LAST-KNOWN GitHub burn (its baseline + everything CTC tracked),
# so early-cycle out-of-band burn isn't swallowed by the lazy first-reconcile
# capture (the incident: GitHub 2600 AIU, CTC 800).
# --------------------------------------------------------------------------- #

def test_rollover_carries_baseline_as_prev_last_known_github_burn():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=4000)
    eng.set_quota("cycle-2026-06", "g1", 4000 * NANO_PER_AIU)
    eng.store.set_burn_baseline("cycle-2026-06", "g1", 500 * NANO_PER_AIU)
    eng.record_consumption("cycle-2026-06", "g1", "g1", Bucket.OWN, 200 * NANO_PER_AIU, ts=JUNE)
    eng.record_consumption("cycle-2026-06", "g1", "g1", Bucket.BYPASS, 100 * NANO_PER_AIU, ts=JUNE)

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    # carried = prev baseline(500) + tracked own(200) + bypass(100)
    assert gc.burn_baseline == 800 * NANO_PER_AIU


def test_rollover_no_carry_when_prev_baseline_none():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=100)
    eng.set_quota("cycle-2026-06", "g1", 100 * NANO_PER_AIU)   # baseline never set

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    assert gc.burn_baseline is None


def test_rollover_carry_includes_all_tracked_buckets():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=4000)
    eng.set_quota("cycle-2026-06", "g1", 4000 * NANO_PER_AIU)
    eng.store.set_burn_baseline("cycle-2026-06", "g1", 500 * NANO_PER_AIU)
    # own + pool + grant + bypass all feed _tracked_burn.
    eng.record_consumption("cycle-2026-06", "g1", "g1", Bucket.OWN, 200 * NANO_PER_AIU, ts=JUNE)
    eng.record_consumption("cycle-2026-06", "c1", "g1", Bucket.POOL, 300 * NANO_PER_AIU,
                           ts=JUNE, allow_overshoot=True)
    eng.store.add_grant(Grant("grant1", "cycle-2026-06", "req1", "g1", "c1", 400 * NANO_PER_AIU, JUNE))
    eng.record_consumption("cycle-2026-06", "c1", "g1", Bucket.GRANT, 400 * NANO_PER_AIU,
                           grant_id="grant1", ts=JUNE, allow_overshoot=True)
    eng.record_consumption("cycle-2026-06", "g1", "g1", Bucket.BYPASS, 100 * NANO_PER_AIU, ts=JUNE)

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    # carried = baseline(500) + own(200) + pool(300) + grant(400) + bypass(100)
    assert gc.burn_baseline == 1500 * NANO_PER_AIU


def test_rollover_does_not_clobber_existing_target_row_baseline():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=4000)
    eng.set_quota("cycle-2026-06", "g1", 4000 * NANO_PER_AIU)
    eng.store.set_burn_baseline("cycle-2026-06", "g1", 500 * NANO_PER_AIU)
    # July row already exists with its own baseline (reactivation / re-entry path).
    eng.store.add_cycle(Cycle("cycle-2026-07", "July 2026",
                              _sec(2026, 7, 1, 0, 0, 0), _sec(2026, 8, 1, 0, 0, 0), "archived"))
    eng.store.upsert_giver_cycle(GiverCycle("cycle-2026-07", "g1", 4000 * NANO_PER_AIU, 0))
    eng.store.set_burn_baseline("cycle-2026-07", "g1", 999 * NANO_PER_AIU)

    eng.ensure_active_cycle(JULY)

    gc = eng.store.get_giver_cycle("cycle-2026-07", "g1")
    assert gc.burn_baseline == 999 * NANO_PER_AIU   # untouched, not overwritten by carry


def test_gap_months_carry_prev_baseline():
    eng = _engine()
    eng.ensure_active_cycle(JUNE)
    _add_pat(eng, "g1", entitlement=4000)
    eng.set_quota("cycle-2026-06", "g1", 4000 * NANO_PER_AIU)
    eng.store.set_burn_baseline("cycle-2026-06", "g1", 500 * NANO_PER_AIU)
    eng.record_consumption("cycle-2026-06", "g1", "g1", Bucket.OWN, 300 * NANO_PER_AIU, ts=JUNE)

    eng.ensure_active_cycle(AUGUST)   # dormancy gap: July skipped entirely

    assert eng.store.get_cycle("cycle-2026-07") is None
    gc = eng.store.get_giver_cycle("cycle-2026-08", "g1")
    # carried from the months-old archived June cycle: baseline(500) + own(300)
    assert gc.burn_baseline == 800 * NANO_PER_AIU


def test_init_db_normalizes_legacy_inclusive_ends_at():
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    last_sec = _sec(2026, 6, 30, 23, 59, 59)
    s.add_cycle(Cycle("cycle-2026-06", "June", _sec(2026, 6, 1, 0, 0, 0), last_sec, "active"))
    init_db(conn)   # re-run migration → bumps the legacy inclusive end by +1
    row = conn.execute("SELECT ends_at FROM cycles WHERE id='cycle-2026-06'").fetchone()
    assert row["ends_at"] == last_sec + 1
    # idempotent: running again does not shift it further
    init_db(conn)
    row2 = conn.execute("SELECT ends_at FROM cycles WHERE id='cycle-2026-06'").fetchone()
    assert row2["ends_at"] == last_sec + 1
