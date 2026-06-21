from __future__ import annotations

from ..domain.config import NANO_PER_AIU


class PatInvalid(Exception): ...
class PatIdentityMismatch(Exception): ...


async def validate_and_store_pat(registry, engine, http_get_user, cycle_id, user_id,
                                 ghe_login, pat, now, effective_config=None) -> dict:
    try:
        user = await http_get_user(pat)
    except PatIdentityMismatch:
        raise
    except Exception as e:  # network / non-200 surfaced by the caller's fetcher
        raise PatInvalid(str(e))
    if user.get("login") != ghe_login:
        raise PatIdentityMismatch(f"PAT belongs to {user.get('login')}, not {ghe_login}")
    pi = user.get("quota_snapshots", {}).get("premium_interactions", {})
    ent = pi.get("entitlement")
    if not ent or ent <= 0:
        raise PatInvalid("no premium_interactions entitlement on this PAT")
    remaining = pi.get("remaining")
    avail = remaining if remaining is not None else ent
    avail = max(0, int(avail))
    reset_date = user.get("quota_reset_date")
    quota_nano = avail * NANO_PER_AIU
    engine.set_quota(cycle_id, user_id, quota_nano)
    registry.store_pat(user_id, pat, now)
    registry.store.set_user_role(user_id, "giver")
    registry.store.set_giver_quota_snapshot(user_id, int(ent), avail, reset_date, now)
    pct = getattr(effective_config, "default_pledge_pct", 0) if effective_config else 0
    gc = engine.store.get_giver_cycle(cycle_id, user_id)
    if pct > 0 and (gc is None or gc.pledge == 0):
        # Default pledge = pct% of what they have LEFT (remaining = quota_nano),
        # not of the entitlement/max. Only seed it when there's no pledge yet.
        engine.set_pledge(cycle_id, user_id, quota_nano * pct // 100)
        gc = engine.store.get_giver_cycle(cycle_id, user_id)
    pledged_nano = gc.pledge if gc else 0
    return {"ghe_login": ghe_login, "quota_aiu": avail,
            "entitlement_aiu": int(ent), "remaining_aiu": avail, "reset_date": reset_date,
            "pledged_nano": pledged_nano}
