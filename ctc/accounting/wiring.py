"""Composition helpers for wiring an AccountingEngine to serve live traffic.

The single construction point shared by every live entrypoint (the proxy and the
control plane). Centralizing it here is deliberate: the proxy previously built its
engine without a config argument and silently fell back to raw env config, so the
admin panel's settings-table overrides never reached proxy routing. Routing every
live service through this factory guarantees they all read the same DB-backed
EffectiveConfig and cannot drift apart again.
"""

from __future__ import annotations

from .engine import AccountingEngine
from ..store.accounting_store import AccountingStore
from ..store.settings_store import SettingsStore
from ..domain.settings import EffectiveConfig


def build_live_engine(conn) -> AccountingEngine:
    """Construct an AccountingEngine whose config is the DB-backed EffectiveConfig
    (settings-table overrides overlaid on env defaults), read live per access so
    admin-panel toggles take effect without a restart.

    Callers own cycle bootstrap (engine.ensure_active_cycle) — this factory only
    constructs; it performs no I/O beyond what the stores do lazily.
    """
    return AccountingEngine(
        AccountingStore(conn),
        config=EffectiveConfig(SettingsStore(conn)),
    )
