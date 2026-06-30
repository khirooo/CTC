from __future__ import annotations

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


class AttributionService:
    def __init__(self, engine: AccountingEngine, identity: IdentityProvider, pats: PatRegistry):
        self.engine = engine
        self.identity = identity
        self.pats = pats

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
                     grant_id; OWN/POOL sources are keyed by giver_id.
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
        # non-PAT consumer: GRANT -> POOL (POOL only when the shared pool is enabled)
        grant = self._grant_source(cycle_id, uid, health=health, exclude=exclude)
        if grant is not None:
            return grant
        if getattr(self.engine.config, "shared_pool_enabled", True) \
                and self.engine.allowance_remaining(cycle_id, uid) > 0:
            givers = self.engine.givers_with_pool_capacity(cycle_id)  # [(giver_id, remaining)]
            for giver_id, _rem in sorted(givers, key=lambda t: t[1], reverse=True):
                if giver_id in exclude or self._dead(health, giver_id):
                    continue
                pat = self.pats.pat_for(giver_id)
                if pat is not None:
                    return Source(Bucket.POOL, giver_id, pat)
        return None

    def any_giver_pat(self) -> str | None:
        """Any stored giver PAT, for non-billable bootstrap/validation calls
        (e.g. /copilot_internal/user, /copilot_internal/v2/token) that aren't
        metered and have no selected source but still need a real PAT upstream.
        No credit is consumed; returns None if no giver PAT exists."""
        for giver_id in self.pats.list_givers():
            pat = self.pats.pat_for(giver_id)
            if pat is not None:
                return pat
        return None

    def debit(self, cycle_id: str, consumer: ConsumerIdentity, source: Source,
              cost_nano_aiu: int, ts: int) -> None:
        """Record the actual realized cost. Post-hoc: the spend already happened,
        so overshoot is allowed (the pre-gate in select_source is the gate)."""
        if cost_nano_aiu <= 0:
            return
        self.engine.record_consumption(
            cycle_id, consumer.user_id, source.giver_id, source.bucket,
            cost_nano_aiu, grant_id=source.grant_id, ts=ts, allow_overshoot=True,
        )
