"""`ctc claude` run tags: the proxy labels each ledger row with the client's
X-CTC-Run-Tag (never forwarding it upstream), and GET /api/usage?tag= reads a
run's real charge back for the tag owner only. Unit throughout: nano-AIU, the
unit consumption_events.credits is stored in (1 AIU = 1e9)."""
import sqlite3
import types

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

import proxy as proxy_mod
from api_server import make_app
from ctc.accounting.engine import AccountingEngine
from ctc.auth.crypto import derive_key
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.auth.registry import AuthRegistry
from ctc.auth.sessions import SessionService
from ctc.domain.config import NANO_PER_AIU as N
from ctc.domain.deployment import DeploymentConfig
from ctc.domain.types import Bucket, Role
from ctc.routing.attribution import AttributionService
from ctc.store.accounting_store import AccountingStore
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db
from tests.conftest import TEST_HOST


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def test_migration_adds_nullable_indexed_run_tag_to_a_legacy_db(tmp_path):
    db = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(db)
    legacy.execute(
        "CREATE TABLE consumption_events (id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, "
        "ts INTEGER NOT NULL, consumer_id TEXT NOT NULL, source_giver_id TEXT NOT NULL, "
        "bucket TEXT NOT NULL, grant_id TEXT, credits INTEGER NOT NULL)")
    legacy.execute("INSERT INTO consumption_events VALUES ('e1','c1',1,'u1','u1','own',NULL,5)")
    legacy.commit(); legacy.close()

    conn = connect(db); init_db(conn)
    cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(consumption_events)")}
    for col in ("run_tag", "model", "exchange_id"):
        assert col in cols and cols[col]["notnull"] == 0
    assert conn.execute("SELECT run_tag FROM consumption_events").fetchone()[0] is None
    idx = {r["name"] for r in conn.execute("PRAGMA index_list(consumption_events)")}
    assert "ix_events_run_tag" in idx
    init_db(conn)  # idempotent


# --------------------------------------------------------------------------- #
# Ledger: tag stored, spill counted once, scoped to the consumer
# --------------------------------------------------------------------------- #
class _ConsumersEnabled:
    shared_pool_enabled = True
    free_allowance = 300 * N
    default_pledge_pct = 0
    participants_mode = "givers_and_consumers"


@pytest.fixture
def spill_svc():
    conn = connect(":memory:"); init_db(conn)
    eng = AccountingEngine(AccountingStore(conn), config=_ConsumersEnabled())
    eng.start_cycle("c1", "June", 0, 10_000_000)
    eng.set_quota("c1", "yas", 500)
    eng.set_quota("c1", "zed", 500)
    ga = eng.fund_request(eng.create_request("c1", "kef", Role.CONSUMER, 25, "a", None, 0, 10_000_000).id,
                          "yas", 25, now=1)
    eng.fund_request(eng.create_request("c1", "kef", Role.CONSUMER, 40, "b", None, 0, 10_000_000).id,
                     "zed", 40, now=2)
    svc = AttributionService(eng, InMemoryIdentityProvider({}),
                             InMemoryPatRegistry({"yas": "ghp_yas", "zed": "ghp_zed"}))
    return svc, eng, ga


def test_debit_stores_the_run_tag_and_counts_a_spill_as_one_request(spill_svc):
    svc, eng, ga = spill_svc
    kef = ConsumerIdentity("kef", is_giver=False)
    src = svc.select_source("c1", kef)
    assert src.grant_id == ga.id
    svc.debit("c1", kef, src, 50, ts=7, run_tag="run-1", model="claude-sonnet-5")  # spills A -> B
    svc.debit("c1", kef, src, 3, ts=9, run_tag="run-1", model="claude-haiku-4.5")
    svc.debit("c1", kef, src, 4, ts=9)                                            # untagged

    rows = eng.store.conn.execute(
        "SELECT run_tag, model, exchange_id, credits FROM consumption_events WHERE ts=7").fetchall()
    assert len(rows) == 2                                # the spill wrote two rows...
    assert {r["run_tag"] for r in rows} == {"run-1"}
    assert len({r["exchange_id"] for r in rows}) == 1    # ...under one exchange

    u = eng.store.usage_by_run_tag("kef", "run-1")
    assert u == {"requests": 2, "nano_aiu_total": 53, "last_ts": 9,
                 "by_model": {"claude-sonnet-5": {"requests": 1, "nano_aiu": 50},
                              "claude-haiku-4.5": {"requests": 1, "nano_aiu": 3}}}


def test_tagging_does_not_change_what_is_charged(spill_svc):
    svc, eng, ga = spill_svc
    kef = ConsumerIdentity("kef", is_giver=False)
    svc.debit("c1", kef, svc.select_source("c1", kef), 50, ts=7, run_tag="run-1", model="m")
    assert eng.grant_remaining("c1", ga.id) == 0
    assert eng.consumed_total("c1", "kef") == 50


def test_another_consumers_tag_reads_as_empty(spill_svc):
    svc, eng, _ = spill_svc
    kef = ConsumerIdentity("kef", is_giver=False)
    svc.debit("c1", kef, svc.select_source("c1", kef), 5, ts=7, run_tag="run-1", model="m")
    assert eng.store.usage_by_run_tag("yas", "run-1") == {
        "requests": 0, "nano_aiu_total": 0, "last_ts": None, "by_model": {}}


# --------------------------------------------------------------------------- #
# Proxy: tag read from the header, recorded on the debit, never forwarded
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,want", [
    ("run-0123abcd", "run-0123abcd"), (" run_1 ", "run_1"),
    ("", None), ("a" * 65, None), ("run 1", None), ("run/../x", None),
])
def test_run_tag_of_accepts_only_safe_tags(raw, want):
    assert proxy_mod.run_tag_of({"x-ctc-run-tag": raw}) == want


