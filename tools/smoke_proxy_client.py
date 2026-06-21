#!/usr/bin/env python3
"""#1 Task 9 — through-proxy billable check (operator-run).

Sends a billable request THROUGH the running proxy (DB mode) using a per-user
proxy token as the bearer. The proxy resolves the token -> user -> giver PAT,
forwards to the real copilot-api, and debits that giver. Confirms the issued
proxy token actually authenticates a real consumer end-to-end.

Trusts the proxy's MITM cert directly (no macOS keychain needed).

Usage:
  PROXY_TOKEN=github_pat_...    # a FRESH proxy token from /api/proxy-token
  PROXY_PORT=8080 PROXY_CERT=cert.pem PROBE_MODEL=claude-haiku-4.5 \
  python3 tools/smoke_proxy_client.py
"""
import http.client
import json
import os
import ssl
import sys

token = os.environ.get("PROXY_TOKEN", "")
if not token:
    print("ERROR: set PROXY_TOKEN to a fresh /api/proxy-token value", file=sys.stderr)
    sys.exit(2)
port = int(os.environ.get("PROXY_PORT", "8080"))
cert = os.environ.get("PROXY_CERT", "cert.pem")
model = os.environ.get("PROBE_MODEL", "claude-haiku-4.5")

ctx = ssl.create_default_context(cafile=cert)
conn = http.client.HTTPSConnection("localhost", port, context=ctx, timeout=60)
conn.set_tunnel("copilot-api.example.ghe.com", 443)
payload = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": "Reply with the single word: hi"}],
    "max_tokens": 16,
    "stream": False,
}).encode()
try:
    conn.request("POST", "/chat/completions", body=payload, headers={
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "editor-version": "copilot/1.0.63",
        "copilot-integration-id": "copilot-developer-cli",
        "x-initiator": "user",
        "content-length": str(len(payload)),
    })
    r = conn.getresponse()
    body = r.read()
    print(f"STATUS {r.status}")
    if r.status == 402:
        print(">> 402 Payment Required — no eligible credit for this user (or token revoked).")
    try:
        d = json.loads(body)
        print("MODEL", d.get("model"))
        print("total_nano_aiu", d.get("copilot_usage", {}).get("total_nano_aiu"))
    except Exception:
        print("BODY", body[:300].decode("utf-8", "replace"))
    print("\n>> Now check the accounting DB: a consumption_event for YOUR user_id should")
    print("   exist, sourced from your giver PAT (own bucket). Query consumption_events.")
finally:
    conn.close()
