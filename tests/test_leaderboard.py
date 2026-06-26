from dataclasses import dataclass

import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.leaderboard import build_leaderboard, LeaderboardUser
from ctc.domain.types import Cycle, GiverCycle, Bucket


class FakeEngine:
    def __init__(self, donated, consumed, pool_consumed=None):
        self._d, self._c = donated, consumed
        self._p = pool_consumed if pool_consumed is not None else {}

    def donated_live(self, cycle_id, uid):
        return self._d.get(uid, 0)

    def consumed_total(self, cycle_id, uid):
        return self._c.get(uid, 0)

    def pool_consumed_by(self, cycle_id, uid):
        return self._p.get(uid, 0)

CYC = "2026-06"


def seed(path=":memory:"):
    conn = connect(path)
    init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 1_000_000, "active"))
    return AccountingEngine(s), s


def test_generous_sorted_by_donated_live_desc():
    """Top generous users ranked by donated_live descending, only value > 0."""
    e, s = seed()
    # g1 donates 100 to c1, g2 donates 50 to c2
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 500))
    s.upsert_giver_cycle(GiverCycle(CYC, "g2", 1000, 500))

    # g1 consumes own 50, then gives away 100 via pool
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 50, ts=1)
    e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 100, ts=2)

    # g2 gives away 50 via pool
    e.record_consumption(CYC, "c2", "g2", Bucket.POOL, 50, ts=3)

    # g3 has zero donation
    s.upsert_giver_cycle(GiverCycle(CYC, "g3", 1000, 500))

    users = [
        LeaderboardUser("g1", "Alice", True),
        LeaderboardUser("g2", "Bob", True),
        LeaderboardUser("g3", "Charlie", True),
    ]

    lb = build_leaderboard(e, users, CYC, top_n=5)

    assert lb["generous"] == [
        {"name": "Alice", "value": 100},
        {"name": "Bob", "value": 50},
    ]
    # g3 excluded because donated_live = 0


def test_top_pro_only_givers_sorted_by_consumed_total():
    """topPro contains only givers (is_giver=True), sorted by consumed_total desc."""
    e, s = seed()
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 500))
    s.upsert_giver_cycle(GiverCycle(CYC, "g2", 1000, 500))

    # g1 consumes 200 own
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 200, ts=1)

    # g2 consumes 150 own
    e.record_consumption(CYC, "g2", "g2", Bucket.OWN, 150, ts=2)

    # c1 is a non-giver consumer consuming 300 (from g1)
    e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 300, ts=3)

    users = [
        LeaderboardUser("g1", "Alice", True),
        LeaderboardUser("g2", "Bob", True),
        LeaderboardUser("c1", "Chris", False),  # non-giver
    ]

    lb = build_leaderboard(e, users, CYC, top_n=5)

    # topPro: only givers, ranked by consumed_total (what they consumed as consumers)
    # g1 consumed 200 own, g2 consumed 150 own
    assert lb["topPro"] == [
        {"name": "Alice", "value": 200},
        {"name": "Bob", "value": 150},
    ]
    # c1 excluded (not a giver)


def test_top_noob_only_non_givers_sorted_by_consumed_total():
    """topNoob contains only non-givers (is_giver=False), sorted by consumed_total desc."""
    e, s = seed()
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 500))

    # c1 non-giver consumes 200
    e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 200, ts=1)

    # c2 non-giver consumes 100
    e.record_consumption(CYC, "c2", "g1", Bucket.POOL, 100, ts=2)

    # g1 giver consumes 500 own (should not appear in topNoob)
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 500, ts=3)

    users = [
        LeaderboardUser("g1", "Alice", True),
        LeaderboardUser("c1", "Chris", False),
        LeaderboardUser("c2", "Dana", False),
    ]

    lb = build_leaderboard(e, users, CYC, top_n=5)

    # topNoob: only non-givers
    assert lb["topNoob"] == [
        {"name": "Chris", "value": 200},
        {"name": "Dana", "value": 100},
    ]
    # g1 excluded (giver)


def test_excludes_zero_consumption():
    """Users with zero consumption are excluded from topPro and topNoob."""
    e, s = seed()
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 500))

    # g1 consumes 100 own
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 100, ts=1)

    # c1 has zero consumption

    users = [
        LeaderboardUser("g1", "Alice", True),
        LeaderboardUser("c1", "Chris", False),
    ]

    lb = build_leaderboard(e, users, CYC)

    assert lb["topPro"] == [{"name": "Alice", "value": 100}]
    assert lb["topNoob"] == []


