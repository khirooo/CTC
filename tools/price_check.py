"""Compare GitHub Copilot's CURRENT per-model token prices against the
baseline captured in tests/fixtures/metering/exchanges.ndjson (2026-06-20).

Answers one question: did Copilot raise prices since we captured the fixture?

Usage:
    PAT=github_pat_xxx python tools/price_check.py
    # optional: GHE_DOMAIN=example.ghe.com (defaults from env or the fixture host)

No third-party deps (urllib only). The PAT is only sent to
copilot-api.<GHE_DOMAIN>/models — a non-billable, read-only endpoint.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/metering/exchanges.ndjson"

PRICE_KEYS = ("input_price", "output_price", "cache_price", "cache_write_price")


def _parse_concatenated_json(text: str) -> list[dict]:
    """The fixture is concatenated JSON docs (bodies contain raw newlines),
    not strict NDJSON — walk it with raw_decode."""
    dec = json.JSONDecoder(strict=False)
    out, i = [], 0
    while i < len(text):
        while i < len(text) and text[i] in " \r\n\t":
            i += 1
        if i >= len(text):
            break
        obj, i = dec.raw_decode(text, i)
        out.append(obj)
    return out


def price_table(models_body: dict) -> dict[str, dict]:
    """model id -> {tier: {price_key: value}} for models with real billing."""
    table = {}
    for m in models_body.get("data", []):
        tp = (m.get("billing") or {}).get("token_prices")
        if not tp:
            continue
        tiers = {}
        for tier in ("default", "long_context"):
            if isinstance(tp.get(tier), dict):
                tiers[tier] = {k: tp[tier].get(k, 0) for k in PRICE_KEYS}
        if any(any(v for v in t.values()) for t in tiers.values()):
            table[m["id"]] = tiers
    return table


def baseline_table() -> tuple[dict[str, dict], str]:
    exchanges = _parse_concatenated_json(FIXTURE.read_text())
    for ex in exchanges:
        if (ex.get("path") or "").split("?")[0] != "/models":
            continue
        body = ex.get("body")
        if isinstance(body, str):
            body = json.loads(body)
        table = price_table(body or {})
        if table:
            captured = ex.get("response_headers", {}).get("Date", "unknown date")
            return table, captured
    sys.exit(f"no /models price list found in {FIXTURE}")


def fetch_current(domain: str, pat: str) -> dict[str, dict]:
    req = urllib.request.Request(
        f"https://copilot-api.{domain}/models",
        headers={
            "authorization": f"Bearer {pat}",
            "accept": "application/json",
            "copilot-integration-id": "copilot-developer-cli",
            "editor-version": "copilot/1.0.63",
            "user-agent": "copilot/1.0.63 (darwin v24.16.0) term/vscode",
            "x-github-api-version": "2026-06-01",
            "openai-intent": "conversation-agent",
            "x-interaction-id": str(uuid.uuid4()),
            "x-initiator": "user",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return price_table(json.load(resp))


def main() -> None:
    pat = os.environ.get("PAT") or os.environ.get("REAL_PAT")
    if not pat:
        sys.exit("set PAT=<github_pat> (only used against the read-only /models endpoint)")
    domain = os.environ.get("GHE_DOMAIN", "example.ghe.com")

    old, captured = baseline_table()
    new = fetch_current(domain, pat)
    print(f"baseline: {FIXTURE.name} (captured {captured})")
    print(f"current:  https://copilot-api.{domain}/models\n")

    changed = 0
    for mid in sorted(old.keys() | new.keys()):
        if mid not in new:
            print(f"[gone]    {mid} (no longer listed / no billing block)")
            continue
        if mid not in old:
            print(f"[new]     {mid}: {json.dumps(new[mid])}")
            continue
        diffs = []
        for tier in old[mid].keys() | new[mid].keys():
            o, n = old[mid].get(tier, {}), new[mid].get(tier, {})
            for k in PRICE_KEYS:
                if o.get(k, 0) != n.get(k, 0):
                    diffs.append(f"{tier}.{k}: {o.get(k, 0)} -> {n.get(k, 0)}")
        if diffs:
            changed += 1
            print(f"[CHANGED] {mid}")
            for d in diffs:
                print(f"            {d}")
    if changed == 0:
        print("== no price changes on models present in both snapshots ==")
    else:
        print(f"\n== {changed} model(s) changed price ==")


if __name__ == "__main__":
    main()
