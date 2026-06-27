"""Server-agnostic dashboard aggregation for the CTC accounting engine."""
from __future__ import annotations

from .leaderboard import LeaderboardUser, build_leaderboard
from ..domain.types import RequestStatus, Role


_SEVEN_DAYS = 7 * 24 * 3600


def build_dashboard(engine, users: list[LeaderboardUser], cycle_id: str, now: int) -> dict:
    """
    Aggregate dashboard metrics for a given cycle.

    Returns a dict with exactly these keys:
        pledged, retained, rotated, donatedToNonPat, donatedThisWeek,
        fulfillmentRate, activeGivers, activeConsumers,
        openCount, closedCount, activity, leaderboardSnapshot
    """
    conn = engine.store.conn

    # --- giver set (ids with a giver_cycle record) ---
    giver_rows = conn.execute(
        "SELECT giver_id, pledge FROM giver_cycles WHERE cycle_id=?", (cycle_id,)
    ).fetchall()
    giver_ids: set[str] = {r["giver_id"] for r in giver_rows}

    # pledged: Σ pledge over all giver_cycles
    pledged = sum(r["pledge"] for r in giver_rows)

    # retained: Σ personal_remaining per giver
    retained = sum(engine.personal_remaining(cycle_id, gid) for gid in giver_ids)

    # --- consumption events for this cycle ---
    event_rows = conn.execute(
        "SELECT consumer_id, source_giver_id, bucket, credits, ts "
        "FROM consumption_events WHERE cycle_id=? AND bucket IN ('pool','grant')",
        (cycle_id,),
    ).fetchall()

    rotated = 0
    donated_to_non_pat = 0
    donated_this_week = 0
    week_cutoff = now - _SEVEN_DAYS

    for row in event_rows:
        cid = row["consumer_id"]
        credits = row["credits"]
        ts = row["ts"]
        is_giver_consumer = cid in giver_ids
        if is_giver_consumer:
            rotated += credits
        else:
            donated_to_non_pat += credits
        if ts >= week_cutoff:
            donated_this_week += credits

    # --- fulfillmentRate ---
    request_rows = conn.execute(
        "SELECT id, expires_at FROM requests WHERE cycle_id=?", (cycle_id,)
    ).fetchall()
    total_requests = len(request_rows)
    fulfilled_count = 0
    open_count = 0
    closed_count = 0
    for rrow in request_rows:
        status = engine.request_status(rrow["id"], now)
        if status == RequestStatus.FULFILLED:
            fulfilled_count += 1
            closed_count += 1
        elif status == RequestStatus.EXPIRED:
            closed_count += 1
        else:
            open_count += 1

    fulfillment_rate = (
        int(fulfilled_count * 100 // total_requests) if total_requests > 0 else 0
    )

    # --- distinct consumers this cycle (used by both tallies below) ---
    all_consumer_rows = conn.execute(
        "SELECT DISTINCT consumer_id FROM consumption_events WHERE cycle_id=?",
        (cycle_id,),
    ).fetchall()
    all_consumers = {r["consumer_id"] for r in all_consumer_rows}

    # --- activeGivers: a giver is an "active host" if they have a license (PAT)
    # connected, OR pledged>0, OR appear as a source in consumption events, OR
    # consumed anything this cycle. The PAT clause matters when the shared pool
    # is off (pledge is forced to 0 then), so a connected host counts before it
    # has run anything. The consumed clause catches a host who exhausted their
    # own quota and used the marketplace (0 credits left, never sourced/pledged):
    # they are still a host and must not vanish from both tallies. ---
    givers_with_pat_rows = conn.execute("SELECT user_id FROM giver_pats").fetchall()
    givers_with_pat = {r["user_id"] for r in givers_with_pat_rows}
    givers_with_pledge = {r["giver_id"] for r in giver_rows if r["pledge"] > 0}
    givers_with_activity_rows = conn.execute(
        "SELECT DISTINCT source_giver_id FROM consumption_events WHERE cycle_id=?",
        (cycle_id,),
    ).fetchall()
    givers_with_activity = {r["source_giver_id"] for r in givers_with_activity_rows}
    # Only count users that are actually givers (have giver_cycle records)
    active_givers = len(
        (givers_with_pat | givers_with_pledge | givers_with_activity | all_consumers)
        & giver_ids
    )

    # --- activeConsumers: distinct consumer_ids in events that are NOT givers ---
    active_consumers = sum(1 for cid in all_consumers if cid not in giver_ids)

    # --- activity: up to 8 most recent consumption events ---
    activity_rows = conn.execute(
        "SELECT ts, consumer_id, bucket, credits "
        "FROM consumption_events WHERE cycle_id=? "
        "ORDER BY ts DESC, rowid DESC LIMIT 8",
        (cycle_id,),
    ).fetchall()
    name_by_id = {u.user_id: u.name for u in users}
    activity = [
        {
            "time": str(row["ts"]),
            "kind": "consume",
            "actorId": row["consumer_id"],
            "detail": f"{name_by_id.get(row['consumer_id'], row['consumer_id'][:8])} via {row['bucket']}",
            "amount": str(row["credits"]),
        }
        for row in activity_rows
    ]

    # --- leaderboardSnapshot ---
    lb = build_leaderboard(engine, users, cycle_id)
    # Expose generous + topConsumers (merge topPro + topNoob into a unified list)
    top_consumers_map: dict[str, dict] = {}
    for entry in lb.get("topPro", []) + lb.get("topNoob", []):
        name = entry["name"]
        agg = top_consumers_map.setdefault(name, {"userId": entry.get("userId"), "value": 0})
        agg["value"] += entry["value"]
    top_consumers = sorted(
        [{"userId": v["userId"], "name": k, "value": v["value"]}
         for k, v in top_consumers_map.items()],
        key=lambda x: x["value"],
        reverse=True,
    )[:5]

    leaderboard_snapshot = {
        "generous": lb.get("generous", []),
        "topConsumers": top_consumers,
    }

    return {
        "pledged": pledged,
        "retained": retained,
        "rotated": rotated,
        "donatedToNonPat": donated_to_non_pat,
        "donatedThisWeek": donated_this_week,
        "fulfillmentRate": fulfillment_rate,
        "activeGivers": active_givers,
        "activeConsumers": active_consumers,
        "openCount": open_count,
        "closedCount": closed_count,
        "activity": activity,
        "leaderboardSnapshot": leaderboard_snapshot,
    }


def build_cycle_report(engine, users: list[LeaderboardUser], cycle_id: str, now: int) -> dict:
    """
    Aggregate per-cycle history report.

    Returns a dict with exactly these keys:
        id, label, pledged, donated, toNonPat, toPat,
        reqFilled, reqTotal, reqPat, reqNonPat, fills, winners
    """
    conn = engine.store.conn

    # --- id, label from cycle row ---
    row = conn.execute(
        "SELECT id, label, starts_at, ends_at, status FROM cycles WHERE id=?",
        (cycle_id,),
    ).fetchone()
    cycle_id_val = row["id"]
    cycle_label = row["label"]

    # --- pledged: Σ gc.pledge over all giver_cycles for this cycle ---
    gcs = engine.store.all_giver_cycles(cycle_id)
    pledged = sum(gc.pledge for gc in gcs)

    # --- budget vs used: total credit the company had (Σ giver quota) vs total
    # credit actually used this cycle (ALL consumption — givers' own usage plus
    # pool/grant flowing to other givers and to consumers). Unused = budget−used
    # = the sum of each giver's leftover credit at cycle end. ---
    budget_total = sum(gc.quota for gc in gcs)
    used_total = conn.execute(
        "SELECT COALESCE(SUM(credits), 0) FROM consumption_events WHERE cycle_id=?",
        (cycle_id,),
    ).fetchone()[0]

    # --- build user lookup for O(1) is_giver checks ---
    user_map = {u.user_id: u for u in users}

    # --- consumption events (pool + grant buckets) for this cycle ---
    event_rows = conn.execute(
        "SELECT consumer_id, source_giver_id, credits "
        "FROM consumption_events WHERE cycle_id=? AND bucket IN ('pool','grant')",
        (cycle_id,),
    ).fetchall()

    to_pat = 0
    to_non_pat = 0
    for ev in event_rows:
        cid = ev["consumer_id"]
        credits = ev["credits"]
        user = user_map.get(cid)
        # unknown consumer → treat as non-giver
        is_giver = user.is_giver if user is not None else False
        if is_giver:
            to_pat += credits
        else:
            to_non_pat += credits

    donated = to_pat + to_non_pat

    # --- request counts ---
    request_rows = conn.execute(
        "SELECT id, requester_role FROM requests WHERE cycle_id=?",
        (cycle_id,),
    ).fetchall()

    req_total = len(request_rows)
    req_filled = 0
    req_pat = 0
    req_non_pat = 0

    giver_role_val = Role.GIVER.value
    consumer_role_val = Role.CONSUMER.value

    for rrow in request_rows:
        status = engine.request_status(rrow["id"], now)
        if status == RequestStatus.FULFILLED:
            req_filled += 1
        role = rrow["requester_role"]
        if role == giver_role_val:
            req_pat += 1
        elif role == consumer_role_val:
            req_non_pat += 1

    # --- fills: top 5 donors from grants table grouped by donor_id ---
    grant_rows = conn.execute(
        "SELECT donor_id, SUM(amount) AS total_amount, COUNT(*) AS n_grants "
        "FROM grants WHERE cycle_id=? GROUP BY donor_id "
        "ORDER BY total_amount DESC LIMIT 5",
        (cycle_id,),
    ).fetchall()

    fills = []
    for grow in grant_rows:
        donor_id = grow["donor_id"]
        user = user_map.get(donor_id)
        name = user.name if user is not None else donor_id
        fills.append({
            "who": name,
            "amount": int(grow["total_amount"]),
            "count": int(grow["n_grants"]),
        })

    # --- winners from leaderboard (top_n=1) ---
    lb = build_leaderboard(engine, users, cycle_id, top_n=1)

    _default = {"name": "—", "value": 0}

    winners: dict = {
        "generous": lb["generous"][0] if lb["generous"] else _default,
        "pro": lb["topPro"][0] if lb["topPro"] else _default,
        "noob": lb["topNoob"][0] if lb["topNoob"] else _default,
    }

    # --- rotator: giver with max Σ pool/grant credits sourced from them consumed by a *different giver* ---
    rotator_rows = conn.execute(
        "SELECT source_giver_id, SUM(credits) AS donated_to_givers "
        "FROM consumption_events "
        "WHERE cycle_id=? AND bucket IN ('pool','grant') AND consumer_id <> source_giver_id "
        "GROUP BY source_giver_id",
        (cycle_id,),
    ).fetchall()

    best_rotator_id = None
    best_rotator_val = 0
    giver_ids = {u.user_id for u in users if u.is_giver}

    for rrow in rotator_rows:
        sid = rrow["source_giver_id"]
        if sid not in giver_ids:
            continue
        # sum only credits donated to other givers
        giver_to_giver = conn.execute(
            "SELECT SUM(credits) FROM consumption_events "
            "WHERE cycle_id=? AND bucket IN ('pool','grant') "
            "AND source_giver_id=? AND consumer_id <> source_giver_id "
            "AND consumer_id IN ({})".format(",".join("?" * len(giver_ids))),
            (cycle_id, sid, *giver_ids),
        ).fetchone()
        val = int(giver_to_giver[0] or 0)
        if val > best_rotator_val:
            best_rotator_val = val
            best_rotator_id = sid

    if best_rotator_id is not None and best_rotator_val > 0:
        rotator_user = user_map.get(best_rotator_id)
        rotator_name = rotator_user.name if rotator_user is not None else best_rotator_id
        winners["rotator"] = {"name": rotator_name, "value": best_rotator_val}

    return {
        "id": cycle_id_val,
        "label": cycle_label,
        "pledged": pledged,
        "budgetTotal": budget_total,
        "usedTotal": used_total,
        "donated": donated,
        "toNonPat": to_non_pat,
        "toPat": to_pat,
        "reqFilled": req_filled,
        "reqTotal": req_total,
        "reqPat": req_pat,
        "reqNonPat": req_non_pat,
        "fills": fills,
        "winners": winners,
    }


def build_history(engine, users: list[LeaderboardUser], now: int) -> list[dict]:
    """
    Return a list of cycle reports, newest-first (ordered by starts_at DESC).
    """
    conn = engine.store.conn
    rows = conn.execute(
        "SELECT id FROM cycles ORDER BY starts_at DESC"
    ).fetchall()
    return [build_cycle_report(engine, users, row["id"], now) for row in rows]
