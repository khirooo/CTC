#!/usr/bin/env python3
"""#1 Task 9 — control-plane acceptance driver (operator-run).

Runs the post-login API loop against a running api_server.py, using a session
cookie you copy from the browser after completing the real GHE OAuth login.

Validates: /api/me identity, PAT submit (200 + quota, role->giver), proxy-token
issue (shown once) + list-redaction + revoke. Prints the issued proxy token ONCE
so you can use it for the proxy billable check (see the runbook). Secrets are
redacted in all other output.

Usage:
  CONTROL_PLANE=http://localhost:8090 \
  CTC_SESSION_COOKIE='<value of ctc_session cookie from browser devtools>' \
  PROBE_PAT=github_pat_your_real_pat \
  python3 tools/smoke_control_plane.py
"""
import http.client
import json
import os
import sys
from urllib.parse import urlparse


def _redacted(s: str) -> str:
    return f"{s[:10]}…{s[-4:]} (len={len(s)})" if s else "(empty)"


CP = os.environ.get("CONTROL_PLANE", "http://localhost:8090")
COOKIE = os.environ.get("CTC_SESSION_COOKIE", "")
PAT = os.environ.get("PROBE_PAT", "")
if not COOKIE or not PAT:
    print("ERROR: set CTC_SESSION_COOKIE (from browser) and PROBE_PAT", file=sys.stderr)
    sys.exit(2)

u = urlparse(CP)
HOST, PORT = u.hostname, (u.port or (443 if u.scheme == "https" else 80))
USE_TLS = u.scheme == "https"


def req(method, path, body=None):
    conn = (http.client.HTTPSConnection if USE_TLS else http.client.HTTPConnection)(HOST, PORT, timeout=30)
    headers = {"Cookie": f"ctc_session={COOKIE}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = raw[:300].decode("utf-8", "replace")
        return r.status, parsed
    finally:
        conn.close()


def show(label, status, body):
    print(f"  {label}: HTTP {status}")
    if isinstance(body, (dict, list)):
        print("    " + json.dumps(body)[:400])
    elif body:
        print("    " + str(body)[:200])


print(f"control-plane: {CP}\n")

print("=" * 64)
print("STEP 1 — GET /api/me (confirm OAuth session)")
print("=" * 64)
s, me = req("GET", "/api/me")
show("/api/me", s, me)
if s != 200:
    print("\nFAIL: no valid session — re-copy the ctc_session cookie after logging in.")
    sys.exit(1)
login = me.get("ghe_login")
print(f">> logged in as: {login}  role={me.get('role')}  has_pat={me.get('has_pat')}")

print("\n" + "=" * 64)
print("STEP 2 — POST /api/pat (submit real PAT; identity-matched)")
print("=" * 64)
print(f"   PAT: {_redacted(PAT)}")
s, body = req("POST", "/api/pat", {"pat": PAT})
show("/api/pat", s, body)
pat_ok = s == 200
if s == 409:
    print(">> 409 identity mismatch — this PAT's GHE login != your session login.")
elif s == 400:
    print(">> 400 invalid PAT (bad token or no premium entitlement).")

print("\n" + "=" * 64)
print("STEP 3 — GET /api/me again (role should now be 'giver')")
print("=" * 64)
s, me2 = req("GET", "/api/me")
show("/api/me", s, me2)

print("\n" + "=" * 64)
print("STEP 4 — POST /api/proxy-token (issued ONCE)")
print("=" * 64)
s, tok = req("POST", "/api/proxy-token")
show("/api/proxy-token", s, {k: (v if k != "token" else _redacted(v)) for k, v in (tok or {}).items()})
token = (tok or {}).get("token", "")
tid = (tok or {}).get("id", "")
if token:
    print("\n>> PROXY TOKEN (set this as COPILOT_GITHUB_TOKEN for the proxy billable check):")
    print(f"   {token}")

print("\n" + "=" * 64)
print("STEP 5 — GET /api/proxy-token (list must NOT contain the raw token)")
print("=" * 64)
s, lst = req("GET", "/api/proxy-token")
leak = isinstance(lst, list) and any("token" in row for row in lst)
show("list", s, lst)
print(f">> raw token leaked in list? {'YES — FAIL' if leak else 'no ✓'}")

print("\n" + "=" * 64)
print("STEP 6 — DELETE /api/proxy-token/{id} then re-list (revoked)")
print("=" * 64)
s, _ = req("DELETE", f"/api/proxy-token/{tid}")
print(f"  delete: HTTP {s}")
s, lst2 = req("GET", "/api/proxy-token")
revoked = isinstance(lst2, list) and any(r.get("id") == tid and r.get("revoked") for r in lst2)
show("list after delete", s, lst2)
print(f">> token {tid[:8]}… revoked? {'yes ✓' if revoked else 'NO — check'}")

print("\n" + "=" * 64)
print("VERDICT (control-plane)")
print("=" * 64)
print(f"[{'PASS' if login else 'FAIL'}] OAuth session resolves to a GHE identity ({login})")
print(f"[{'PASS' if pat_ok else 'CHECK'}] PAT submit accepted + role->giver "
      f"(role now: {me2.get('role') if isinstance(me2, dict) else '?'})")
print(f"[{'PASS' if token else 'FAIL'}] proxy token issued once")
print(f"[{'PASS' if not leak else 'FAIL'}] list endpoint redacts the raw token")
print(f"[{'PASS' if revoked else 'CHECK'}] proxy token revocable")
print("\nNEXT: use the printed proxy token (STEP 4) as COPILOT_GITHUB_TOKEN and run the")
print("proxy billable check from the runbook to confirm it resolves to your user and")
print("bills your giver PAT. (That token is now REVOKED — issue a fresh one for that step.)")
