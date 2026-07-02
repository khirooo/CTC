"""Unify live-engine config on EffectiveConfig.

Regression tests for the incident where the proxy built its AccountingEngine
without a config arg, so it read participants_mode/shared_pool from raw env
config and ignored the settings table (the admin panel + DB overrides). The
shared factory build_live_engine() is the single wiring point that guarantees
every live service reads the DB-backed EffectiveConfig.
"""

from ctc.accounting.wiring import build_live_engine
from ctc.accounting.engine import AccountingEngine
from ctc.routing.attribution import AttributionService
from ctc.auth.identity import ConsumerIdentity, InMemoryIdentityProvider, InMemoryPatRegistry
from ctc.store.accounting_store import AccountingStore
from ctc.store.settings_store import SettingsStore
from ctc.store.db import connect, init_db
from ctc.domain.settings import EffectiveConfig
from ctc.domain.config import NANO_PER_AIU
from ctc.domain.types import Bucket, Grant


def test_build_live_engine_uses_db_backed_effective_config():
    conn = connect(":memory:"); init_db(conn)
    eng = build_live_engine(conn)
    assert isinstance(eng, AccountingEngine)
    assert isinstance(eng.config, EffectiveConfig)
    # an override written to the settings table is visible through the engine
    SettingsStore(conn).set_many({"participants_mode": "givers_and_consumers"}, "admin", 1000)
    assert eng.config.participants_mode == "givers_and_consumers"


def test_db_participants_override_flips_select_source_live():
    """The incident, encoded: a consumer with a valid grant is blocked while
    participants_mode is givers_only, then funded the moment the setting is
    flipped in the DB — on the SAME engine, no rebuild (proves it's read live)."""
    conn = connect(":memory:"); init_db(conn)
    eng = build_live_engine(conn)
    cyc = eng.ensure_active_cycle(1000)
    # giver g1 has an active grant to non-giver consumer c1
    AccountingStore(conn).add_grant(
        Grant("gr1", cyc.id, "req1", "g1", "c1", 100 * NANO_PER_AIU, 1000))
    pats = InMemoryPatRegistry({"g1": "pat_g1"})
    svc = AttributionService(eng, InMemoryIdentityProvider({}), pats)
    consumer = ConsumerIdentity("c1", is_giver=False)

    # givers_only gate blocks the non-giver despite the grant
    SettingsStore(conn).set_many({"participants_mode": "givers_only"}, "admin", 1001)
    assert svc.select_source(cyc.id, consumer) is None

    # admin flips the setting → same engine now routes to the grant, live
    SettingsStore(conn).set_many({"participants_mode": "givers_and_consumers"}, "admin", 1002)
    src = svc.select_source(cyc.id, consumer)
    assert src is not None and src.bucket == Bucket.GRANT and src.grant_id == "gr1"
