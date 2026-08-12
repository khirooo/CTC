"""One-time repair for phantom shared-pool capacity backed by dead PATs.

The incident: a fresh cycle opened showing 3,103 AIU "available" in the shared
pool with nobody having donated. Two givers' PATs had expired, but the rollover
seeded the new cycle straight from `giver_pats` (whose `entitlement` snapshot is
only refreshed on a VALID verdict and never cleared) and carried their previous
pledges forward — 2,103 + 1,000 AIU of capacity that nothing could ever draw.

Going forward this cannot recur: the rollover no longer carries a pledge for a
definitively dead PAT, `pool_available`/`givers_with_pool_capacity` exclude those
givers, and the PAT-health sweep retracts the pledge as soon as it sees a dead
verdict (see ctc/accounting/engine.py and ctc/auth/pat_health.py). This script
cleans up the pledges that are ALREADY on the current cycle's rows so the pool
number is honest without waiting for the next health sweep.

Usage:
  python -m tools.retract_dead_pledges                 # dry-run report (default)
  python -m tools.retract_dead_pledges --apply
  python -m tools.retract_dead_pledges --apply --yes    # non-interactive
  python -m tools.retract_dead_pledges --giver alice --apply

Exit code: 0 on success (or dry-run), non-zero on config/usage error or failure.

OPERATIONAL NOTES:
  * Only the UNDRAWN part of a pledge is retracted. The floor is `pledge_used`
    (legacy POOL events plus booked marketplace pool fills), so no history is
    rewritten and the engine's own invariants hold. Idempotent — a second run
    retracts 0.
  * Health verdicts are read, never written. A giver marked "unreachable" (last
    check errored, e.g. GHE 502s during an outage) is NOT touched: the surviving
    definitive verdict is what counts. Only expired/forbidden/no_entitlement
    qualify.
  * Not a permanent demotion: reconnecting a working PAT re-applies the default
    pledge, because validate_and_store_pat treats pledge == 0 as unpledged.
  * Safe to run with the proxy and control plane up — the write goes through the
    shared DB open helper (WAL + busy_timeout) and one BEGIN IMMEDIATE.
  * Env: CTC_DB_PATH only. No secret and no network access are needed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from ctc.accounting.wiring import build_live_engine
from ctc.domain.config import NANO_PER_AIU
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db


class RepairError(Exception):
    """Raised when a --giver argument cannot be resolved to a user."""


def _resolve_giver(store: AuthStore, token: str) -> str:
    """Map a --giver argument (user id OR GitLab login) to a user id."""
    if store.get_user_by_id(token) is not None:
        return token
    user = store.get_user_by_login(token)
    if user is not None:
        return user["id"]
    raise RepairError(f"no user matches {token!r} (tried id and login)")


def find_dead_pledges(engine, store, cycle_id, only: set[str] | None = None) -> list[dict]:
    """Report every giver on `cycle_id` holding an undrawn pledge behind a
    definitively dead PAT.

    Returns one dict per affected giver: {"giver_id", "login", "health",
    "pledge", "used", "retractable"}. Read-only.
    """
    dead = engine.dead_pat_givers()
    out = []
    for gc in engine.store.all_giver_cycles(cycle_id):
        if gc.giver_id not in dead:
            continue
        if only is not None and gc.giver_id not in only:
            continue
        used = engine.pledge_used(cycle_id, gc.giver_id)
        retractable = max(0, gc.pledge - used)
        if retractable <= 0:
            continue
        user = store.get_user_by_id(gc.giver_id)
        health = store.get_pat_health(gc.giver_id) or {}
        out.append({"giver_id": gc.giver_id,
                    "login": (user or {}).get("ghe_login", "?"),
                    "health": health.get("status"),
                    "pledge": gc.pledge,
                    "used": used,
                    "retractable": retractable})
    return out


def _aiu(nano: int) -> str:
    return f"{nano} nano ({nano / NANO_PER_AIU:,.0f} AIU)"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="retract_dead_pledges")
    ap.add_argument("--giver", action="append", default=[],
                    help="restrict to this user id or GitLab login (repeatable)")
    ap.add_argument("--apply", action="store_true",
                    help="write the retraction (default is a dry-run report)")
    ap.add_argument("--yes", action="store_true", help="skip the interactive confirm")
    args = ap.parse_args(argv)

    db_path = os.environ.get("CTC_DB_PATH")
    if not db_path:
        print("retract_dead_pledges: CTC_DB_PATH is required", file=sys.stderr)
        return 2

    conn = connect(db_path)
    init_db(conn)
    store = AuthStore(conn)
    engine = build_live_engine(conn)
    cycle = engine.ensure_active_cycle(int(time.time()))

    try:
        only = {_resolve_giver(store, g) for g in args.giver} if args.giver else None
    except RepairError as e:
        print(f"retract_dead_pledges: {e}", file=sys.stderr)
        return 2

    before = engine.pool_available(cycle.id)
    rows = find_dead_pledges(engine, store, cycle.id, only)
    print(f"cycle={cycle.id}  pool_available={_aiu(before)}")
    if not rows:
        print("no dead-PAT pledges to retract — nothing to do.")
        return 0

    total = sum(r["retractable"] for r in rows)
    for r in rows:
        print(f"  {r['login']} ({r['giver_id']}) health={r['health']} "
              f"pledge={_aiu(r['pledge'])} drawn={_aiu(r['used'])} "
              f"-> retract {_aiu(r['retractable'])}")
    print(f"total retractable: {_aiu(total)}")

    if not args.apply:
        print("dry-run — nothing written. Re-run with --apply to commit.")
        return 0

    if not args.yes:
        print("=" * 70)
        print("This withdraws the undrawn pledge above from the shared pool.")
        print("Reconnecting a working PAT re-applies the default pledge.")
        print("=" * 70)
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("aborted.")
            return 1

    failures = 0
    for r in rows:
        try:
            n = engine.retract_pledge(cycle.id, r["giver_id"])
        except Exception as e:
            print(f"  {r['login']}: FAILED — {e}", file=sys.stderr)
            failures += 1
            continue
        print(f"  {r['login']}: retracted {_aiu(n)}")

    # pool_available already excludes dead-PAT givers, so the displayed number does
    # not move here — the retraction is what stops the pledge carrying forward and
    # what makes the giver's own profile honest.
    print(f"pool_available now {_aiu(engine.pool_available(cycle.id))}")
    if failures:
        print(f"retract_dead_pledges: {failures} giver(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