def test_respects_top_n():
    """Respects the top_n parameter."""
    e, s = seed()
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 2000, 1500))
    s.upsert_giver_cycle(GiverCycle(CYC, "g2", 2000, 1500))
    s.upsert_giver_cycle(GiverCycle(CYC, "g3", 2000, 1500))

    # Three givers each consuming different amounts
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 300, ts=1)
    e.record_consumption(CYC, "g2", "g2", Bucket.OWN, 200, ts=2)
    e.record_consumption(CYC, "g3", "g3", Bucket.OWN, 100, ts=3)

    users = [
        LeaderboardUser("g1", "Alice", True),
        LeaderboardUser("g2", "Bob", True),
        LeaderboardUser("g3", "Charlie", True),
    ]

    lb = build_leaderboard(e, users, CYC, top_n=2)

    # topPro limited to 2
    assert len(lb["topPro"]) == 2
    assert lb["topPro"] == [
        {"name": "Alice", "value": 300},
        {"name": "Bob", "value": 200},
    ]


def test_returns_correct_shape():
    """Returned dict has the four expected keys with list values."""
    e, s = seed()
    users = []

    lb = build_leaderboard(e, users, CYC, top_n=5)

    assert set(lb.keys()) == {"generous", "topPro", "topNoob", "standings"}
    assert isinstance(lb["generous"], list)
    assert isinstance(lb["topPro"], list)
    assert isinstance(lb["topNoob"], list)
    assert isinstance(lb["standings"], list)


def test_entry_shape():
    """Each entry has exactly 'name' and 'value' keys."""
    e, s = seed()
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 1000, 500))

    # g1 gives away 100
    e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 100, ts=1)

    users = [LeaderboardUser("g1", "Alice", True)]

    lb = build_leaderboard(e, users, CYC)

    assert len(lb["generous"]) == 1
    entry = lb["generous"][0]
    assert set(entry.keys()) == {"name", "value"}
    assert entry["name"] == "Alice"
    assert entry["value"] == 100


def test_empty_user_list():
    """Empty user list produces empty leaderboards."""
    e, s = seed()
    users = []

    lb = build_leaderboard(e, users, CYC)

    assert lb == {"generous": [], "topPro": [], "topNoob": [], "standings": []}


def test_mixed_giver_consumption_ranking():
    """Complex scenario: multiple givers/non-givers with varied consumption."""
    e, s = seed()
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 2000, 1000))
    s.upsert_giver_cycle(GiverCycle(CYC, "g2", 2000, 1000))

    # g1 gives to c1 (300 consumed by c1 from g1), g2 gives to c2 (200 consumed by c2 from g2)
    e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 300, ts=1)
    e.record_consumption(CYC, "c2", "g2", Bucket.POOL, 200, ts=2)

    # g1 self-consumes 100, g2 self-consumes 150
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 100, ts=3)
    e.record_consumption(CYC, "g2", "g2", Bucket.OWN, 150, ts=4)

    # non-giver c3 consumes 250 from g1
    e.record_consumption(CYC, "c3", "g1", Bucket.POOL, 250, ts=5)

    users = [
        LeaderboardUser("g1", "Alice", True),
        LeaderboardUser("g2", "Bob", True),
        LeaderboardUser("c1", "Chris", False),
        LeaderboardUser("c2", "Dana", False),
        LeaderboardUser("c3", "Eve", False),
    ]

    lb = build_leaderboard(e, users, CYC, top_n=5)

    # generous: donated_live = consumption from non-self
    # g1: donated to c1 (300) + c3 (250) = 550, g2: donated to c2 (200) = 200
    assert lb["generous"] == [
        {"name": "Alice", "value": 550},
        {"name": "Bob", "value": 200},
    ]

    # topPro: only givers, ranked by consumed_total (total consumption as consumers)
    # g1 consumed 100 own = 100, g2 consumed 150 own = 150
    assert lb["topPro"] == [
        {"name": "Bob", "value": 150},
        {"name": "Alice", "value": 100},
    ]

    # topNoob: only non-givers, ranked by consumed_total
    # c1 consumed 300, c2 consumed 200, c3 consumed 250
    assert lb["topNoob"] == [
        {"name": "Chris", "value": 300},
        {"name": "Eve", "value": 250},
        {"name": "Dana", "value": 200},
    ]


def test_standings_present_sorted_and_tracks_unchanged():
    from ctc.accounting.leaderboard import LeaderboardUser, build_leaderboard

    users = [
        LeaderboardUser("a", "Alice", True),
        LeaderboardUser("b", "Bob", True),
        LeaderboardUser("c", "Cara", True),
    ]
    # Alice net +300, Bob net -50 (via pool draw), Cara zero activity (newcomer)
    engine = FakeEngine(
        donated={"a": 300, "b": 0, "c": 0},
        consumed={"a": 0, "b": 50, "c": 0},
        pool_consumed={"b": 50},
    )

    out = build_leaderboard(engine, users, cycle_id="cyc1")

    assert [s["name"] for s in out["standings"]] == ["Alice", "Bob", "Cara"]
    assert out["standings"][0] == {"name": "Alice", "net": 300, "tier": "aristocrat"}
    assert out["standings"][1] == {"name": "Bob", "net": -50, "tier": "beggar"}
    assert out["standings"][2]["tier"] == "newcomer"
    # existing tracks unchanged
    assert out["generous"] == [{"name": "Alice", "value": 300}]
    assert "topPro" in out and "topNoob" in out
