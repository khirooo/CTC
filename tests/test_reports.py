"""Tests for ctc.accounting.reports.build_dashboard."""
from __future__ import annotations

import time

import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.leaderboard import LeaderboardUser
from ctc.accounting.reports import build_dashboard
from ctc.domain.types import Bucket, Cycle, GiverCycle, Role

CYC = "2026-06"
NOW = 1_750_000_000  # arbitrary fixed "now"
WEEK_AGO = NOW - 7 * 24 * 3600  # exactly 1 week before NOW


def make_engine() -> tuple[AccountingEngine, AccountingStore]:
    conn = connect(":memory:")
    init_db(conn)
    s = AccountingStore(conn)
    return AccountingEngine(s), s


def seed_full():
    """
    Seed:
      - 2 givers: g1 (quota=1000, pledge=300), g2 (quota=800, pledge=200)
      - 1 non-giver consumer: c1
      - POOL events: g1 donates 50 to c1 (non-giver), g2 donates 30 to c1 (non-giver)
      - POOL event: g1 donates 20 to g2 (giver-to-giver = rotated)
      - OWN event: g1 consumes 100 own credits
      - 2 requests: req1 fully funded (fulfilled), req2 open
    Returns (engine, users, giver_ids, consumer_ids, events)
    """
    e, s = make_engine()
    s.add_cycle(Cycle(CYC, "June 2026", 0, 2_000_000_000, "active"))

    # --- givers ---
    e.set_quota(CYC, "g1", 1000)
    e.set_pledge(CYC, "g1", 300)
    e.set_quota(CYC, "g2", 800)
    e.set_pledge(CYC, "g2", 200)

    giver_ids = {"g1", "g2"}

    # --- consumption events ---
    # POOL: g1 → c1 (non-giver), recent (within last 7 days)
    ev_pool_g1_c1 = e.record_consumption(CYC, "c1", "g1", Bucket.POOL, 50, ts=NOW - 1000)
    # POOL: g2 → c1 (non-giver), recent
    ev_pool_g2_c1 = e.record_consumption(CYC, "c1", "g2", Bucket.POOL, 30, ts=NOW - 2000)
    # POOL: g1 → g2 (giver to giver = rotated), recent
    ev_pool_g1_g2 = e.record_consumption(CYC, "g2", "g1", Bucket.POOL, 20, ts=NOW - 3000)
    # OWN: g1 own consumption
    ev_own_g1 = e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 100, ts=NOW - 4000)
    # POOL: g2 → c1 (non-giver), OLD (more than 7 days ago)
    ev_pool_old = e.record_consumption(CYC, "c1", "g2", Bucket.POOL, 15, ts=WEEK_AGO - 1)

    # --- requests ---
    # req1: fully funded (g1 funds it fully → fulfilled)
    req1 = e.create_request(CYC, "c1", Role.CONSUMER, 40, "need help", None,
                            created_at=NOW - 10000, expires_at=NOW + 100000)
    e.fund_request(req1.id, "g1", 40, NOW - 5000)

    # req2: open, not funded
    req2 = e.create_request(CYC, "c1", Role.CONSUMER, 100, "more help", None,
                            created_at=NOW - 8000, expires_at=NOW + 200000)

    users = [
        LeaderboardUser("g1", "Giver One", is_giver=True),
        LeaderboardUser("g2", "Giver Two", is_giver=True),
        LeaderboardUser("c1", "Consumer One", is_giver=False),
    ]

    return e, users, giver_ids, req1, req2


def test_pledged():
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    gcs = e.store.all_giver_cycles(CYC)
    expected = sum(gc.pledge for gc in gcs)  # 300 + 200 = 500
    assert dash["pledged"] == expected


def test_retained():
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    gcs = e.store.all_giver_cycles(CYC)
    expected = sum(e.personal_remaining(CYC, gc.giver_id) for gc in gcs)
    assert dash["retained"] == expected


def test_rotated():
    """rotated = pool+grant credits where consumer IS a giver."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # g2 consumed 20 pool from g1 (giver consuming pool)
    assert dash["rotated"] == 20


def test_donated_to_non_pat():
    """donatedToNonPat = pool+grant credits where consumer is NOT a giver."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # c1 consumed 50 (g1) + 30 (g2) recently + 15 (g2) old via pool = 95
    assert dash["donatedToNonPat"] == 95


def test_donated_this_week():
    """donatedThisWeek = pool+grant where ts >= NOW - 7days."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # Recent pool events: 50 + 30 + 20 = 100 (old 15 excluded)
    assert dash["donatedThisWeek"] == 100


def test_fulfillment_rate():
    """fulfillmentRate = int(fulfilled / total * 100)."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # 1 fulfilled out of 2 = 50%
    assert dash["fulfillmentRate"] == 50


