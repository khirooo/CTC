#!/usr/bin/env python3
"""Seed a throwaway local DB for the VS Code IDE operator test.

Creates a fresh SQLite DB with one giver (your real PAT) who is also the
consumer, an active cycle with headroom, and mints a CTC proxy token. Prints the
token — use it for `ctc login` (or the shim's CTC_TOKEN). No web/OAuth needed.

Nothing here touches prod: it writes only to the DB path you pass.

Usage:
  REAL_PAT=github_pat_...withCredits \
  CTC_DB_PATH=/tmp/ctc-ide-test.db \
  CTC_SECRET_KEY=local-ide-test-key-16chars \
  python3 tools/seed_local_ide_test.py
"""
import os
import sqlite3
import sys

# Allow `python3 tools/seed_local_ide_test.py` (sys.path[0] would otherwise be
# tools/, hiding the top-level ctc package).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctc.auth.crypto import derive_key
from ctc.auth.registry import AuthRegistry
from ctc.accounting.engine import AccountingEngine
from ctc.store.auth_store import AuthStore
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect, init_db

GIVER = "local-ide-tester"
CYCLE = "local-ide-cycle"


def main() -> None:
    pat = os.environ.get("REAL_PAT", "")
    db = os.environ.get("CTC_DB_PATH", "")
    secret = os.environ.get("CTC_SECRET_KEY", "")
    if not pat or not db or not secret:
        print("ERROR: set REAL_PAT, CTC_DB_PATH, CTC_SECRET_KEY", file=sys.stderr)
        sys.exit(2)
    if len(secret) < 16:
        print("ERROR: CTC_SECRET_KEY must be >= 16 chars", file=sys.stderr)
        sys.exit(2)

    conn = connect(db)
    init_db(conn)
    store = AuthStore(conn)
    eng = AccountingEngine(AccountingStore(conn))

    # Far-future cycle so ensure_active_cycle() returns it without rolling over;
    # generous OWN quota so routing picks the PAT (real billing still happens on
    # GHE against the PAT — this quota is CTC's display/gate only).
    try:
        eng.start_cycle(CYCLE, "local-ide", 0, 9_999_999_999)
    except sqlite3.IntegrityError:
        pass  # already seeded on a prior run; reuse it and mint a fresh token
    eng.set_quota(CYCLE, GIVER, 100_000_000_000)
    store.upsert_user(GIVER, "local-ide-tester", "Local IDE Tester", "giver", 1)

    reg = AuthRegistry(store, derive_key(secret))
    _, token, fp = reg.issue_proxy_token(GIVER, now=1)
    reg.store_pat(GIVER, pat, now=1)

    print("\n✓ Seeded throwaway DB:", db)
    print("  giver/consumer:", GIVER, "(OWN bucket, quota headroom)")
    print("  PAT fingerprint: …" + pat[-4:])
    print("\nYour CTC token (use for `ctc login` / CTC_TOKEN):\n")
    print("  " + token + "\n")


if __name__ == "__main__":
    main()
