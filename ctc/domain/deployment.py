from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

_AUTH_MODES = ("email", "ghe_oauth")
_WEB_TRANSPORTS = ("http", "https")
_EMAIL_BACKENDS = ("console", "smtp")


def _pick(env: Mapping, key: str, allowed: tuple[str, ...], default: str) -> str:
    v = (env.get(key) or default).strip().lower()
    if v not in allowed:
        raise ValueError(f"{key} must be one of {allowed!r}, got {v!r}")
    return v


@dataclass(frozen=True)
class DeploymentConfig:
    auth_mode: str = "email"
    web_transport: str = "http"
    email_backend: str = "console"

    @classmethod
    def from_env(cls, env: Mapping) -> "DeploymentConfig":
        return cls(
            auth_mode=_pick(env, "CTC_AUTH_MODE", _AUTH_MODES, "email"),
            web_transport=_pick(env, "CTC_WEB_TRANSPORT", _WEB_TRANSPORTS, "http"),
            email_backend=_pick(env, "CTC_EMAIL_BACKEND", _EMAIL_BACKENDS, "console"),
        )
