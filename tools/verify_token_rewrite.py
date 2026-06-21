#!/usr/bin/env python3
"""#3 Task 0 verification probe — run by the OPERATOR with a real PAT.

Proves the two load-bearing assumptions of the routing/attribution design
(docs/reference/routing-attribution.md §6):

  GOAL 1  Discover the /copilot_internal/v2/token exchange shape and the
          copilot token's format + expiry, so the broker's lazy-refresh
          (ctc/broker/) can be built against real semantics.

  GOAL 2  Prove a copilot token MINTED FROM AN ARBITRARY PAT authorizes a
          billable /chat/completions call AND bills THAT PAT's quota. This is
          exactly what the proxy does when it rewrites Authorization to a
          selected giver's token per request. If this works standalone, it
          works through the proxy (upstream sees identical bytes).

This talks DIRECTLY to real GHE upstream — no proxy, no CLI involved. It reads
premium_interactions quota before and after the billable call to show the bill
landing on the minted token's PAT.

SAFETY: the copilot token and PAT are only ever printed as a short redacted
preview; full secrets are never written to stdout or disk.

Usage:
  REAL_GHE_HOST=api.example.ghe.com \\
  COPILOT_API_HOST=copilot-api.example.ghe.com \\
  PROBE_PAT=github_pat_xxxxx \\
  [PROBE_MODEL=claude-haiku-4.5] \\
  [UPSTREAM_CA_BUNDLE=/abs/path/corp-ca.pem] \\
  [UPSTREAM_INSECURE=1] \\
  python tools/verify_token_rewrite.py

Notes:
  - PROBE_MODEL must be a *premium* model so the call has non-zero AIU and the
    quota visibly moves. Default claude-haiku-4.5 (cheap premium). A free model
    like gpt-4o-mini bills 0 and would prove nothing about attribution.
  - One PAT is enough: the script mints a token from a PAT of *its* choosing,
    independent of any session, which is precisely the "different giver" case.
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import sys

EDITOR_VERSION = "copilot/1.0.63"
INTEGRATION_ID = "copilot-developer-cli"


def _redacted(secret: str) -> str:
    if not secret:
        return "(empty)"
    return f"{secret[:8]}…{secret[-4:]} (len={len(secret)})"


def _ssl_context() -> ssl.SSLContext:
    if os.environ.get("UPSTREAM_INSECURE") == "1":
        print("!! UPSTREAM_INSECURE=1 — TLS verification DISABLED", file=sys.stderr)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    bundle = os.environ.get("UPSTREAM_CA_BUNDLE")
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def http_request(host, method, path, *, headers, body=None, ctx):
    conn = http.client.HTTPSConnection(host, 443, context=ctx, timeout=60)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, dict(resp.getheaders()), raw
    finally:
        conn.close()


def parse_premium(user_body: bytes):
    try:
        d = json.loads(user_body)
        pi = d.get("quota_snapshots", {}).get("premium_interactions", {})
        return {
            "entitlement": pi.get("entitlement"),
            "remaining": pi.get("remaining"),
            "quota_remaining": pi.get("quota_remaining"),
            "percent_remaining": pi.get("percent_remaining"),
        }, d.get("login")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}, None


def main() -> int:
    ghe = os.environ.get("REAL_GHE_HOST", "api.example.ghe.com")
    capi = os.environ.get("COPILOT_API_HOST", "copilot-api.example.ghe.com")
    pat = os.environ.get("PROBE_PAT", "")
    model = os.environ.get("PROBE_MODEL", "claude-haiku-4.5")
    if not pat:
        print("ERROR: set PROBE_PAT to a real PAT", file=sys.stderr)
        return 2
    ctx = _ssl_context()
    print(f"PAT: {_redacted(pat)}  GHE: {ghe}  copilot-api: {capi}  model: {model}\n")

    common = {
        "authorization": f"Bearer {pat}",
        "editor-version": EDITOR_VERSION,
        "copilot-integration-id": INTEGRATION_ID,
        "user-agent": "GitHubCopilotChat/" + EDITOR_VERSION,
    }

    # ── The real model: the PAT is the bearer for copilot-api directly ─────────
    # proxy.py swaps fake->REAL_PAT on copilot-api.* (SWAP_HOSTS), so billable
    # calls authenticate with the PAT itself — there is NO /v2/token exchange in
    # the no-login PAT flow. Per-request giver routing = swap to a different
    # giver's PAT. So the linchpin to verify is: does copilot-api accept a PAT as
    # bearer and bill THAT PAT? We use the PAT directly below.
    print("=" * 70)
    print("STEP 1 — credential model: PAT used directly as copilot-api bearer")
    print("=" * 70)
    print("  (no /v2/token exchange — matches proxy.py SWAP_HOSTS swap)")
    copilot_token = pat  # the PAT IS the bearer
    print("\n>> bearer used for copilot-api:", _redacted(copilot_token))

    # ── quota BEFORE ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("STEP 2 — GET /copilot_internal/user  (premium_interactions BEFORE)")
    print("=" * 70)
    s, _, ubody = http_request(ghe, "GET", "/copilot_internal/user",
                               headers=common, ctx=ctx)
    before, login = parse_premium(ubody)
    print(f"status: {s}  login: {login}")
    print("premium_interactions BEFORE:", json.dumps(before))

    # ── GOAL 2: billable call with the MINTED token ───────────────────────────
    print("\n" + "=" * 70)
    print(f"STEP 3 — POST /chat/completions on {capi}  using the PAT as bearer")
    print("=" * 70)
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: hi"}],
        "max_tokens": 16,
        "stream": False,
    }).encode()
    s, chdrs, cbody = http_request(
        capi, "POST", "/chat/completions",
        headers={
            "authorization": f"Bearer {copilot_token}",
            "content-type": "application/json",
            "editor-version": EDITOR_VERSION,
            "copilot-integration-id": INTEGRATION_ID,
            "x-initiator": "user",
            "user-agent": "GitHubCopilotChat/" + EDITOR_VERSION,
            "content-length": str(len(payload)),
        },
        body=payload, ctx=ctx,
    )
    print(f"status: {s}")
    nano = None
    try:
        cd = json.loads(cbody)
        nano = cd.get("copilot_usage", {}).get("total_nano_aiu")
        print("returned model:", cd.get("model"))
        print("copilot_usage.total_nano_aiu:", nano,
              f"({(nano or 0)/1e9:.4f} AIU)")
    except Exception:  # noqa: BLE001
        print("response body (first 800 bytes):")
        print(cbody[:800].decode("utf-8", "replace"))
    for hk in ("x-quota-snapshot-premium_interactions", "x-request-id"):
        if hk in chdrs:
            print(f"hdr {hk}: {chdrs[hk]}")

    # ── quota AFTER ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("STEP 4 — GET /copilot_internal/user  (premium_interactions AFTER)")
    print("=" * 70)
    s, _, ubody2 = http_request(ghe, "GET", "/copilot_internal/user",
                                headers=common, ctx=ctx)
    after, _ = parse_premium(ubody2)
    print("premium_interactions AFTER: ", json.dumps(after))

    # ── verdict ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    print(f"[{'PASS' if (s == 200 or isinstance(nano, int)) else 'FAIL'}] "
          "GOAL 1: copilot-api accepted the PAT directly as bearer (status "
          f"{s}) — confirms the no-exchange PAT credential model")
    try:
        moved = (before.get("quota_remaining") is not None
                 and after.get("quota_remaining") is not None
                 and after["quota_remaining"] < before["quota_remaining"])
    except Exception:  # noqa: BLE001
        moved = False
    print(f"[{'PASS' if (nano or 0) > 0 else 'WARN'}] "
          f"GOAL 2a: billable call billed non-zero AIU ({(nano or 0)/1e9:.4f})")
    print(f"[{'PASS' if moved else 'WARN'}] "
          "GOAL 2b: this PAT's premium_interactions decreased "
          f"({before.get('quota_remaining')} -> {after.get('quota_remaining')})")
    print("\nNote: the quota snapshot header lags (per the metering contract), so "
          "GOAL 2b may read flat even when the call billed — trust total_nano_aiu "
          "(2a) as the authoritative signal; re-run /user a few seconds later to "
          "see the decrement settle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
