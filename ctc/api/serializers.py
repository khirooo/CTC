from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ..domain.rules import derive_status
from ..domain.types import Request, Role


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PublicRequestDTO(CamelModel):
    id: str
    requester_name: str
    initials: str
    requester_role: str          # 'pro' | 'noob'
    amount_needed: int           # nano-AIU
    amount_funded: int           # nano-AIU
    reason: str
    target: str | None
    created_at: int
    expires_at: int
    status: str
    donor_count: int
    is_own: bool = False         # belongs to the viewing user (can't self-fund)


class RoleCountsDTO(CamelModel):
    all: int
    pro: int
    noob: int


class ListRequestsDTO(CamelModel):
    requests: list[PublicRequestDTO]
    counts: RoleCountsDTO


class CreateRequestDTO(CamelModel):
    amount_needed: int           # nano-AIU
    reason: str
    target: str | None = None
    expiry_hours: int | None = None


class DonateDTO(CamelModel):
    amount: int                  # nano-AIU


class SettingsDTO(CamelModel):
    name: str
    login: str
    role: str
    has_pat: bool
    total_credit: int | None     # nano-AIU
    pledged_surplus: int | None  # nano-AIU
    allowance: int | None        # nano-AIU


class SettingsPatchDTO(CamelModel):
    pledged_surplus: int | None = None  # nano-AIU
    name: str | None = None
    role: str | None = None
    pat: str | None = None


class PublicUserDTO(CamelModel):
    id: str
    name: str
    initials: str
    role: str                    # 'giver' | 'consumer'


class PublicUserHitDTO(CamelModel):
    id: str
    login: str
    name: str
    initials: str
    role: str                    # 'giver' | 'consumer'


class PublicProfileDTO(CamelModel):
    id: str
    name: str
    login: str
    initials: str
    role: str                        # 'giver' | 'consumer'
    tier: str | None = None          # null for non-givers
    net: int | None = None           # nano-AIU
    donated: int | None = None       # nano-AIU
    donations_made: int | None = None


class OwnProfileDTO(CamelModel):
    # Credit fields are RAW nano-AIU (the frontend `aiu()` helper divides by
    # NANO_PER_AIU for display).
    user: PublicUserDTO
    total_credit: int | None     # nano-AIU; None for consumers
    pledged_surplus: int | None  # nano-AIU; None for consumers
    retained: int | None         # nano-AIU; None for consumers
    donated_so_far: int          # nano-AIU
    allowance: int | None        # nano-AIU remaining free allowance; None for givers
    consumed: int                # nano-AIU
    donations_received: int      # nano-AIU
    entitlement: int | None = None       # nano-AIU; -1*NANO sentinel never used — see unlimited
    remaining: int | None = None
    used: int | None = None
    pledged: int | None = None
    donated: int | None = None
    left: int | None = None
    pledged_consumed: int | None = None
    donated_consumed: int | None = None
    allowance_max: int | None = None
    allowance_used: int | None = None
    allowance_left: int | None = None
    reset_date: str | None = None
    unlimited: bool = False
    quota_stale: bool = False
    tier: str | None = None         # aristocracy tier; None for consumers
    net: int | None = None          # nano-AIU donated - consumed; None for consumers
    net_to_next: int | None = None  # nano-AIU to overtake next-higher giver; None if top/newcomer


ROLE_TO_REQUESTER: dict[Role, str] = {Role.GIVER: "pro", Role.CONSUMER: "noob"}
REQUESTER_TO_ROLE: dict[str, Role] = {"pro": Role.GIVER, "noob": Role.CONSUMER}


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    return "".join(p[0].upper() for p in parts[:2])


def build_public_request(store, get_user, r: Request, now: int, viewer_id: str | None = None) -> PublicRequestDTO:
    funded = store.request_funded(r.id)
    user = get_user(r.requester_id)
    name = user["display_name"] if user else r.requester_id
    status = derive_status(funded, r.amount_needed, r.expires_at, now)
    return PublicRequestDTO(
        id=r.id, requester_name=name, initials=initials(name),
        requester_role=ROLE_TO_REQUESTER[r.requester_role],
        amount_needed=r.amount_needed, amount_funded=funded,
        reason=r.reason, target=r.target, created_at=r.created_at,
        expires_at=r.expires_at, status=status.value,
        donor_count=store.request_donor_count(r.id),
        is_own=(viewer_id is not None and viewer_id == r.requester_id),
    )
