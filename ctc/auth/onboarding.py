from __future__ import annotations

from ..domain.config import NANO_PER_AIU


class PatInvalid(Exception): ...
class PatIdentityMismatch(Exception): ...


async def validate_and_store_pat(registry, engine, http_get_user, cycle_id, user_id,
                                 ghe_login, pat, now, effective_config=None,
                                 enforce_identity=True) -> dict:
    try:
        user = await http_get_user(pat)
    except PatIdentityMismatch:
        raise
    except Exception as e:  # network / non-200 surfaced by the caller's fetcher
        raise PatInvalid(str(e))
    # Under GitLab auth the CTC login is a GitLab username, which can never match a
    # PAT's GHE owner, so the ownership check is always skipped (enforce_identity=False).
    # The branch is retained for tests that exercise identity enforcement directly.
    if enforce_identity and user.get("login") != ghe_login:
        raise PatIdentityMismatch(f"PAT belongs to {user.get('login')}, not {ghe_login}")
    pi = user.get("quota_snapshots", {}).get("premium_interactions", {})
    ent = pi.get("entitlement")
    if not ent or ent <= 0:
        raise PatInvalid("no premium_interactions entitlement on this PAT")
    remaining = pi.get("remaining")
    # Missing `remaining` means GitHub did not report headroom; assume spent (0).
    avail = remaining if remaining is not None else 0
    avail = max(0, int(avail))
    reset_date = user.get("quota_reset_date")
    avail_nano = avail * NANO_PER_AIU
    quota_nano = int(ent) * NANO_PER_AIU          # quota = entitlement ceiling
    engine.set_quota(cycle_id, user_id, quota_nano)
    registry.store_pat(user_id, pat, now)
    # The PAT just answered /copilot_internal/user with an entitlement, so it is
    # definitively healthy right now; the periodic checker takes over from here.
    registry.store.set_pat_health_ok(user_id, "valid", now)
    registry.store.set_user_role(user_id, "giver")
    registry.store.set_giver_quota_snapshot(user_id, int(ent), avail, reset_date, now)
    pct = getattr(effective_config, "default_pledge_pct", 0) if effective_config else 0
    gc = engine.store.get_giver_cycle(cycle_id, user_id)
    if pct > 0 and (gc is None or gc.pledge == 0):
        # Default pledge = pct% of what they have LEFT (remaining), not entitlement.
        engine.set_pledge(cycle_id, user_id, avail_nano * pct // 100)
        gc = engine.store.get_giver_cycle(cycle_id, user_id)
    # Book any burn that happened before they connected to CTC as their own use.
    engine.reconcile_giver(cycle_id, user_id,
                           {"entitlement": int(ent), "remaining": avail})
    pledged_nano = gc.pledge if gc else 0
    used_nano = engine.store.own_consumed(cycle_id, user_id) + engine.store.bypass_consumed(cycle_id, user_id)
    return {"ghe_login": ghe_login, "quota_aiu": avail,
            "entitlement_aiu": int(ent), "remaining_aiu": avail, "reset_date": reset_date,
            "pledged_nano": pledged_nano, "used_nano": used_nano}
