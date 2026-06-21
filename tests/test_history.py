"""Tests for ctc.accounting.reports.build_cycle_report and build_history."""
from __future__ import annotations

import pytest

from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.accounting.leaderboard import LeaderboardUser
from ctc.accounting.reports import build_cycle_report, build_history
from ctc.domain.types import Bucket, Cycle, GiverCycle, Role, RequestStatus

CYC1 = "2026-06"
CYC2 = "2026-07"
NOW = 1_750_000_000  # arbitrary fixed "now"


def make_engine():
    conn = connect(":memory:")
    init_db(conn)
    s = AccountingStore(conn)
    return AccountingEngine(s), s


def seed_single_cycle():
    """
    Seed one cycle (CYC1) with:
      - 2 givers: g1 (quota=1000, pledge=300), g2 (quota=800, pledge=200)
      - 1 non-giver consumer: c1
      - POOL event: g1 -> c1 (non-giver), 50 credits   [toNonPat]
      - POOL event: g2 -> c1 (non-giver), 30 credits   [toNonPat]
      - POOL event: g1 -> g2 (giver-to-giver, rotator) [toPat]
      - 2 requests:
          req_giver: by g1 (Role.GIVER), amount=40, fully funded (FULFILLED)
          req_consumer: by c1 (Role.CONSUMER), amount=100, not funded (OPEN)
      - grant from g2 -> req_giver
    Returns (engine, users, req_giver, req_consumer)
    """
    e, s = make_engine()
    s.add_cycle(Cycle(CYC1, "June 2026", 1_000_000, 2_000_000_000, "active"))

    e.set_quota(CYC1, "g1", 1000)
    e.set_pledge(CYC1, "g1", 300)
    e.set_quota(CYC1, "g2", 800)
    e.set_pledge(CYC1, "g2", 200)

    # POOL: g1 -> c1 (non-giver)
    e.record_consumption(CYC1, "c1", "g1", Bucket.POOL, 50, ts=NOW - 3000)
    # POOL: g2 -> c1 (non-giver)
    e.record_consumption(CYC1, "c1", "g2", Bucket.POOL, 30, ts=NOW - 2000)
    # POOL: g1 -> g2 (giver-to-giver)
    e.record_consumption(CYC1, "g2", "g1", Bucket.POOL, 20, ts=NOW - 1000)

    # request by giver (g1), fully funded by g2
    req_giver = e.create_request(
        CYC1, "g1", Role.GIVER, 40, "giver needs", None,
        created_at=NOW - 10000, expires_at=NOW + 100000,
    )
    e.fund_request(req_giver.id, "g2", 40, NOW - 5000)

    # request by consumer (c1), open
    req_consumer = e.create_request(
        CYC1, "c1", Role.CONSUMER, 100, "consumer needs", None,
        created_at=NOW - 8000, expires_at=NOW + 200000,
    )

    users = [
        LeaderboardUser("g1", "Giver One", is_giver=True),
        LeaderboardUser("g2", "Giver Two", is_giver=True),
        LeaderboardUser("c1", "Consumer One", is_giver=False),
    ]

    return e, users, req_giver, req_consumer


# ---------------------------------------------------------------------------
# build_cycle_report — field-level tests
# ---------------------------------------------------------------------------

