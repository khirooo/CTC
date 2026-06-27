"""Automatic cycle rollover: when the active cycle's window has ended,
ensure_active_cycle archives it, opens the month-of-now cycle, and seeds the new
cycle's giver_cycles from the connected PATs (quota = entitlement, pledge carried
forward and clamped). See docs/superpowers/specs/2026-06-27-cycle-rollover-design.md.
"""
import datetime

from ctc.accounting.engine import AccountingEngine
from ctc.domain.config import NANO_PER_AIU
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db


def _ts(y, m, d, hh=12):
    return int(datetime.datetime(y, m, d, hh, tzinfo=datetime.timezone.utc).timestamp())


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
