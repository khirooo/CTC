from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.domain.types import Cycle, GiverCycle, Request, Grant, Event, Role, Bucket


def fresh():
    conn = connect()
    init_db(conn)
    return AccountingStore(conn)


def test_cycle_roundtrip_and_active():
    s = fresh()
    s.add_cycle(Cycle("2026-06", "June", 0, 100, "active"))
    s.add_cycle(Cycle("2026-05", "May", -100, -1, "archived"))
    assert s.get_cycle("2026-06").label == "June"
    assert s.active_cycle().id == "2026-06"


def test_giver_cycle_upsert_overwrites():
    s = fresh()
    s.upsert_giver_cycle(GiverCycle("2026-06", "g1", 1000, 200))
    s.upsert_giver_cycle(GiverCycle("2026-06", "g1", 1000, 350))
    assert s.get_giver_cycle("2026-06", "g1").pledge == 350
    assert len(s.all_giver_cycles("2026-06")) == 1


def test_request_and_grant_roundtrip():
    s = fresh()
    s.add_request(Request("r1", "2026-06", "u1", Role.CONSUMER, 60, "PR", None, 0, 100))
    assert s.get_request("r1").amount_needed == 60
    assert s.get_request("r1").requester_role == Role.CONSUMER
    s.add_grant(Grant("gr1", "2026-06", "r1", "g1", "u1", 25, 5))
    assert s.get_grant("gr1").amount == 25
    assert [g.id for g in s.grants_for_recipient("2026-06", "u1")] == ["gr1"]


def test_event_roundtrip_and_persistence(tmp_path):
    path = str(tmp_path / "ctc.db")
    conn = connect(path); init_db(conn)
    s = AccountingStore(conn)
    s.add_event(Event("e1", "2026-06", 7, "u1", "g1", Bucket.POOL, None, 25))
    # reopen -> data survives, enum restored
    s2 = AccountingStore(connect(path))
    rows = s2.conn.execute("SELECT bucket, credits FROM consumption_events WHERE id='e1'").fetchone()
    assert rows["bucket"] == "pool"
    assert rows["credits"] == 25