class TestBuildCycleReportKeys:
    def test_all_required_keys_present(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        required = {
            "id", "label", "pledged", "donated", "toNonPat", "toPat",
            "reqFilled", "reqTotal", "reqPat", "reqNonPat", "fills", "winners",
        }
        assert required == set(report.keys())

    def test_id_and_label(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["id"] == CYC1
        assert report["label"] == "June 2026"


class TestBuildCycleReportPledged:
    def test_pledged_is_sum_of_all_gc_pledges(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        gcs = e.store.all_giver_cycles(CYC1)
        expected = sum(gc.pledge for gc in gcs)  # 300 + 200 = 500
        assert report["pledged"] == expected


class TestBuildCycleReportDonated:
    def test_to_non_pat_counts_pool_grant_to_non_givers(self):
        """toNonPat = pool/grant credits consumed by non-giver users."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        # c1 consumed 50 (from g1) + 30 (from g2) via POOL = 80
        assert report["toNonPat"] == 80

    def test_to_pat_counts_pool_grant_to_givers(self):
        """toPat = pool/grant credits consumed by giver users."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        # g2 consumed 20 via POOL (from g1) = 20
        assert report["toPat"] == 20

    def test_donated_is_sum_of_to_pat_and_to_non_pat(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["donated"] == report["toPat"] + report["toNonPat"]

    def test_own_events_not_counted_in_donated(self):
        """OWN bucket events should NOT appear in toPat/toNonPat/donated."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        # Add an OWN consumption for g1
        e.record_consumption(CYC1, "g1", "g1", Bucket.OWN, 100, ts=NOW - 500)
        report = build_cycle_report(e, users, CYC1, NOW)
        # donated should still be 80 + 20 = 100 (no change from own event)
        assert report["toPat"] == 20
        assert report["toNonPat"] == 80
        assert report["donated"] == 100


class TestBuildCycleReportRequests:
    def test_req_total(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["reqTotal"] == 2

    def test_req_filled_counts_fulfilled_requests(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        # req_giver is fully funded → FULFILLED, req_consumer is not funded → OPEN
        assert report["reqFilled"] == 1

    def test_req_pat_counts_giver_role_requests(self):
        """reqPat = requests with requester_role == Role.GIVER."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["reqPat"] == 1

    def test_req_non_pat_counts_consumer_role_requests(self):
        """reqNonPat = requests with requester_role == Role.CONSUMER."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["reqNonPat"] == 1

    def test_req_pat_plus_non_pat_equals_total(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["reqPat"] + report["reqNonPat"] == report["reqTotal"]


class TestBuildCycleReportFills:
    def test_fills_is_list(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert isinstance(report["fills"], list)

    def test_fills_entry_shape(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        for entry in report["fills"]:
            assert set(entry.keys()) == {"who", "amount", "count"}

    def test_fills_top_donor_is_g2(self):
        """g2 funded req_giver for 40 credits."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        assert len(report["fills"]) >= 1
        top = report["fills"][0]
        assert top["who"] == "Giver Two"
        assert top["amount"] == 40
        assert top["count"] == 1

    def test_fills_sorted_by_amount_desc(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        amounts = [f["amount"] for f in report["fills"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_fills_at_most_5(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        # Fund with many donors by seeding more givers
        report = build_cycle_report(e, users, CYC1, NOW)
        assert len(report["fills"]) <= 5

    def test_fills_fallback_to_id_when_name_unknown(self):
        """If donor_id not in users list, fallback to donor_id as name."""
        e, s = make_engine()
        s.add_cycle(Cycle(CYC1, "June 2026", 1_000_000, 2_000_000_000, "active"))
        e.set_quota(CYC1, "unknown_donor", 1000)
        # Directly insert a grant with unknown_donor
        from ctc.domain.types import Grant
        import uuid
        req = e.create_request(
            CYC1, "c1", Role.CONSUMER, 50, "need", None,
            created_at=NOW - 1000, expires_at=NOW + 1000,
        )
        # fund_request needs personal credit; use allow_overshoot path via store directly
        g = Grant(uuid.uuid4().hex, CYC1, req.id, "unknown_donor", "c1", 50, NOW - 500)
        s.add_grant(g)

        users_no_unknown = [
            LeaderboardUser("c1", "Consumer One", is_giver=False),
        ]
        report = build_cycle_report(e, users_no_unknown, CYC1, NOW)
        fills = report["fills"]
        assert len(fills) == 1
        assert fills[0]["who"] == "unknown_donor"


class TestBuildCycleReportWinners:
    def test_winners_shape(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        w = report["winners"]
        assert "generous" in w
        assert "pro" in w
        assert "noob" in w

    def test_winners_generous_has_name_and_value(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        g = report["winners"]["generous"]
        assert "name" in g
        assert "value" in g

    def test_winners_generous_is_top_donor(self):
        """g1 donated 50+20=70 credits (pool/grant), g2 donated 30+0=30; g1 wins."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        # g1 donated_live: 50 to c1 + 20 to g2 = 70
        # g2 donated_live: 30 to c1
        assert report["winners"]["generous"]["name"] == "Giver One"
        assert report["winners"]["generous"]["value"] == 70

    def test_winners_pro_is_giver_consumer(self):
        """topPro winner is the giver with most consumed_total."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        # g2 consumed 20 from pool (pool event)
        # g1 consumed 0 (no own events added yet)
        report = build_cycle_report(e, users, CYC1, NOW)
        w = report["winners"]["pro"]
        # g2 consumed 20 credits (pool from g1)
        assert w["name"] == "Giver Two"
        assert w["value"] == 20

    def test_winners_noob_is_top_non_giver_consumer(self):
        """topNoob winner is non-giver with most consumed_total."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        # c1 consumed 50+30=80 credits (pool from g1 and g2)
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["winners"]["noob"]["name"] == "Consumer One"
        assert report["winners"]["noob"]["value"] == 80

    def test_winners_defaults_when_no_data(self):
        """When no consumption, generous/pro/noob default to '—' with value 0."""
        e, s = make_engine()
        s.add_cycle(Cycle(CYC1, "Empty", 0, 2_000_000_000, "active"))
        users = []
        report = build_cycle_report(e, users, CYC1, NOW)
        assert report["winners"]["generous"] == {"name": "—", "value": 0}
        assert report["winners"]["pro"] == {"name": "—", "value": 0}
        assert report["winners"]["noob"] == {"name": "—", "value": 0}

    def test_winners_rotator_present_when_giver_to_giver(self):
        """rotator key is present when a giver donated pool/grant to another giver."""
        e, users, req_giver, req_consumer = seed_single_cycle()
        report = build_cycle_report(e, users, CYC1, NOW)
        # g1 donated 20 to g2 via pool → rotator should be g1
        w = report["winners"]
        assert "rotator" in w
        assert w["rotator"]["name"] == "Giver One"
        assert w["rotator"]["value"] == 20

    def test_winners_rotator_omitted_when_no_giver_to_giver(self):
        """rotator key is absent when no giver-to-giver donations."""
        e, s = make_engine()
        s.add_cycle(Cycle(CYC1, "NoRotate", 0, 2_000_000_000, "active"))
        e.set_quota(CYC1, "g1", 1000)
        e.set_pledge(CYC1, "g1", 300)
        # only donate to non-giver
        e.record_consumption(CYC1, "c1", "g1", Bucket.POOL, 50, ts=NOW - 1000)
        users = [
            LeaderboardUser("g1", "Giver One", is_giver=True),
            LeaderboardUser("c1", "Consumer One", is_giver=False),
        ]
        report = build_cycle_report(e, users, CYC1, NOW)
        assert "rotator" not in report["winners"]


# ---------------------------------------------------------------------------
# build_history — ordering and multi-cycle tests
# ---------------------------------------------------------------------------

class TestBuildHistory:
    def test_returns_list(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        history = build_history(e, users, NOW)
        assert isinstance(history, list)

    def test_single_cycle_in_history(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        history = build_history(e, users, NOW)
        assert len(history) == 1
        assert history[0]["id"] == CYC1

    def test_newest_first_across_two_cycles(self):
        """build_history returns cycles ordered newest-first by starts_at."""
        e, s = make_engine()
        # CYC1: starts_at=1000, CYC2: starts_at=2000 (newer)
        s.add_cycle(Cycle(CYC1, "June 2026", 1000, 1_999_999, "archived"))
        s.add_cycle(Cycle(CYC2, "July 2026", 2000, 2_999_999, "active"))

        users = []
        history = build_history(e, users, NOW)
        assert len(history) == 2
        # CYC2 has larger starts_at, should come first
        assert history[0]["id"] == CYC2
        assert history[1]["id"] == CYC1

    def test_history_each_cycle_has_all_required_keys(self):
        e, users, req_giver, req_consumer = seed_single_cycle()
        history = build_history(e, users, NOW)
        required = {
            "id", "label", "pledged", "donated", "toNonPat", "toPat",
            "reqFilled", "reqTotal", "reqPat", "reqNonPat", "fills", "winners",
        }
        for report in history:
            assert required == set(report.keys())

    def test_history_two_cycles_correct_values(self):
        """Each cycle in history has values computed from its own data."""
        e, s = make_engine()
        s.add_cycle(Cycle(CYC1, "June 2026", 1000, 1_999_999, "archived"))
        s.add_cycle(Cycle(CYC2, "July 2026", 2000, 2_999_999, "active"))

        # Seed CYC1 with a giver and some pledges
        e.set_quota(CYC1, "g1", 500)
        e.set_pledge(CYC1, "g1", 100)
        e.record_consumption(CYC1, "c1", "g1", Bucket.POOL, 30, ts=NOW - 5000)

        # Seed CYC2 with different pledge
        e.set_quota(CYC2, "g1", 800)
        e.set_pledge(CYC2, "g1", 200)
        e.record_consumption(CYC2, "c1", "g1", Bucket.POOL, 60, ts=NOW - 1000)

        users = [
            LeaderboardUser("g1", "Giver One", is_giver=True),
            LeaderboardUser("c1", "Consumer One", is_giver=False),
        ]
        history = build_history(e, users, NOW)
        # history[0] = CYC2 (newer), history[1] = CYC1 (older)
        assert history[0]["id"] == CYC2
        assert history[0]["pledged"] == 200
        assert history[0]["toNonPat"] == 60

        assert history[1]["id"] == CYC1
        assert history[1]["pledged"] == 100
        assert history[1]["toNonPat"] == 30

    def test_empty_db_returns_empty_list(self):
        e, s = make_engine()
        users = []
        history = build_history(e, users, NOW)
        assert history == []
