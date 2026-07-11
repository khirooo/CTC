from __future__ import annotations

import time
from dataclasses import dataclass

from ..accounting.engine import AccountingEngine
from ..auth.identity import ConsumerIdentity, IdentityProvider, PatRegistry
from ..domain.types import Bucket


@dataclass(frozen=True)
class Source:
    bucket: Bucket
    giver_id: str
    pat: str
    grant_id: str | None = None


# A GitHub auto-mode `session_token` (minted by POST /models/session) is bound
# to the specific giver identity that requested it — presenting it while
# authenticated as a *different* giver gets rejected upstream with
# `401 Invalid auto-mode selector`. Pin the giver chosen for a client's
# /models/session bootstrap call so the client's subsequent billable calls
# (within the token's lifetime) reuse the same giver. Bounds guard against a
# missing/malformed `expires_at` from upstream.
SESSION_PIN_MIN_TTL_S = 60
SESSION_PIN_MAX_TTL_S = 30 * 60


class AttributionService:
    def __init__(self, engine: AccountingEngine, identity: IdentityProvider, pats: PatRegistry):
        self.engine = engine
        self.identity = identity
        self.pats = pats
        # (consumer_user_id, client_session_id) -> (Source, expires_at_epoch_s)
        self._session_pins: dict[tuple[str, str], tuple[Source, int]] = {}

    def resolve_consumer(self, fake_token: str) -> ConsumerIdentity | None:
        return self.identity.resolve(fake_token)

    @staticmethod
    def _dead(health: dict | None, giver_id: str) -> bool:
        """Return True iff health explicitly marks giver_id as exhausted (remaining <= 0).
        None/absent means unknown -> ALLOW (return False)."""
        if not health:
            return False
        r = health.get(giver_id)
        return r is not None and r <= 0

    def _grant_source(self, cycle_id: str, consumer_id: str, *,
                      health: dict | None = None,
                      exclude: frozenset = frozenset()) -> Source | None:
        for g in self.engine.active_grants(cycle_id, consumer_id):
            if g.id in exclude or self._dead(health, g.donor_id):
                continue
            pat = self.pats.pat_for(g.donor_id)
            if pat is not None:
                return Source(Bucket.GRANT, g.donor_id, pat, g.id)
        return None

    def select_source(self, cycle_id: str, consumer: ConsumerIdentity, *,
                      health: dict | None = None,
                      exclude: frozenset = frozenset()) -> Source | None:
        """First eligible bucket in the credit-model order, including the PAT to
        forward. None means 'no credit available' -> caller blocks with 402.

        Args:
            health: giver_id -> live remaining (int) or None (unknown -> allow).
                    A bucket is skipped iff health[giver_id] is not None and <= 0.
                    Pass None or omit to treat all givers as healthy.
            exclude: set of keys to skip entirely. GRANT sources are keyed by
                     grant_id; OWN sources are keyed by giver_id.
        """
        if getattr(self.engine.config, "participants_mode", "givers_and_consumers") \
                == "givers_only" and not consumer.is_giver:
            return None
        uid = consumer.user_id
        if consumer.is_giver:
            # OWN -> GRANT
            if uid not in exclude and not self._dead(health, uid) \
                    and self.engine.personal_remaining(cycle_id, uid) > 0:
                pat = self.pats.pat_for(uid)
                if pat is not None:
                    return Source(Bucket.OWN, uid, pat)
            return self._grant_source(cycle_id, uid, health=health, exclude=exclude)
        # non-PAT consumer: GRANT only. Shared-pool credit reaches consumers as
        # source='pool' grants created in the marketplace, not by auto-routing.
        return self._grant_source(cycle_id, uid, health=health, exclude=exclude)

    def _sweep_expired_pins(self, now: float) -> None:
        """Drop stale pins opportunistically. Called on every insert/lookup so
        the dict never grows unbounded; cheap since it's a single dict scan and
        the proxy is a single asyncio process (no concurrent mutation)."""
        expired = [k for k, (_src, exp) in self._session_pins.items() if exp <= now]
        for k in expired:
            del self._session_pins[k]

    def pin_source(self, session_key: tuple[str, str] | None, source: Source,
                    expires_at: int | None, *, now: float | None = None) -> None:
        """Remember which giver was chosen for a client's /models/session
        bootstrap call, so the client's next billable call (same
        consumer + x-client-session-id) can reuse it instead of letting
        select_source()'s independent, dynamic pick land on a different
        giver -> upstream 401 "Invalid auto-mode selector".

        `expires_at` is the epoch-seconds value from the /models/session
        response; clamped to [SESSION_PIN_MIN_TTL_S, SESSION_PIN_MAX_TTL_S]
        from now so a missing/malformed/clock-skewed value can't pin forever
        or expire before it's ever used.
        """
        if session_key is None:
            return
        now = time.time() if now is None else now
        self._sweep_expired_pins(now)
        ttl = SESSION_PIN_MAX_TTL_S
        if isinstance(expires_at, (int, float)):
            ttl = max(SESSION_PIN_MIN_TTL_S, min(SESSION_PIN_MAX_TTL_S, expires_at - now))
        self._session_pins[session_key] = (source, now + ttl)

    def _bucket_has_headroom(self, cycle_id: str, source: Source) -> bool:
        """Does the pinned source's bucket still have credit to draw? Mirrors the
        gate select_source applies, so a pin can't be a 30-min bypass of the
        credit model (debit runs with allow_overshoot=True)."""
        if source.bucket == Bucket.OWN:
            return self.engine.personal_remaining(cycle_id, source.giver_id) > 0
        if source.bucket == Bucket.GRANT:
            return (source.grant_id is not None
                    and self.engine.grant_remaining(cycle_id, source.grant_id) > 0)
        if source.bucket == Bucket.POOL:
            return self.engine.pledge_remaining(cycle_id, source.giver_id) > 0
        return True

    def pinned_source(self, session_key: tuple[str, str] | None, *,
                      cycle_id: str | None = None,
                      health: dict | None = None, now: float | None = None) -> Source | None:
        """The giver pinned for this (consumer, client_session_id) pair, if
        any, not yet expired, not reported dead in `health`, and — when
        `cycle_id` is given — whose bucket still has headroom. None means "no pin,
        or it's no longer usable" -> caller should fall back to select_source()."""
        if session_key is None:
            return None
        now = time.time() if now is None else now
        self._sweep_expired_pins(now)
        entry = self._session_pins.get(session_key)
        if entry is None:
            return None
        source, expires_at = entry
        if expires_at <= now or self._dead(health, source.giver_id):
            return None
        if cycle_id is not None and not self._bucket_has_headroom(cycle_id, source):
            return None
        return source

    def any_giver_pat(self) -> str | None:
        """Any stored giver PAT, for non-billable bootstrap/validation calls
        (e.g. /copilot_internal/user, /copilot_internal/v2/token) that aren't
        metered and have no selected source but still need a real PAT upstream.
        Prefers a PAT last checked healthy so a non-billable call doesn't ride a
        dead PAT while a valid one exists (same shape as the /responses incident);
        falls back to any stored PAT (health None = unknown, not dead). No credit
        is consumed; returns None if no giver PAT exists."""
        fallback = None
        for giver_id in self.pats.list_givers():
            pat = self.pats.pat_for(giver_id)
            if pat is None:
                continue
            status = self.pats.pat_health_status(giver_id)
            if status == "valid":
                return pat
            if fallback is None:
                fallback = pat
        return fallback

    def debit(self, cycle_id: str, consumer: ConsumerIdentity, source: Source,
              cost_nano_aiu: int, ts: int) -> None:
        """Record the actual realized cost. Post-hoc: the spend already happened,
        so overshoot is allowed on the final residual record (the pre-gate in
        select_source is the gate).

        For GRANT sources, the cost is spilled across active grants in order —
        first the selected source grant (clamped to its remaining), then the
        consumer's other active grants in engine order (each clamped) — before
        any residual is recorded with overshoot on the original source.
        OWN/POOL sources skip the grant loop and fall straight to the residual
        record, matching the previous single-record behavior.
        """
        if cost_nano_aiu <= 0:
            return
        residual = cost_nano_aiu
        # 1) the selected source first (grant clamped to its remaining)
        order = []
        if source.bucket == Bucket.GRANT and source.grant_id:
            order.append((source.giver_id, source.grant_id))
            # 2) the consumer's other active grants, in engine order
            # Only spill across grants when the source is itself a GRANT bucket.
            # OWN and POOL sources skip this loop entirely — their overshoot is
            # absorbed by the original source bucket via allow_overshoot=True below.
            for g in self.engine.active_grants(cycle_id, consumer.user_id):
                if g.id != source.grant_id:
                    order.append((g.donor_id, g.id))
        for giver_id, grant_id in order:
            if residual <= 0:
                break
            room = self.engine.grant_remaining(cycle_id, grant_id)
            if room <= 0:
                continue
            take = min(room, residual)
            self.engine.record_consumption(cycle_id, consumer.user_id, giver_id,
                Bucket.GRANT, take, grant_id=grant_id, ts=ts, allow_overshoot=False)
            residual -= take
        # 3) anything left (all grants drained, or non-grant source) -> record on the
        # original source with overshoot allowed (spend already happened upstream).
        if residual > 0:
            self.engine.record_consumption(cycle_id, consumer.user_id, source.giver_id,
                source.bucket, residual, grant_id=source.grant_id, ts=ts, allow_overshoot=True)
