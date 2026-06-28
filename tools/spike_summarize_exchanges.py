"""Summarize a CTC capture (exchanges.ndjson) for the VS Code extension spike.

Read-only and redaction-safe: emits host/path/status classifications only, never
raw header or body content. See
docs/superpowers/specs/2026-06-27-vscode-extension-spike-design.md.
"""
from __future__ import annotations

import json
import sys
from typing import Iterable

from ctc import contract

_TOKEN_EXCHANGE_MARK = "/copilot_internal/v2/token"
_METERING_MARK = "total_nano_aiu"


def _slim(rec: dict) -> dict:
    return {"host": rec.get("host"), "path": rec.get("path"), "status": rec.get("status")}


def summarize(records: Iterable[dict]) -> dict:
    hosts: dict[str, dict] = {}
    statuses: dict[str, set] = {}
    token_exchange: list[dict] = []
    billable: list[dict] = []
    metering_hits: list[dict] = []

    for rec in records:
        host = rec.get("host", "")
        path = rec.get("path", "")
        method = (rec.get("method") or "").upper()
        status = rec.get("status")
        body = rec.get("body") or ""

        h = hosts.setdefault(host, {"count": 0, "paths": set()})
        h["count"] += 1
        h["paths"].add(path)
        statuses.setdefault(host, set()).add(status)

        if _TOKEN_EXCHANGE_MARK in path:
            token_exchange.append(_slim(rec))
        if method == contract.BILLABLE_METHOD and path in contract.BILLABLE_PATHS:
            billable.append(_slim(rec))
        if _METERING_MARK in body:
            metering_hits.append(_slim(rec))

    return {
        "hosts": {k: {"count": v["count"], "paths": sorted(v["paths"])} for k, v in hosts.items()},
        "token_exchange": token_exchange,
        "billable": billable,
        "metering_hits": metering_hits,
        "statuses": {k: sorted(s for s in v if s is not None) for k, v in statuses.items()},
    }


def _load(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tools.spike_summarize_exchanges <exchanges.ndjson>", file=sys.stderr)
        return 2
    print(json.dumps(summarize(_load(argv[1])), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
