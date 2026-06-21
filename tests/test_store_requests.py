from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.domain.types import Request, Grant, Role


def _store():
    conn = connect(":memory:")
    init_db(conn)
    return AccountingStore(conn)


def test_list_requests_returns_cycle_requests_newest_first():
    s = _store()
    s.add_request(Request("r1", "c1", "u_ada", Role.GIVER, 100, "need", None, 10, 1000))
    s.add_request(Request("r2", "c1", "u_lh", Role.CONSUMER, 50, "need2", "@ada", 20, 1000))
    s.add_request(Request("r3", "c2", "u_dr", Role.CONSUMER, 30, "other cycle", None, 30, 1000))
    out = s.list_requests("c1")
    assert [r.id for r in out] == ["r2", "r1"]  # newest created_at first
    assert all(isinstance(r, Request) for r in out)
    assert out[1].requester_role == Role.GIVER


def test_request_donor_count_counts_distinct_donors():
    s = _store()
    s.add_request(Request("r1", "c1", "u_lh", Role.CONSUMER, 100, "need", None, 1, 1000))
    s.add_grant(Grant("g1", "c1", "r1", "u_ada", "u_lh", 40, 5))
    s.add_grant(Grant("g2", "c1", "r1", "u_ada", "u_lh", 10, 6))  # same donor again
    s.add_grant(Grant("g3", "c1", "r1", "u_mb", "u_lh", 50, 7))
    assert s.request_donor_count("r1") == 2  # u_ada, u_mb
    assert s.request_donor_count("missing") == 0