def test_run_tag_header_is_stripped_from_upstream_headers():
    out = proxy_mod.build_upstream_headers(
        {"x-ctc-run-tag": "run-1", "accept": "*/*"}, "api.example.ghe.com", "token x", 0, "PAT")
    assert "x-ctc-run-tag" not in out
    assert out["accept"] == "*/*"


class _Attribution:
    def __init__(self):
        self.engine = types.SimpleNamespace(ensure_active_cycle=lambda now: types.SimpleNamespace(id="c1"),
                                            active_grants=lambda c, u: [])
        self.debits = []

    def resolve_consumer(self, token):
        return ConsumerIdentity("consumer1", is_giver=True)

    def select_source(self, cid, consumer, health=None, exclude=frozenset()):
        return types.SimpleNamespace(giver_id="g1", pat="github_pat_REAL", grant_id=None)

    def pinned_source(self, *a, **k):
        return None

    def debit(self, cid, consumer, source, cost, ts, **tags):
        self.debits.append(tags)


@pytest.mark.asyncio
async def test_proxy_records_the_tag_and_does_not_forward_it(running_proxy, client_ssl,
                                                             mock_upstream, monkeypatch):
    attr = _Attribution()
    monkeypatch.setattr(proxy_mod, "ATTRIBUTION", attr)
    monkeypatch.setattr(proxy_mod, "LIVE_QUOTA", None)
    monkeypatch.setattr(proxy_mod, "_COPILOT_API_HOST", TEST_HOST)
    monkeypatch.setattr(proxy_mod, "_BILLABLE_PATHS", proxy_mod._BILLABLE_PATHS | {"/tagged"})
    monkeypatch.setattr(proxy_mod, "MITM_HOSTS", {TEST_HOST})
    monkeypatch.setattr(proxy_mod, "SWAP_HOSTS", {TEST_HOST})

    connector = aiohttp.TCPConnector(ssl=client_ssl)
    async with aiohttp.ClientSession(connector=connector) as s:
        async with s.post(f"https://{TEST_HOST}/tagged", data=b'{"model":"claude-sonnet-5"}',
                          proxy=f"http://127.0.0.1:{running_proxy['port']}",
                          headers={"Authorization": "token ctc-fake",
                                   "X-CTC-Run-Tag": "run-feedface"}) as r:
            assert r.status == 200

    assert attr.debits == [{"run_tag": "run-feedface", "model": "claude-sonnet-5"}]
    upstream = {k.lower() for k in mock_upstream["received"]["headers"]}
    assert "x-ctc-run-tag" not in upstream


# --------------------------------------------------------------------------- #
# GET /api/usage
# --------------------------------------------------------------------------- #
async def _usage_app():
    conn = connect(":memory:"); init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn)); eng.start_cycle("c1", "June", 0, 10_000_000_000)
    reg = AuthRegistry(store, derive_key("k"))
    for uid in ("alice", "bob"):
        store.upsert_user(uid, uid, uid, "giver", 1)
    _, alice_tok, _ = reg.issue_proxy_token("alice", 1)
    _, bob_tok, _ = reg.issue_proxy_token("bob", 1)
    for credits, model in ((2 * N, "claude-sonnet-5"), (N // 2, "claude-haiku-4.5")):
        eng.record_consumption("c1", "alice", "alice", Bucket.OWN, credits, ts=50,
                               allow_overshoot=True, run_tag="run-alice", model=model,
                               exchange_id=model)
    app = make_app(store=store, engine=eng, registry=reg,
                   sessions=SessionService(store, secret="sek", ttl_s=10_000),
                   http_get_user=None, cycle_id="c1", secret="sek", app_origin="http://app",
                   deployment=DeploymentConfig(web_transport="https"), now=lambda: 100)
    return app, alice_tok, bob_tok


@pytest.mark.asyncio
async def test_usage_returns_the_callers_run_total_in_nano_aiu():
    app, alice, _ = await _usage_app()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.get("/api/usage?tag=run-alice", headers={"Authorization": f"Bearer {alice}"})
        assert r.status == 200
        assert await r.json() == {
            "tag": "run-alice", "unit": "nano_aiu", "requests": 2,
            "nano_aiu_total": 2 * N + N // 2, "last_ts": 50,
            "by_model": {"claude-sonnet-5": {"requests": 1, "nano_aiu": 2 * N},
                         "claude-haiku-4.5": {"requests": 1, "nano_aiu": N // 2}}}


@pytest.mark.asyncio
async def test_usage_of_another_consumers_tag_returns_nothing():
    app, _, bob = await _usage_app()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.get("/api/usage?tag=run-alice", headers={"Authorization": f"Bearer {bob}"})
        assert r.status == 200
        body = await r.json()
        assert body["requests"] == 0 and body["nano_aiu_total"] == 0 and body["by_model"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,path,status", [
    ({}, "/api/usage?tag=run-alice", 401),
    ({"Authorization": "Bearer not-a-token"}, "/api/usage?tag=run-alice", 401),
    (None, "/api/usage", 400),
    (None, "/api/usage?tag=../etc", 400),
])
async def test_usage_rejects_bad_auth_and_bad_tags(headers, path, status):
    app, alice, _ = await _usage_app()
    async with TestClient(TestServer(app)) as cli:
        r = await cli.get(path, headers={"Authorization": f"Bearer {alice}"} if headers is None else headers)
        assert r.status == status
