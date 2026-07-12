from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ..domain.config import NANO_PER_AIU
from ..domain.rules import derive_status
from ..domain.types import Request, Role

# Request-amount ceiling: 10,000 AIU in nano-AIU. Bounds a single marketplace ask
# so a fat-fingered or hostile value can't pollute the board / overflow displays.
MAX_REQUEST_NANO = 10_000 * NANO_PER_AIU


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PublicRequestDTO(CamelModel):
    id: str
    requester_id: str
    requester_name: str
    initials: str
    requester_role: str          # 'pro' | 'noob'
    amount_needed: int           # nano-AIU
    amount_funded: int           # nano-AIU
    funded_consumed: int = 0     # nano-AIU of amount_funded already burned by the recipient
    reason: str
    target: str | None
    created_at: int
    expires_at: int
    status: str
    donor_count: int
    is_own: bool = False         # belongs to the viewing user (can't self-fund personally)
    pool_funded: int = 0         # nano-AIU of amount_funded drawn from the shared pool


class RoleCountsDTO(CamelModel):
    all: int
    pro: int
    noob: int


class ListRequestsDTO(CamelModel):
    requests: list[PublicRequestDTO]
    counts: RoleCountsDTO
    pool_enabled: bool = False
    pool_available: int = 0      # nano-AIU still pledged and undrawn across all givers
    # Viewer's chip-in sources (nano-AIU) — the card shows a source picker only
    # when both are positive.
    viewer_personal_remaining: int = 0
    viewer_received_remaining: int = 0


class CreateRequestDTO(CamelModel):
    amount_needed: int = Field(gt=0, le=MAX_REQUEST_NANO)   # nano-AIU
    reason: str = Field(min_length=1, max_length=500)
    target: str | None = Field(default=None, max_length=200)
    expiry_hours: int | None = None


class DonateDTO(CamelModel):
    amount: int = Field(gt=0)    # nano-AIU
    # 'personal' = the donor's retained credit; 'received' = re-donate credit
    # that was granted to them (chains attribution to the original PAT holder).
    source: str = "personal"


class SettingsDTO(CamelModel):
    name: str
    login: str
    role: str
    has_pat: bool
    pat_health: str | None = None          # valid|expired|forbidden|no_entitlement|unreachable
    pat_health_checked_at: int | None = None
    total_credit: int | None     # nano-AIU
    pledged_surplus: int | None  # nano-AIU


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
    # Public credit cycle (givers only; nano-AIU; None for consumers or
    # unlimited entitlements). Public by design since 2026-07-11 — visitors
    # see the same bar the Host sees on their own profile.
    entitlement: int | None = None
    used: int | None = None
    pledged: int | None = None
    pledged_consumed: int | None = None
    pledged_remaining: int | None = None
    donated_consumed: int | None = None
    donated_remaining: int | None = None
    left: int | None = None
    unlimited: bool = False


class OwnProfileDTO(CamelModel):
    # Credit fields are RAW nano-AIU (the frontend `aiu()` helper divides by
    # NANO_PER_AIU for display).
    user: PublicUserDTO
    total_credit: int | None     # nano-AIU; None for consumers
    pledged_surplus: int | None  # nano-AIU; None for consumers
    retained: int | None         # nano-AIU; None for consumers
    donated_so_far: int          # nano-AIU
    consumed: int                # nano-AIU
    donations_received: int      # nano-AIU (total grants received this cycle)
    donations_received_consumed: int = 0   # nano-AIU of received grants already burned
    donations_received_remaining: int = 0  # nano-AIU of received grants still available
    donations_received_from_pool: int = 0  # nano-AIU of the received total that came from the shared pool
    re_donated: int = 0                    # nano-AIU of received credit passed on to other requests
    returned_to_pool: int = 0              # nano-AIU of received credit moved into the shared pool
    entitlement: int | None = None       # nano-AIU; -1*NANO sentinel never used — see unlimited
    remaining: int | None = None
    used: int | None = None
    pledged: int | None = None
    donated: int | None = None
    left: int | None = None
    pledged_consumed: int | None = None
    donated_consumed: int | None = None
    donated_remaining: int | None = None   # nano-AIU; max(0, donated - donatedConsumed)
    pledged_remaining: int | None = None    # nano-AIU; pledge not yet drawn from pool
    reset_date: str | None = None
    unlimited: bool = False
    quota_stale: bool = False
    tier: str | None = None         # aristocracy tier; None for consumers
    net: int | None = None          # nano-AIU donated - consumed; None for consumers
    net_to_next: int | None = None  # nano-AIU to overtake next-higher giver; None if top/newcomer


ROLE_TO_REQUESTER: dict[Role, str] = {Role.GIVER: "pro", Role.CONSUMER: "noob"}


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    return "".join(p[0].upper() for p in parts[:2])


def build_public_request(store, get_user, r: Request, now: int, viewer_id: str | None = None) -> PublicRequestDTO:
    funded = store.request_funded(r.id)
    user = get_user(r.requester_id)
    name = user["display_name"] if user else r.requester_id
    status = derive_status(funded, r.amount_needed, r.expires_at, now, r.cancelled_at)
    # Directed requests store the target as a user id (the client sends userId);
    # resolve it to a display name for rendering. Legacy rows that stored a raw
    # name (no matching user) render verbatim; an unresolved id-shaped target is a
    # since-deleted user and renders as "Unknown user" rather than a raw uuid.
    target = r.target
    if target:
        target_user = get_user(target)
        if target_user:
            target = target_user["display_name"]
        elif len(target) == 32 and all(c in "0123456789abcdef" for c in target):
            target = "Unknown user"
    return PublicRequestDTO(
        id=r.id, requester_id=r.requester_id, requester_name=name, initials=initials(name),
        requester_role=ROLE_TO_REQUESTER[r.requester_role],
        amount_needed=r.amount_needed, amount_funded=funded,
        funded_consumed=store.request_consumed(r.id),
        reason=r.reason, target=target, created_at=r.created_at,
        expires_at=r.expires_at, status=status.value,
        donor_count=store.request_donor_count(r.id),
        is_own=(viewer_id is not None and viewer_id == r.requester_id),
        pool_funded=store.request_pool_funded(r.id),
    )
