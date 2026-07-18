#!/usr/bin/env python3
"""Verify the local VS Code IDE operator test billed correctly.

Reads the throwaway DB seeded by seed_local_ide_test.py and prints the tester's
remaining OWN quota (starts at 100000000000 nano-AIU) — after a real chat it
drops by the turn's total_nano_aiu. Also scans the capture for the charge.

Usage:
  CTC_DB_PATH=/tmp/ctc-ide-test.db python3 tools/verify_local_ide_test.py \
      [/tmp/ctc-ide-cap/exchanges.ndjson]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctc.accounting.engine import AccountingEngine
from ctc.store.accounting_store import AccountingStore
from ctc.store.db import connect

GIVER = "local-ide-tester"
CYCLE = "local-ide-cycle"
SEED_QUOTA = 100_000_000_000


def main() -> None:
    db = os.environ.get("CTC_DB_PATH", "")
    if not db:
        print("ERROR: set CTC_DB_PATH", file=sys.stderr)
        sys.exit(2)
    eng = AccountingEngine(AccountingStore(connect(db)))
    remaining = eng.personal_remaining(CYCLE, GIVER)
    spent = SEED_QUOTA - remaining
    print(f"tester OWN remaining : {remaining:,} nano-AIU")
    print(f"spent this test      : {spent:,} nano-AIU", "  <-- should be > 0 after a chat"
          if spent == 0 else "  <-- a chat was billed ✓")

    cap = sys.argv[1] if len(sys.argv) > 1 else ""
    if cap and os.path.exists(cap):
        hits = [ln for ln in open(cap) if "total_nano_aiu" in ln]
        print(f"\ncapture lines with total_nano_aiu: {len(hits)}")
        for ln in hits[-3:]:
            i = ln.find("total_nano_aiu")
            print("  …" + ln[i:i + 40].split(",")[0])


if __name__ == "__main__":
    main()
