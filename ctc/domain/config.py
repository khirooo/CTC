from __future__ import annotations

import os
from dataclasses import dataclass, field

# Credits are stored in nano-AIU (1 AIU = 1e9 credits). See the metering contract
# (docs/reference/metering-contract.md).
NANO_PER_AIU = 1_000_000_000


def _free_allowance_nano() -> int:
    """Per-non-PAT-consumer shared-pool allowance per cycle, in nano-AIU.

    Configured in AIU via CTC_FREE_ALLOWANCE_AIU (default 300 AIU), stored as
    nano-AIU. (A single small request costs ~0.004 AIU, so 300 AIU is a generous
    per-consumer cap — tune via the env var.)
    """
    aiu = int(os.environ.get("CTC_FREE_ALLOWANCE_AIU", "300"))
    return aiu * NANO_PER_AIU


@dataclass(frozen=True)
class Config:
    free_allowance: int = field(default_factory=_free_allowance_nano)  # nano-AIU
    credit_to_euro_rate: float = 0.0088  # euros per AIU — apply to (nano / NANO_PER_AIU)
    request_expiry_hours: int = 24
    request_expiry_max_hours: int = 24 * 7
    cycle_reset_day: int = 1
    # % of a giver's remaining quota auto-pledged to the shared pool at onboarding
    # (givers can change it later). Override via CTC_DEFAULT_PLEDGE_PCT or admin settings.
    default_pledge_pct: int = field(
        default_factory=lambda: int(os.environ.get("CTC_DEFAULT_PLEDGE_PCT", "10")))
    # Default chip-in amount (AIU) pre-filled on the marketplace "chip in" action.
    # Override via CTC_DEFAULT_CHIP_IN_AIU or admin settings.
    default_chip_in_aiu: int = field(
        default_factory=lambda: int(os.environ.get("CTC_DEFAULT_CHIP_IN_AIU", "100")))
    participants_mode: str = field(
        default_factory=lambda: os.environ.get("CTC_PARTICIPANTS_MODE", "givers_only"))
    shared_pool_enabled: bool = field(
        default_factory=lambda: os.environ.get("CTC_SHARED_POOL", "off").strip().lower()
        in ("1", "on", "true", "yes"))


config = Config()
