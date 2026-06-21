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

    def _grant_source(self, cycle_id: str, consumer_id: str) -> Source | None:
        for g in self.engine.active_grants(cycle_id, consumer_id):
            pat = self.pats.pat_for(g.donor_id)
            if pat is not None:
                return Source(Bucket.GRANT, g.donor_id, pat, g.id)
        return None

    def select_source(self, cycle_id: str, consumer: ConsumerIdentity) -> Source | None:
        """First eligible bucket in the credit-model order, including the PAT to
        forward. None means 'no credit available' -> caller blocks with 402."""
        uid = consumer.user_id
        if consumer.is_giver:
            # OWN -> GRANT
            if self.engine.personal_remaining(cycle_id, uid) > 0:
                pat = self.pats.pat_for(uid)
                if pat is not None:
                    return Source(Bucket.OWN, uid, pat)
            return self._grant_source(cycle_id, uid)
        # non-PAT consumer: GRANT -> POOL
        grant = self._grant_source(cycle_id, uid)
        if grant is not None:
            return grant
        if self.engine.allowance_remaining(cycle_id, uid) > 0:
            givers = self.engine.givers_with_pool_capacity(cycle_id)  # [(giver_id, remaining)]
            for giver_id, _rem in sorted(givers, key=lambda t: t[1], reverse=True):
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
