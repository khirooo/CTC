"""Tests for ctc.accounting.reports.build_dashboard."""
from __future__ import annotations

import re
import time

import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.leaderboard import LeaderboardUser, build_leaderboard
from ctc.accounting.reports import build_dashboard, build_cycle_report
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
    # c1's usage is all POOL bucket in this fixture, so it also counts as a poolGuest
    assert dash["poolGuests"] == 1


def test_pool_guests_excludes_grant_only_and_givers():
    """poolGuests = distinct non-giver consumers with a POOL-bucket event this
    cycle. A guest who only received a directed GRANT (not pool) must NOT
    count in poolGuests, even though they DO count in activeConsumers. A guest
    who drew from the POOL must count in both."""
    e, s = make_engine()
    s.add_cycle(Cycle(CYC, "June 2026", 0, 2_000_000_000, "active"))

    e.set_quota(CYC, "g1", 1000)
    e.set_pledge(CYC, "g1", 300)

    # c_grant: only ever received a directed GRANT chip-in (not pool) — funded
    # via a request/grant, as GRANT-bucket consumption must reference a grant.
    req = e.create_request(CYC, "c_grant", Role.CONSUMER, 10, "need help", None,
                            created_at=NOW - 2000, expires_at=NOW + 100000)
    grant = e.fund_request(req.id, "g1", 10, NOW - 1500)
    e.record_consumption(CYC, "c_grant", "g1", Bucket.GRANT, 10, grant_id=grant.id, ts=NOW - 1000)
    # c_pool: drew from the shared POOL.
    e.record_consumption(CYC, "c_pool", "g1", Bucket.POOL, 20, ts=NOW - 2000)

    users = [
        LeaderboardUser("g1", "Giver One", is_giver=True),
        LeaderboardUser("c_grant", "Grant Consumer", is_giver=False),
        LeaderboardUser("c_pool", "Pool Consumer", is_giver=False),
    ]

    dash = build_dashboard(e, users, CYC, NOW)
    # Both non-giver consumers count in activeConsumers (any bucket).
    assert dash["activeConsumers"] == 2
    # Only the pool consumer counts in poolGuests.
    assert dash["poolGuests"] == 1


def test_pool_guests_excludes_givers_who_draw_from_pool():
    """A giver who consumes from the pool must not count as a poolGuest —
    mirrors the activeConsumers giver-exclusion rule."""
    e, s = make_engine()
    s.add_cycle(Cycle(CYC, "June 2026", 0, 2_000_000_000, "active"))

    e.set_quota(CYC, "g1", 1000)
    e.set_pledge(CYC, "g1", 300)
    e.set_quota(CYC, "g2", 500)
    e.set_pledge(CYC, "g2", 0)

    # g2 (a giver) draws from g1's pool.
    e.record_consumption(CYC, "g2", "g1", Bucket.POOL, 50, ts=NOW - 1000)

    users = [
        LeaderboardUser("g1", "Lender", is_giver=True),
        LeaderboardUser("g2", "Borrower Host", is_giver=True),
    ]

    dash = build_dashboard(e, users, CYC, NOW)
    assert dash["poolGuests"] == 0


def test_open_closed_count():
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    # req1 is fulfilled (closed), req2 is open
    assert dash["openCount"] == 1
    assert dash["closedCount"] == 1


def test_activity_structure():
    """activity = pool+grant events from the last 24h (capped), time/kind/actorId/detail/amount."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    activity = dash["activity"]
    assert isinstance(activity, list)
    assert len(activity) <= 100
    assert len(activity) >= 1
    for item in activity:
        # time is a display-ready HH:MM string (not a raw epoch)
        assert re.fullmatch(r"\d{2}:\d{2}", item["time"]), item["time"]
        # kind carries the bucket so the client can split pool vs marketplace streams
        assert item["kind"] in ("pool", "grant")
        assert "actorId" in item
        assert "detail" in item
        # amount is a display-ready AIU string (not raw nano-AIU)
        assert re.fullmatch(r"\d+\.\d{2} AIU", item["amount"]), item["amount"]
    # Most recent event first: amounts match the pool/grant events within the last
    # 24h ordered by ts DESC (own-bucket burn and >24h events are excluded).
    rows = e.store.conn.execute(
        "SELECT credits FROM consumption_events WHERE cycle_id=? "
        "AND bucket IN ('pool','grant') AND ts >= ? "
        "ORDER BY ts DESC, rowid DESC LIMIT 100",
        (CYC, NOW - 24 * 3600),
    ).fetchall()
    assert [it["amount"] for it in activity] == [
        f"{r['credits'] / 1_000_000_000:.2f} AIU" for r in rows
    ]
    # own-bucket burn (g1's 100) must NOT appear in the marketplace/pool feed
    assert "100.00 AIU" not in [it["amount"] for it in activity]


def test_activity_detail_format():
    """Each activity detail is the resolved display name (or id[:8] fallback)."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    name_by_id = {u.user_id: u.name for u in users}
    for item in dash["activity"]:
        actor_id = item["actorId"]
        expected_name = name_by_id.get(actor_id, actor_id[:8])
        assert item["detail"] == expected_name


