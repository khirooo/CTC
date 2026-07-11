from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConsumerIdentity:
    user_id: str
    is_giver: bool


class IdentityProvider(Protocol):
    def resolve(self, fake_token: str) -> ConsumerIdentity | None: ...


class PatRegistry(Protocol):
    def pat_for(self, giver_id: str) -> str | None: ...
    def list_givers(self) -> list[str]: ...
    # Last recorded health verdict for a giver's PAT ('valid'/'expired'/... or
    # None when unknown/never checked). Used to prefer a healthy PAT for
    # non-billable borrow calls.
    def pat_health_status(self, giver_id: str) -> str | None: ...


class InMemoryIdentityProvider:
    """Stub IdentityProvider keyed by the consumer's fake token. #1 replaces this."""

    def __init__(self, mapping: dict[str, ConsumerIdentity]):
        self._mapping = dict(mapping)

    def resolve(self, fake_token: str) -> ConsumerIdentity | None:
        return self._mapping.get(fake_token)


class InMemoryPatRegistry:
    """Stub PatRegistry keyed by giver_id. #1 replaces this with the real registry."""

    def __init__(self, pats: dict[str, str]):
        self._pats = dict(pats)

    def pat_for(self, giver_id: str) -> str | None:
        return self._pats.get(giver_id)

    def list_givers(self) -> list[str]:
        return list(self._pats.keys())

    def pat_health_status(self, giver_id: str) -> str | None:
        return None  # stub: health unknown
