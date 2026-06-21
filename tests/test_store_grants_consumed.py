from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.domain.config import NANO_PER_AIU


def _store():
    conn = connect(":memory:"); init_db(conn)
    return AccountingStore(conn), conn


def _ev(conn, eid, bucket, source, credits, gid=None):
    conn.execute(
        "INSERT INTO consumption_events (id,cycle_id,ts,consumer_id,source_giver_id,bucket,grant_id,credits) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (eid, "c1", 1, "u_c", source, bucket, gid, credits),
    )


def test_grants_consumed_from_sums_only_grant_bucket_for_giver():
    store, conn = _store()
    _ev(conn, "e1", "grant", "u_g", 50 * NANO_PER_AIU, gid="g1")
    _ev(conn, "e2", "pool", "u_g", 30 * NANO_PER_AIU)          # not a grant
    _ev(conn, "e3", "grant", "u_other", 99 * NANO_PER_AIU, gid="g2")  # different giver
    assert store.grants_consumed_from("c1", "u_g") == 50 * NANO_PER_AIU


def test_grants_consumed_from_zero_when_none():
    store, _ = _store()
    assert store.grants_consumed_from("c1", "u_g") == 0
