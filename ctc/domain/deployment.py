from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

_WEB_TRANSPORTS = ("http", "https")


def _pick(env: Mapping, key: str, allowed: tuple[str, ...], default: str) -> str:
    v = (env.get(key) or default).strip().lower()
    if v not in allowed:
        raise ValueError(f"{key} must be one of {allowed!r}, got {v!r}")
    return v


@dataclass(frozen=True)
class DeploymentConfig:
    web_transport: str = "http"

    @classmethod
    def from_env(cls, env: Mapping) -> "DeploymentConfig":
        return cls(
            web_transport=_pick(env, "CTC_WEB_TRANSPORT", _WEB_TRANSPORTS, "http"),
        )
