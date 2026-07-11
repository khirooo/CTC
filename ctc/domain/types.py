from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    GIVER = "giver"
    CONSUMER = "consumer"


class Bucket(str, Enum):
    OWN = "own"
    POOL = "pool"
    GRANT = "grant"
    BYPASS = "bypass"  # giver's own out-of-band (non-proxied) burn, self-sourced


class RequestStatus(str, Enum):
    OPEN = "open"
    PARTIALLY_FUNDED = "partially_funded"
    FULFILLED = "fulfilled"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Cycle:
    id: str
    label: str
    starts_at: int
    ends_at: int
    status: str  # 'active' | 'archived'


@dataclass(frozen=True)
class GiverCycle:
    cycle_id: str
    giver_id: str
    quota: int
    pledge: int


@dataclass(frozen=True)
class Request:
    id: str
    cycle_id: str
    requester_id: str
    requester_role: Role
    amount_needed: int
    reason: str
    target: str | None
    created_at: int
    expires_at: int
    cancelled_at: int | None = None


@dataclass(frozen=True)
class Grant:
    id: str
    cycle_id: str
    request_id: str
    donor_id: str
    recipient_id: str
    amount: int
    created_at: int
    source: str = "personal"  # 'personal' | 'pool'
    # Re-donation chain (depth capped at 1): a child grant is funded by its
    # parent grant's remaining credit, NOT by donor_id's retained quota —
    # donor_id stays the original PAT holder so routing charges the right PAT.
    origin_grant_id: str | None = None   # parent grant this was funded from
    via_user_id: str | None = None       # the re-donor (display attribution)
    contribution_id: str | None = None   # set when drawn from a pool contribution


@dataclass(frozen=True)
class PoolContribution:
    """Received credit a recipient moved into the shared pool. Backed by (and
    charged to) the origin grant's donor; drawn by fund_request_from_pool."""
    id: str
    cycle_id: str
    contributor_id: str
    origin_grant_id: str
    donor_id: str
    amount: int
    created_at: int


@dataclass(frozen=True)
class Event:
    id: str
    cycle_id: str
    ts: int
    consumer_id: str
    source_giver_id: str
    bucket: Bucket
    grant_id: str | None
    credits: int