def test_active_givers():
    """activeGivers = distinct giver_ids with pledge>0 OR source_giver_id in events."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # Both g1 and g2 have pledge > 0
    assert dash["activeGivers"] == 2


def test_active_consumers():
    """activeConsumers = distinct consumer_ids in events that are NOT givers."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # Only c1 is a non-giver consumer
    assert dash["activeConsumers"] == 1


def test_active_host_who_only_consumed_counts():
    """A giver who only consumed this cycle (no pledge, no PAT, never sourced
    credits) is still a host and must count as an active host — not vanish from
    both the host and guest tallies.

    Scenario from the field: a host exhausted their own quota (0 credits left)
    and used the pool/grant of another host via the marketplace. They have a
    giver_cycles row (role=giver) but pledge=0, no giver_pats row, and they only
    ever appear as a *consumer*, never as source_giver_id.
    """
    e, s = make_engine()
    s.add_cycle(Cycle(CYC, "June 2026", 0, 2_000_000_000, "active"))

    # g1: the lender — pledges to the pool (active by pledge).
    e.set_quota(CYC, "g1", 1000)
    e.set_pledge(CYC, "g1", 300)

    # g2: a host who consumed from g1's pool but never pledged, never sourced,
    # and has no PAT row. Give them a giver_cycles row via set_quota only.
    e.set_quota(CYC, "g2", 500)
    e.set_pledge(CYC, "g2", 0)

    # g2 consumes 50 from g1's pool (g2 is consumer_id, g1 is source_giver_id).
    e.record_consumption(CYC, "g2", "g1", Bucket.POOL, 50, ts=NOW - 1000)

    users = [
        LeaderboardUser("g1", "Lender", is_giver=True),
        LeaderboardUser("g2", "Borrower Host", is_giver=True),
    ]

    dash = build_dashboard(e, users, CYC, NOW)
    # Both g1 and g2 are hosts participating this cycle.
    assert dash["activeGivers"] == 2
    # g2 is a giver, so they must NOT be counted as a guest.
    assert dash["activeConsumers"] == 0


def test_open_closed_count():
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # req1 is fulfilled (closed), req2 is open
    assert dash["openCount"] == 1
    assert dash["closedCount"] == 1


def test_activity_structure():
    """activity = up to 8 most recent events, each with time/kind/actorId/detail/amount."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    activity = dash["activity"]
    assert isinstance(activity, list)
    assert len(activity) <= 8
    assert len(activity) >= 1
    for item in activity:
        assert "time" in item
        assert "kind" in item
        assert item["kind"] == "consume"
        assert "actorId" in item
        assert "detail" in item
        assert "amount" in item
    # Most recent event should come first
    times = [int(item["time"]) for item in activity]
    assert times == sorted(times, reverse=True)


def test_activity_detail_format():
    """Each activity detail uses display name (or id[:8] fallback) + ' via {bucket}'."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # Build a name lookup to verify resolved names
    name_by_id = {u.user_id: u.name for u in users}
    for item in dash["activity"]:
        detail = item["detail"]
        # Should contain " via " and a bucket name
        assert " via " in detail
        actor_id = item["actorId"]
        expected_name = name_by_id.get(actor_id, actor_id[:8])
        assert detail.startswith(expected_name + " via ")


def test_leaderboard_snapshot_keys():
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    lb = dash["leaderboardSnapshot"]
    assert "generous" in lb
    assert "topConsumers" in lb


def test_leaderboard_generous_has_donors():
    """Givers who donated should appear in generous list."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    lb = dash["leaderboardSnapshot"]
    names = [entry["name"] for entry in lb["generous"]]
    # g1 donated to c1 (50) and g2 (20) = 70 live; g2 donated to c1 (30+15) = 45 live
    assert "Giver One" in names
    assert "Giver Two" in names


def test_all_keys_present():
    """Ensure all required dashboard keys are present."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    required = {
        "pledged", "retained", "rotated", "donatedToNonPat", "donatedThisWeek",
        "fulfillmentRate", "activeGivers", "activeConsumers",
        "openCount", "closedCount", "activity", "leaderboardSnapshot",
    }
    assert required == set(dash.keys())


def test_empty_cycle():
    """build_dashboard on a fresh cycle with no events returns sensible zeros."""
    e, s = make_engine()
    s.add_cycle(Cycle(CYC, "Empty", 0, 2_000_000_000, "active"))
    users = []
    dash = build_dashboard(e, users, CYC, NOW)
    assert dash["pledged"] == 0
    assert dash["retained"] == 0
    assert dash["rotated"] == 0
    assert dash["donatedToNonPat"] == 0
    assert dash["donatedThisWeek"] == 0
    assert dash["fulfillmentRate"] == 0
    assert dash["activeGivers"] == 0
    assert dash["activeConsumers"] == 0
    assert dash["openCount"] == 0
    assert dash["closedCount"] == 0
    assert dash["activity"] == []
