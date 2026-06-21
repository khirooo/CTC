from __future__ import annotations

from .config import NANO_PER_AIU, config as _env_config

EFFECTIVE_KEYS = [
    "free_allowance_aiu", "default_pledge_pct",
    "request_expiry_hours", "request_expiry_max_hours", "credit_to_euro_rate",
]


class EffectiveConfig:
    """Reads a runtime override from the settings store, else the env default."""

    def __init__(self, store, base=_env_config):
        self.store = store
        self.base = base

    def _raw(self, key):
        return self.store.get_all().get(key)

    @property
    def free_allowance(self) -> int:            # nano-AIU
        v = self._raw("free_allowance_aiu")
        return int(v) * NANO_PER_AIU if v is not None else self.base.free_allowance

    @property
    def default_pledge_pct(self) -> int:
        v = self._raw("default_pledge_pct")
        return int(v) if v is not None else self.base.default_pledge_pct

    @property
    def request_expiry_hours(self) -> int:
        v = self._raw("request_expiry_hours")
        return int(v) if v is not None else self.base.request_expiry_hours

    @property
    def request_expiry_max_hours(self) -> int:
        v = self._raw("request_expiry_max_hours")
        return int(v) if v is not None else self.base.request_expiry_max_hours

    @property
    def credit_to_euro_rate(self) -> float:
        v = self._raw("credit_to_euro_rate")
        return float(v) if v is not None else self.base.credit_to_euro_rate


def effective_view(ec: EffectiveConfig, store) -> dict:
    """Per-key {value, is_override}; free_allowance reported in AIU."""
    raw = store.get_all()
    return {
        "free_allowance_aiu": {"value": ec.free_allowance // NANO_PER_AIU,
                               "is_override": "free_allowance_aiu" in raw},
        "default_pledge_pct": {"value": ec.default_pledge_pct,
                               "is_override": "default_pledge_pct" in raw},
        "request_expiry_hours": {"value": ec.request_expiry_hours,
                                 "is_override": "request_expiry_hours" in raw},
        "request_expiry_max_hours": {"value": ec.request_expiry_max_hours,
                                     "is_override": "request_expiry_max_hours" in raw},
        "credit_to_euro_rate": {"value": ec.credit_to_euro_rate,
                                "is_override": "credit_to_euro_rate" in raw},
    }


def validate_patch(patch: dict, current: dict | None = None) -> dict[str, str]:
    """Coerce + bound-check an admin settings PATCH. Returns a str->str map for
    SettingsStore.set_many. Raises ValueError on any invalid field.

    current: optional mapping of currently-effective int values for
    request_expiry_hours / request_expiry_max_hours (e.g. from EffectiveConfig).
    Precedence for the cross-field check: patch value → current → env default.
    """
    unknown = set(patch) - set(EFFECTIVE_KEYS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    out: dict[str, str] = {}
    coerced: dict = {}
    for k, v in patch.items():
        if k == "credit_to_euro_rate":
            f = float(v)
            if f < 0:
                raise ValueError("credit_to_euro_rate must be >= 0")
            coerced[k] = f
            out[k] = repr(f) if "." in str(v) or "e" in str(v).lower() else str(v)
        else:
            n = int(v)
            coerced[k] = n
            if k == "free_allowance_aiu" and n <= 0:
                raise ValueError("free_allowance_aiu must be > 0")
            if k == "default_pledge_pct" and not (0 <= n <= 100):
                raise ValueError("default_pledge_pct must be between 0 and 100")
            if k in ("request_expiry_hours", "request_expiry_max_hours") and n < 1:
                raise ValueError(f"{k} must be >= 1")
            out[k] = str(n)
    # cross-field: max >= default; resolve each side: patch → current → env default
    if "request_expiry_hours" in coerced or "request_expiry_max_hours" in coerced:
        _cur = current or {}
        dflt = coerced.get(
            "request_expiry_hours",
            _cur.get("request_expiry_hours", _env_config.request_expiry_hours),
        )
        mx = coerced.get(
            "request_expiry_max_hours",
            _cur.get("request_expiry_max_hours", _env_config.request_expiry_max_hours),
        )
        if mx < dflt:
            raise ValueError("request_expiry_max_hours must be >= request_expiry_hours")
    return out
