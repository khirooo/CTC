"""Server-agnostic dashboard aggregation for the CTC accounting engine."""
from __future__ import annotations

import datetime
import json

from .leaderboard import LeaderboardUser, build_leaderboard
from ..domain.config import NANO_PER_AIU
from ..domain.types import RequestStatus, Role


_SEVEN_DAYS = 7 * 24 * 3600


def build_dashboard(engine, users: list[LeaderboardUser], cycle_id: str, now: int) -> dict:
    """
    Aggregate dashboard metrics for a given cycle.

    Returns a dict with exactly these keys:
        pledged, retained, rotated, donatedToNonPat, donatedThisWeek,
        fulfillmentRate, activeGivers, activeConsumers, poolGuests,
        openCount, closedCount, activity, leaderboardSnapshot,
        cycleLabel, cycleNumber, resetDate, daysLeft
    """
    conn = engine.store.conn

    # --- current cycle identity: label, 1-based ordinal (by start), reset info ---
    cyc = conn.execute(
        "SELECT label, starts_at, ends_at FROM cycles WHERE id=?", (cycle_id,)
    ).fetchone()
    cycle_label = cyc["label"] if cyc else ""
    cycle_number = 0
    reset_date = None
    days_left = 0
    if cyc:
        cycle_number = conn.execute(
            "SELECT COUNT(*) FROM cycles WHERE starts_at <= ?", (cyc["starts_at"],)
        ).fetchone()[0]
        ends_at = cyc["ends_at"]
        days_left = max(0, -(-(ends_at - now) // 86400))  # ceil, floored at 0
        reset_date = datetime.datetime.fromtimestamp(
            min(ends_at, 32503680000), datetime.timezone.utc).strftime("%Y-%m-%d")

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

    # --- poolGuests: distinct consumer_ids with a POOL-bucket event this cycle
    # that are NOT givers. Narrower than activeConsumers (which counts ANY
    # bucket, including directed 'grant' chip-ins): this is specifically guests
    # currently drawing from the SHARED POOL. ---
    pool_consumer_rows = conn.execute(
        "SELECT DISTINCT consumer_id FROM consumption_events "
        "WHERE cycle_id=? AND bucket='pool'",
        (cycle_id,),
    ).fetchall()
    pool_consumers = {r["consumer_id"] for r in pool_consumer_rows}
    pool_guests = sum(1 for cid in pool_consumers if cid not in giver_ids)

    # --- activity: consumption events from the last 24h (capped), newest-first.
    # Both the shared pool ('pool' bucket) and directed marketplace chip-ins
    # ('grant' bucket) flow through here; `kind` carries the bucket so the client
    # can label/colour the two streams distinctly. Own-quota ('own'/'bypass')
    # burn is excluded — it isn't marketplace/pool traffic. Cap keeps the payload
    # bounded on very busy days. ---
    DAY = 24 * 3600
    ACTIVITY_CAP = 100
    activity_rows = conn.execute(
        "SELECT ts, consumer_id, bucket, credits "
        "FROM consumption_events WHERE cycle_id=? AND bucket IN ('pool','grant') AND ts >= ? "
        "ORDER BY ts DESC, rowid DESC LIMIT ?",
        (cycle_id, now - DAY, ACTIVITY_CAP),
    ).fetchall()
    name_by_id = {u.user_id: u.name for u in users}
    activity = [
        {
            # Display-ready strings (the frontend renders these verbatim):
            # HH:MM clock time (UTC) and AIU amount, not raw epoch / nano-AIU.
            "time": datetime.datetime.fromtimestamp(
                row["ts"], datetime.timezone.utc).strftime("%H:%M"),
            # 'pool' = drew from the shared pool; 'grant' = used a directed chip-in.
            "kind": row["bucket"],
            "actorId": row["consumer_id"],
            "detail": name_by_id.get(row["consumer_id"], row["consumer_id"][:8]),
            "amount": f"{row['credits'] / NANO_PER_AIU:.2f} AIU",
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
        "poolGuests": pool_guests,
        "openCount": open_count,
        "closedCount": closed_count,
        "activity": activity,
        "leaderboardSnapshot": leaderboard_snapshot,
        "cycleLabel": cycle_label,
        "cycleNumber": cycle_number,
        "resetDate": reset_date,
        "daysLeft": days_left,
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

    The active cycle is always computed live so the current period stays
    real-time. An archived cycle is served from a frozen snapshot: the first time
    it is requested after archival its report is computed, persisted, and returned;
    every later request returns that stored copy. This keeps a past report's
    winner/donor *labels* from drifting as live user roles/names change later
    (the credit totals, derived from frozen events, never drift either way).
    """
    conn = engine.store.conn
    rows = conn.execute(
        "SELECT id, status FROM cycles ORDER BY starts_at DESC"
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        cycle_id = row["id"]
        if row["status"] == "active":
            out.append(build_cycle_report(engine, users, cycle_id, now))
            continue
        snapshot = engine.store.get_cycle_report(cycle_id)
        if snapshot is not None:
            out.append(json.loads(snapshot))
            continue
        # archived but not yet frozen → compute once and persist (freeze on first read)
        report = build_cycle_report(engine, users, cycle_id, now)
        engine.store.save_cycle_report(cycle_id, json.dumps(report), now)
        out.append(report)
    return out