def test_cycle_number_and_reset():
    """Dashboard carries the cycle ordinal, label, reset date and days-left."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    assert dash["cycleLabel"] == "June 2026"
    assert dash["cycleNumber"] == 1  # only one cycle exists → ordinal 1
    # cycle ends at ts=2_000_000_000; NOW=1_750_000_000 → ceil(250_000_000/86400) days
    assert dash["daysLeft"] == -(-(2_000_000_000 - NOW) // 86400)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", dash["resetDate"])


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
        "fulfillmentRate", "activeGivers", "activeConsumers", "poolGuests",
        "openCount", "closedCount", "activity", "leaderboardSnapshot",
        "cycleLabel", "cycleNumber", "resetDate", "daysLeft",
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
    assert dash["poolGuests"] == 0
    assert dash["openCount"] == 0
    assert dash["closedCount"] == 0
    assert dash["activity"] == []


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
    assert dash["poolGuests"] == 0


def test_dashboard_top_consumers_carry_userid():
    """Dashboard "Top users" entries must keep userId so the names stay
    clickable through to /app/users/:id (regression: the merge dropped it)."""
    e, users, giver_ids, req1, req2 = seed_full()
    dash = build_dashboard(e, users, CYC, NOW)
    tc = dash["leaderboardSnapshot"]["topConsumers"]
    assert tc, "expected some top consumers"
    for entry in tc:
        assert entry.get("userId"), f"topConsumers entry missing userId: {entry}"


def test_cycle_report_unused_budget_is_quota_minus_all_consumption():
    """Unused budget = total company budget (Σ giver quota) − total credit used
    (ALL consumption: own + pool + grant)."""
    e, users, giver_ids, req1, req2 = seed_full()
    rep = build_cycle_report(e, users, CYC, NOW)
    # budget = Σ giver quota = 1000 + 800
    assert rep["budgetTotal"] == 1800
    # used = ALL consumption incl own = 50 + 30 + 20 + 100(own) + 15
    assert rep["usedTotal"] == 215
    assert rep["budgetTotal"] - rep["usedTotal"] == 1585


def test_giver_who_only_consumed_a_grant_is_not_newcomer():
    """A host who received a marketplace grant and consumed it has participated;
    their tier must reflect that (grant 'taken' counts), not 'newcomer'."""
    e, s = make_engine()
    s.add_cycle(Cycle(CYC, "June 2026", 0, 2_000_000_000, "active"))
    e.set_quota(CYC, "g1", 1000); e.set_pledge(CYC, "g1", 0)
    e.set_quota(CYC, "g2", 500);  e.set_pledge(CYC, "g2", 0)
    # g2 (a giver) posts a request, g1 funds it (grant), g2 consumes the grant.
    req = e.create_request(CYC, "g2", Role.GIVER, 100, "need", None,
                           created_at=NOW - 1000, expires_at=NOW + 100000)
    g = e.fund_request(req.id, "g1", 100, NOW - 500)
    e.record_consumption(CYC, "g2", "g1", Bucket.GRANT, 80, grant_id=g.id, ts=NOW - 400)
    users = [LeaderboardUser("g1", "Lender", is_giver=True),
             LeaderboardUser("g2", "Borrower", is_giver=True)]
    tiers = {row["name"]: row["tier"] for row in build_leaderboard(e, users, CYC)["standings"]}
    assert tiers["Borrower"] != "newcomer"   # consumed a grant → active
    assert tiers["Lender"] != "newcomer"     # their gift was burned → donated
