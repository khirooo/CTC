from __future__ import annotations

from .types import RequestStatus


def derive_status(
    amount_funded: int,
    amount_needed: int,
    expires_at: int,
    now: int,
    cancelled_at: int | None = None,
) -> RequestStatus:
    if cancelled_at is not None:
        return RequestStatus.CANCELLED
    if amount_funded >= amount_needed:
        return RequestStatus.FULFILLED
    if now >= expires_at:
        return RequestStatus.EXPIRED
    if amount_funded > 0:
        return RequestStatus.PARTIALLY_FUNDED
    return RequestStatus.OPEN
