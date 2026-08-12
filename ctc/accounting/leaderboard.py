from __future__ import annotations

from dataclasses import dataclass

from .tiers import TierInput, assign_tiers


@dataclass(frozen=True)
class LeaderboardUser:
    user_id: str
    name: str
    is_giver: bool


def giver_tier_inputs(engine, users, cycle_id):
    """TierInput for every giver who can still host. net = donated_live -
    consumed_from_others: 'taken' counts everything this giver drew from OTHER
    givers (pool draws AND grants received), excluding their own quota usage.
    This is the true mirror of donated_live (others burning this giver's gifts,
    pool and grant alike), so a host who only received a marketplace grant still
    counts as active.

    Givers whose PAT is definitively dead are left out entirely: a standing says
    "this host is carrying the marketplace", and a host whose license stopped
    working is not. They are unranked (tier/net null) until the license is
    rotated, which also drops them from the standings table, their own profile's
    tier line, and their public profile's tier. Their booked donations are
    untouched — the 'generous' track still credits what people really burned from
    them.
    """
    dead = engine.dead_pat_givers()
    return [
        TierInput(
            u.user_id, u.name,
            engine.donated_live(cycle_id, u.user_id),
            engine.consumed_from_others(cycle_id, u.user_id),
        )
        for u in users if u.is_giver and u.user_id not in dead
    ]


def build_leaderboard(engine, users: list[LeaderboardUser], cycle_id: str, top_n: int = 5) -> dict:
    """
    Compute the 3-track leaderboard from the accounting engine.

    Returns:
        {"generous": [...], "topPro": [...], "topNoob": [...], "standings": [...]}
        where each track entry is {"userId": str, "name": str, "value": int}
        and each standings entry is {"userId": str, "name": str, "net": int, "tier": str}.

    Tracks:
        - generous: users sorted by donated_live(cycle_id, user_id) descending, value > 0
        - topPro: only givers (is_giver=True) with a working license, sorted by
          consumed_total descending, value > 0
        - topNoob: only non-givers (is_giver=False), sorted by consumed_total descending, value > 0

    A giver whose PAT is definitively dead is dropped from the host-facing tracks
    (topPro and standings): both describe an active host, which they no longer are.
    'generous' keeps them, because what others already burned from their gifts
    really happened and does not stop being true when the token dies.
    """
    # Build user lookup by user_id for O(1) access
    user_map = {u.user_id: u for u in users}
    dead_givers = engine.dead_pat_givers()

    # Compute generous: all users with donated_live > 0, sorted descending
    generous_candidates = []
    for user in users:
        donated = engine.donated_live(cycle_id, user.user_id)
        if donated > 0:
            generous_candidates.append((user.user_id, user.name, donated))

    generous_candidates.sort(key=lambda x: x[2], reverse=True)
    generous = [{"userId": uid, "name": name, "value": value}
                for uid, name, value in generous_candidates[:top_n]]

    # Compute topPro: givers with a working license and consumed_total > 0, descending
    pro_candidates = []
    for user in users:
        if user.is_giver and user.user_id not in dead_givers:
            consumed = engine.consumed_total(cycle_id, user.user_id)
            if consumed > 0:
                pro_candidates.append((user.user_id, user.name, consumed))

    pro_candidates.sort(key=lambda x: x[2], reverse=True)
    top_pro = [{"userId": uid, "name": name, "value": value}
               for uid, name, value in pro_candidates[:top_n]]

    # Compute topNoob: non-givers with consumed_total > 0, sorted descending
    noob_candidates = []
    for user in users:
        if not user.is_giver:
            consumed = engine.consumed_total(cycle_id, user.user_id)
            if consumed > 0:
                noob_candidates.append((user.user_id, user.name, consumed))

    noob_candidates.sort(key=lambda x: x[2], reverse=True)
    top_noob = [{"userId": uid, "name": name, "value": value}
                for uid, name, value in noob_candidates[:top_n]]

    # Standings: aristocracy tiers over all givers (givers-only feature)
    standings = [
        {"userId": r.user_id, "name": r.name, "net": r.net, "tier": r.tier}
        for r in assign_tiers(giver_tier_inputs(engine, users, cycle_id))
    ]

    return {
        "generous": generous,
        "topPro": top_pro,
        "topNoob": top_noob,
        "standings": standings,
    }
