"""CTC contract canary — drive a real paid Copilot completion through an
isolated proxy and assert the contract still holds. Run daily by cron.

Usage:
  python -m tools.canary [--if-version-changed] [--status PATH] [--model NAME]

Exit code: 0 on pass (or skipped), non-zero on any contract breach.

OPERATIONAL NOTES (live run):
  * Requires macOS `security add-trusted-cert` (the trust layer under test).
    The cron user needs a scoped sudoers rule for that one command.
  * Uses a DEDICATED canary PAT (env CANARY_PAT) — never the production PAT.
  * Requires a PAID model (env CANARY_MODEL); a free model costs 0, which is
    indistinguishable from the silent break this canary exists to catch.
  * All temp state (cert, accounting DB, capture dir, isolated HOME) is created
    under a tempdir and removed in a `finally`, including untrusting the cert.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from ctc import canary as verdict_mod

DEFAULT_STATUS = os.path.expanduser("~/.local/state/ctc/canary-status.json")


def copilot_version() -> str | None:
    try:
        out = subprocess.run(["copilot", "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text or None


def should_skip(installed: str | None, status_path: str) -> bool:
    if installed is None:
        return False
    try:
        with open(status_path, "r", encoding="utf-8") as fh:
            last = json.load(fh).get("copilot_version")
    except (OSError, ValueError):
        return False
    return last == installed


def _run_live(model: str, status_path: str, version: str | None) -> int:
    """Stand up isolation, drive one paid completion, evaluate, write status.

    This is the live-run skeleton. Each numbered block is an ordered shell/IO
    step; they are intentionally NOT unit-tested (they spend quota and mutate
    the keychain). The pure verdict logic they feed is tested in
    tests/test_canary_verdict.py.
    """
    import tempfile

    pat = os.environ.get("CANARY_PAT")
    if not pat:
        print("canary: CANARY_PAT not set", file=sys.stderr)
        return 2

    workdir = tempfile.mkdtemp(prefix="ctc-canary-")
    cert = os.path.join(workdir, "cert.pem")
    key = os.path.join(workdir, "key.pem")
    capture_dir = os.path.join(workdir, "capture")
    db_path = os.path.join(workdir, "canary.db")
    os.makedirs(capture_dir, exist_ok=True)
    proc = None
    trusted = False
    try:
        # 1. Generate a throwaway cert whose SANs cover EVERY expected MITM host.
        from ctc import contract
        sans = ",".join(f"DNS:{h}" for h in sorted(contract.EXPECTED_MITM_HOSTS)) + ",IP:127.0.0.1"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key, "-out", cert,
            "-days", "1", "-nodes", "-subj", "/CN=ctc-canary-ca", "-addext", f"subjectAltName={sans}",
        ], check=True, capture_output=True)

        # 2. Trust it in the System keychain (exercises the CRITICAL trust layer).
        subprocess.run([
            "sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot",
            "-k", "/Library/Keychains/System.keychain", cert,
        ], check=True)
        trusted = True

        # 3. Seed the temp accounting DB with one active cycle + a canary giver,
        #    then start a dedicated proxy on an ephemeral port with capture on.
        #    (Build CTC_IDENTITY_JSON/CTC_PATS_JSON for the canary token + PAT;
        #    set CTC_CAPTURE_DIR=capture_dir, CTC_DB_PATH=db_path, REAL_PAT=pat,
        #    CERT_FILE=cert, KEY_FILE=key, PORT=<ephemeral>.)
        #    proc = subprocess.Popen([... "python3", "proxy.py" ...], env=...)
        #    Wait until the port accepts connections.

        # 4. Drive ONE non-interactive paid completion through the real copilot
        #    binary using the ctc-launcher isolated-env recipe (isolated HOME,
        #    GH_HOST=example.ghe.com, COPILOT_GITHUB_TOKEN=<canary fake token>,
        #    HTTPS_PROXY=http://localhost:<port>, NODE_EXTRA_CA_CERTS=cert,
        #    --model <paid model>). NOTE: reliable non-interactive invocation of
        #    `copilot` must be validated against the installed CLI version (the
        #    launcher's cmd_launch is still a stub) — see plan risk note.

        # 5. Evaluate: load the recorded exchanges + read the debit from the DB.
        exchanges = verdict_mod.load_exchanges(os.path.join(capture_dir, "exchanges.ndjson"))
        debited = _read_canary_debit(db_path)  # sum of debits this run
        v = verdict_mod.evaluate(exchanges, debited)

        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        verdict_mod.write_status(status_path, v, ran_at=_utc_now(), copilot_version=version)
        if v.verdict != "pass":
            for f in v.failures:
                print(f"canary FAIL: {f['assertion']}: {f['detail']}", file=sys.stderr)
            return 1
        print(f"canary PASS: extracted_nano_aiu={v.extracted_nano_aiu}")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
        if trusted:
            subprocess.run(["sudo", "security", "delete-certificate", "-c", "ctc-canary-ca",
                            "/Library/Keychains/System.keychain"], check=False)
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


def _read_canary_debit(db_path: str) -> int:
    """Sum nano-AIU debited in the temp DB this run.

    Queries consumption_events.credits (integer nano-AIU); every row is a
    debit — there is no 'kind' column. Returns 0 if the DB has no rows.

    CORRECTION vs. brief: the brief showed `ledger_entries` with `kind='debit'`
    — that table does not exist. The real schema (ctc/store/db.py) uses
    `consumption_events` with a `credits` INTEGER column.
    """
    from ctc.store.db import connect
    conn = connect(db_path)
    row = conn.execute("SELECT COALESCE(SUM(credits), 0) FROM consumption_events").fetchone()
    return int(row[0]) if row else 0


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="canary")
    ap.add_argument("--if-version-changed", action="store_true")
    ap.add_argument("--status", default=DEFAULT_STATUS)
    ap.add_argument("--model", default=os.environ.get("CANARY_MODEL", ""))
    args = ap.parse_args(argv)

    version = copilot_version()
    if args.if_version_changed and should_skip(version, args.status):
        print(f"canary: copilot version unchanged ({version}); skipping")
        return 0
    if not args.model:
        print("canary: no paid model set (--model or CANARY_MODEL)", file=sys.stderr)
        return 2
    return _run_live(args.model, args.status, version)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
