from ctc.store.db import connect, init_db
from ctc.store.accounting_store import AccountingStore
from ctc.accounting.engine import AccountingEngine
from ctc.domain.types import Cycle, GiverCycle, Bucket
from ctc.domain.config import NANO_PER_AIU as N
from tools.repair_baseline import repair_giver, RepairError

import pytest

CYC = "2026-06"


class FakeRegistry:
    def __init__(self, pats: dict):
        self._pats = pats

    def pat_for(self, giver_id):
        return self._pats.get(giver_id)


def seed_incident():
    """Reproduce the incident: baseline of 1800 AIU absorbed real burn, CTC only
    tracked 800 AIU (own), while GitHub reports 2600 AIU burned (4000-1400)."""
    conn = connect(":memory:"); init_db(conn)
    s = AccountingStore(conn)
    s.add_cycle(Cycle(CYC, "June", 0, 4_000_000_000, "active"))
    s.upsert_giver_cycle(GiverCycle(CYC, "g1", 4000 * N, 0))
    s.set_burn_baseline(CYC, "g1", 1800 * N)          # baseline swallowed the burn
    e = AccountingEngine(s)
    e.record_consumption(CYC, "g1", "g1", Bucket.OWN, 800 * N, ts=1)   # tracked
    return e, s


def _live(ent, rem):
    return {"quota_snapshots": {"premium_interactions":
                                {"entitlement": ent, "remaining": rem}}}


def test_incident_repair_books_absorbed_drift_as_bypass():
    e, s = seed_incident()
    reg = FakeRegistry({"g1": "pat-g1"})
    calls = []

    def fetch_user(pat):
        calls.append(pat)
        return _live(4000, 1400)  # github_burn 2600

    r = repair_giver(e, reg, fetch_user, "g1", now=1000)
    assert calls == ["pat-g1"]
    assert r["old_baseline"] == 1800 * N
    assert r["drift_booked_nano"] == 1800 * N
    assert r["cycle_id"] == CYC
    # baseline re-anchored, one BYPASS event, own+bypass now matches GitHub (2600).
    assert s.get_giver_cycle(CYC, "g1").burn_baseline == 0
    assert s.bypass_consumed(CYC, "g1") == 1800 * N
    assert s.own_consumed(CYC, "g1") + s.bypass_consumed(CYC, "g1") == 2600 * N


def test_dry_run_writes_nothing_but_reports_drift():
    e, s = seed_incident()
    reg = FakeRegistry({"g1": "pat-g1"})
    r = repair_giver(e, reg, lambda pat: _live(4000, 1400), "g1", now=1000, dry_run=True)
    assert r["drift_booked_nano"] == 1800 * N          # would-be booking reported
    assert r["old_baseline"] == 1800 * N
    # nothing changed on disk.
    gc = s.get_giver_cycle(CYC, "g1")
    assert gc.burn_baseline == 1800 * N
    assert gc.pending_drift is None
    assert s.bypass_consumed(CYC, "g1") == 0


def test_second_run_is_idempotent():
    e, s = seed_incident()
    reg = FakeRegistry({"g1": "pat-g1"})
    fetch = lambda pat: _live(4000, 1400)
    repair_giver(e, reg, fetch, "g1", now=1000)
    assert s.bypass_consumed(CYC, "g1") == 1800 * N
    r2 = repair_giver(e, reg, fetch, "g1", now=2000)
    assert r2["drift_booked_nano"] == 0                 # tracked now covers github_burn
    assert s.bypass_consumed(CYC, "g1") == 1800 * N     # no new event


def test_offline_override_never_calls_fetch_user():
    e, s = seed_incident()
    reg = FakeRegistry({"g1": "pat-g1"})

    def fetch_user(pat):
        raise AssertionError("fetch_user must not be called on the offline path")

    r = repair_giver(e, reg, fetch_user, "g1", now=1000,
                     entitlement=4000, remaining=1400)
    assert r["drift_booked_nano"] == 1800 * N
    assert s.bypass_consumed(CYC, "g1") == 1800 * N


def test_stale_pending_drift_is_cleared():
    e, s = seed_incident()
    s.set_pending_drift(CYC, "g1", 999 * N, 500)       # a stale observation
    reg = FakeRegistry({"g1": "pat-g1"})
    repair_giver(e, reg, lambda pat: _live(4000, 1400), "g1", now=1000)
    assert s.get_giver_cycle(CYC, "g1").pending_drift is None
    assert s.bypass_consumed(CYC, "g1") == 1800 * N


def test_missing_pat_raises():
    e, s = seed_incident()
    reg = FakeRegistry({})                              # no PAT for g1
    with pytest.raises(RepairError):
        repair_giver(e, reg, lambda pat: _live(4000, 1400), "g1", now=1000)
