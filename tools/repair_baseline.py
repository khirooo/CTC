"""One-time repair for givers whose burn_baseline swallowed real out-of-band burn.

The incident: a giver's official Copilot plan showed 2,600 AIU burned this cycle
while CTC's ledger showed 800 — the missing 1,800 was absorbed into the lazy
`burn_baseline` capture (baseline := github_burn at first observation of the
cycle), so it could never surface as a BYPASS event. The reset-aware baseline
carry (see ctc/accounting/engine.py `_open_month_cycle`) prevents this going
forward, but a giver whose baseline already swallowed burn THIS cycle needs a
manual re-anchor to make their profile match GitHub.

This script re-anchors the giver's baseline to 0 for the current cycle, clears any
pending drift, then runs an immediate reconcile so all burn GitHub reports that
CTC hasn't otherwise tracked this cycle books as one BYPASS event (self-sourced,
never headroom-checked — the spend already happened upstream).

Usage:
  python -m tools.repair_baseline --giver <user-id-or-gitlab-login> [--giver ...]
  python -m tools.repair_baseline --all
  python -m tools.repair_baseline --giver alice --dry-run
  python -m tools.repair_baseline --giver alice --entitlement 4000 --remaining 1400

Exit code: 0 on success (or dry-run), non-zero on config/usage error or failure.

OPERATIONAL NOTES:
  * DESTRUCTIVE re-attribution. This books ALL burn GitHub reports that CTC has
    not otherwise tracked this cycle to the giver as their OWN bypass usage. Run
    --dry-run first and eyeball the drift before committing.
  * Safe to run with the proxy and control plane up: every write goes through the
    shared DB open helper (WAL + busy_timeout) and one BEGIN IMMEDIATE, and the
    reconcile itself is BEGIN IMMEDIATE-guarded and idempotent (a second run books
    0). A concurrent proxy debit that lands between the re-anchor and the reconcile
    is simply counted as tracked and excluded — never double-booked.
  * The control-plane LiveQuotaCache has a 60s TTL, so a giver's profile reflects
    the repair within a minute automatically, or instantly via the profile's
    Refresh button (which bypasses the cache).
  * Env: CTC_DB_PATH and CTC_SECRET_KEY are always required. GHE_API_BASE is
    required unless you pass the offline --entitlement/--remaining override (single
    --giver only), which skips the live /copilot_internal/user fetch entirely.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
from urllib.parse import urlparse

from ctc.accounting.wiring import build_live_engine
from ctc.auth.crypto import derive_key, validate_secret
from ctc.auth.registry import AuthRegistry
from ctc.domain.config import NANO_PER_AIU
from ctc.store.auth_store import AuthStore
from ctc.store.db import connect, init_db


class RepairError(Exception):
    """Raised when a giver cannot be repaired (no PAT, unusable live quota)."""


def repair_giver(engine, registry, fetch_user, giver_id, now,
                 entitlement=None, remaining=None, dry_run=False) -> dict:
    """Re-anchor one giver's burn_baseline to 0 for the current cycle and book the
    resulting drift as a single immediate BYPASS event.

    Returns {"giver_id", "cycle_id", "old_baseline", "drift_booked_nano"}. In
    dry_run mode nothing is written and drift_booked_nano is the amount that WOULD
    be booked. `entitlement`/`remaining` (AIU ints), when BOTH supplied, are used
    directly and `fetch_user` is never called; otherwise the giver's decrypted PAT
    drives a live /copilot_internal/user fetch.
    """
    cycle = engine.ensure_active_cycle(now)

    if entitlement is not None and remaining is not None:
        ent, rem = int(entitlement), int(remaining)
    else:
        pat = registry.pat_for(giver_id)
        if not pat:
            raise RepairError(f"no stored PAT for giver {giver_id!r}; cannot fetch live quota")
        body = fetch_user(pat)
        pi = (body.get("quota_snapshots") or {}).get("premium_interactions") or {}
        ent, rem = pi.get("entitlement"), pi.get("remaining")
        if ent is None or rem is None:
            raise RepairError(
                f"live quota for giver {giver_id!r} missing entitlement/remaining")
        ent, rem = int(ent), int(rem)

    gc = engine.store.get_giver_cycle(cycle.id, giver_id)
    old_baseline = gc.burn_baseline if gc else None

    github_burn = (ent - rem) * NANO_PER_AIU
    tracked = engine._tracked_burn(cycle.id, giver_id)
    would_book = max(0, github_burn - tracked)

    if dry_run:
        return {"giver_id": giver_id, "cycle_id": cycle.id,
                "old_baseline": old_baseline, "drift_booked_nano": would_book}

    # Re-anchor + clear any pending observation in one short transaction, so the
    # immediate reconcile below measures drift against a zero baseline.
    engine.conn.execute("BEGIN IMMEDIATE")
    try:
        engine.store.set_burn_baseline(cycle.id, giver_id, 0)
        engine.store.set_pending_drift(cycle.id, giver_id, None, None)
        engine.conn.execute("COMMIT")
    except BaseException:
        engine.conn.execute("ROLLBACK")
        raise

    event = engine.reconcile_giver(
        cycle.id, giver_id, {"entitlement": ent, "remaining": rem},
        ts=now, immediate=True)
    return {"giver_id": giver_id, "cycle_id": cycle.id,
            "old_baseline": old_baseline,
            "drift_booked_nano": event.credits if event else 0}


def _fetch_user_factory(api_base: str):
    """Synchronous /copilot_internal/user fetch (this is a plain CLI, not async).

    Mirrors the control plane's http_get_user headers so GHE returns the same
    quota_snapshots shape. Raises on non-200 so a dead PAT fails the giver loudly.
    """
    u = urlparse(api_base)
    host = u.hostname
    port = u.port or (443 if u.scheme == "https" else 80)
    use_tls = u.scheme == "https"

    def fetch_user(pat: str) -> dict:
        conn = (http.client.HTTPSConnection if use_tls
                else http.client.HTTPConnection)(host, port, timeout=30)
        headers = {"authorization": f"Bearer {pat}",
                   "editor-version": "copilot/1.0.63",
                   "copilot-integration-id": "copilot-developer-cli"}
        try:
            conn.request("GET", "/copilot_internal/user", headers=headers)
            r = conn.getresponse()
            raw = r.read()
            if r.status != 200:
                raise RepairError(f"/copilot_internal/user -> {r.status}")
            return json.loads(raw)
        finally:
            conn.close()

    return fetch_user


def _resolve_giver(store: AuthStore, token: str) -> str:
    """Map a --giver argument (user id OR GitLab login) to a user id."""
    if store.get_user_by_id(token) is not None:
        return token
    user = store.get_user_by_login(token)
    if user is not None:
        return user["id"]
    raise RepairError(f"no user matches {token!r} (tried id and login)")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="repair_baseline")
    ap.add_argument("--giver", action="append", default=[],
                    help="user id or GitLab login (repeatable)")
    ap.add_argument("--all", action="store_true", help="repair every connected giver")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--yes", action="store_true", help="skip the interactive confirm")
    ap.add_argument("--entitlement", type=int, help="offline AIU entitlement override")
    ap.add_argument("--remaining", type=int, help="offline AIU remaining override")
    args = ap.parse_args(argv)

    if args.all and args.giver:
        print("repair_baseline: --all and --giver are mutually exclusive", file=sys.stderr)
        return 2
    if not args.all and not args.giver:
        print("repair_baseline: pass --all or at least one --giver", file=sys.stderr)
        return 2

    offline = args.entitlement is not None and args.remaining is not None
    if (args.entitlement is None) != (args.remaining is None):
        print("repair_baseline: --entitlement and --remaining must be given together",
              file=sys.stderr)
        return 2
    if offline and (args.all or len(args.giver) != 1):
        print("repair_baseline: --entitlement/--remaining require exactly one --giver",
              file=sys.stderr)
        return 2

    db_path = os.environ.get("CTC_DB_PATH")
    secret = os.environ.get("CTC_SECRET_KEY")
    if not db_path or not secret:
        print("repair_baseline: CTC_DB_PATH and CTC_SECRET_KEY are required", file=sys.stderr)
        return 2
    try:
        validate_secret(secret)
    except Exception as e:
        print(f"repair_baseline: {e}", file=sys.stderr)
        return 2

    if offline:
        fetch_user = None
    else:
        api_base = os.environ.get("GHE_API_BASE")
        if not api_base:
            print("repair_baseline: GHE_API_BASE is required for the live fetch "
                  "(or pass --entitlement/--remaining)", file=sys.stderr)
            return 2
        fetch_user = _fetch_user_factory(api_base.rstrip("/"))

    conn = connect(db_path)
    init_db(conn)
    store = AuthStore(conn)
    engine = build_live_engine(conn)
    registry = AuthRegistry(store, derive_key(secret))
    now = int(time.time())

    try:
        if args.all:
            giver_ids = list(registry.list_givers())
        else:
            giver_ids = [_resolve_giver(store, g) for g in args.giver]
    except RepairError as e:
        print(f"repair_baseline: {e}", file=sys.stderr)
        return 2

    if not giver_ids:
        print("repair_baseline: no givers to repair")
        return 0

    if not args.dry_run and not args.yes:
        print("=" * 70)
        print("WARNING: this attributes ALL burn GitHub reports that CTC has not")
        print("tracked this cycle to each giver as their OWN bypass usage, and")
        print("re-anchors their burn baseline to 0. This is a one-time repair.")
        print("=" * 70)
        print(f"Givers: {', '.join(giver_ids)}")
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("aborted.")
            return 1

    failures = 0
    for gid in giver_ids:
        try:
            r = repair_giver(engine, registry, fetch_user, gid, now,
                             entitlement=args.entitlement, remaining=args.remaining,
                             dry_run=args.dry_run)
        except RepairError as e:
            print(f"  {gid}: SKIP — {e}", file=sys.stderr)
            failures += 1
            continue
        old = r["old_baseline"]
        old_str = "None" if old is None else f"{old} nano ({old / NANO_PER_AIU:.0f} AIU)"
        booked = r["drift_booked_nano"]
        verb = "would book" if args.dry_run else "booked"
        print(f"  {gid}: cycle={r['cycle_id']} old_baseline={old_str} "
              f"{verb} {booked} nano ({booked / NANO_PER_AIU:.0f} AIU) bypass")

    if failures:
        print(f"repair_baseline: {failures} giver(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
