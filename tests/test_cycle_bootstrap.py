from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine

JUNE_2026 = 1781000000  # ~2026-06-09 UTC


def _engine():
    conn = connect(":memory:"); init_db(conn)
    return AccountingEngine(AccountingStore(conn))


def test_ensure_active_cycle_creates_one_when_none():
    eng = _engine()
    assert eng.current_cycle() is None
    c = eng.ensure_active_cycle(JUNE_2026)
    assert c.status == "active"
    assert c.id == "cycle-2026-06"
    assert eng.current_cycle().id == c.id


def test_ensure_active_cycle_is_idempotent():
    eng = _engine()
    first = eng.ensure_active_cycle(JUNE_2026)
    again = eng.ensure_active_cycle(JUNE_2026 + 500_000)  # later in the month
    assert again.id == first.id
    # exactly one cycle row exists
    rows = eng.store.conn.execute("SELECT COUNT(*) AS n FROM cycles").fetchone()
    assert rows["n"] == 1


def test_ensure_active_cycle_leaves_existing_active_cycle_untouched():
    eng = _engine()
    eng.start_cycle("custom", "Custom", 0, 10_000_000_000)
    kept = eng.ensure_active_cycle(JUNE_2026)
    assert kept.id == "custom"   # does not replace an already-active cycle
