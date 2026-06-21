from __future__ import annotations

from .types import Bucket, RequestStatus, Role


def derive_status(amount_funded: int, amount_needed: int, expires_at: int, now: int) -> RequestStatus:
    if amount_funded >= amount_needed:
        return RequestStatus.FULFILLED
    if now >= expires_at:
        return RequestStatus.EXPIRED
    if amount_funded > 0:
        return RequestStatus.PARTIALLY_FUNDED
    return RequestStatus.OPEN


def next_bucket(
    role: Role,
    *,
    personal_remaining: int = 0,
    allowance_remaining: int = 0,
    pool_available: int = 0,
    grant_remaining: int = 0,
) -> Bucket | None:
    if role == Role.GIVER:
        if personal_remaining > 0:
            return Bucket.OWN
        if grant_remaining > 0:
            return Bucket.GRANT
        return None
    if allowance_remaining > 0 and pool_available > 0:
        return Bucket.POOL
    if grant_remaining > 0:
        return Bucket.GRANT
    return None
