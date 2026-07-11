# CTC Full Audit — 2026-07-10

Scope: `proxy.py`, `api_server.py`, `ctc/`, `web/src`, docs. Six parallel audits
(security, backend correctness, routes/API, performance, docs accuracy, frontend).
Findings below are deduplicated across audits and re-ranked into a single severity
scale. Line references are against HEAD at audit time.

Legend: **P0** ship-blocker / data-corrupting / exploitable · **P1** serious ·
**P2** should-fix · **P3** minor/cosmetic.

---

## P0 — fix first

### P0-1 · Cycle-rollover time bomb (reproduced) — `ctc/accounting/engine.py:97,115,151`
`_month_cycle` sets `ends_at` to the month's last second *inclusive* (23:59:59), but
liveness is `now < ends_at`. A request landing in that single UTC second triggers
`_roll_over`, where `_month_cycle(now)` still resolves to the *same* month
(`new.id == live.id`), the `existing.id != live.id` reactivation guard is false, and
the cycle is archived with **no active successor**. Consequences, verified:
1. A second request in that same second hits the `cur is None` gap path →
   `start_cycle` bare-INSERTs the existing id → unhandled `IntegrityError`/500.
2. The next month's cycle opens via the gap path, which **does not seed
   `giver_cycles`** → every giver has `personal_remaining == 0` → every billable
   request is 402-blocked until each giver re-submits their PAT.
Fix: make `ends_at` exclusive (first second of next month); in `_roll_over`
reactivate when `new.id == live.id`; route the gap path through the same
insert-or-reactivate logic **and seed `giver_cycles` from `giver_pats`** (shared helper).
Same root cause as the fresh-DB concurrent-first-request `IntegrityError`
(`engine.py:119` — bare INSERT outside `BEGIN IMMEDIATE`).

### P0-2 · Plain-HTTP proxy path bypasses the open-relay guard (SSRF) — `proxy.py:963-976`
`CTC_RESTRICT_CONNECT`/`connect_allowed()` are checked **only** in the CONNECT branch
(`proxy.py:931`). A non-CONNECT proxy request routes through the `else` branch, reads
the `Host` header, and forwards to `https://{host}{path}` with no allowlist check —
an open forward proxy / SSRF into whatever the proxy host can reach, defeating the
exact hardening `CTC_RESTRICT_CONNECT` exists to provide. In legacy single-PAT mode
an arbitrary `Host: api.<ghe>` also gets the shared `REAL_PAT` swapped in.
Fix: apply the same guard in the plain-HTTP branch, or reject non-CONNECT proxy
requests outright when `RESTRICT_CONNECT` is set (Copilot always uses CONNECT).

---

## P1 — serious

### P1-1 · Client disconnect mid-stream skips the debit → free request + false BYPASS — `proxy.py:829-841,861`
Debit runs only *after* `_relay_response` returns. If the client Ctrl-C's mid-SSE
(routine), `drain()` raises → jumps to the generic `except` → `debit()` never runs,
even though upstream fully burned the giver's quota. The next `reconcile_giver` sweep
then books the missing cost as a **BYPASS on the giver**: consumer got a free request,
giver's ledger shows burn they never did. Fix: on relay failure, best-effort extract
cost from the already-captured body and debit; log a reconciliation marker.

### P1-2 · Reconcile-watermark race double-counts in-flight cost as BYPASS — `engine.py:236-268`, `proxy.py:651`
Debit lands after the response completes, but GitHub `remaining` drops during the
request. Any `reconcile_giver` in that window (another caller's 60s cache expiry, or a
profile view during a long stream) computes drift including the not-yet-debited cost
and books it as BYPASS; A's debit then also lands → cost counted **twice**, permanently
(watermark is add-only). Skews balances/leaderboard/`personal_remaining` low under
normal concurrent use. Fix: track in-flight expected cost per giver, or require drift
to persist across two observations before booking BYPASS.

### P1-3 · Cycle boundary vs GitHub `quota_reset_date` lag double-books at rollover — `engine.py:159-166,250`
`reconcile_giver` sums only the new cycle's `tracked` events but measures
`github_burn = ent - remaining` against GitHub's own reset. If a PAT's reset isn't
exactly the UTC-month boundary (or GitHub's snapshot lags), the first reconcile of the
month re-books the entire previous month's usage as one giant BYPASS. Fix: store a
per-giver burn baseline in `giver_cycles` at seed time and compute drift relative to it.

### P1-4 · Fresh `SSLContext` per connection — blocks the loop and defeats connection pooling — `proxy.py:581,99,510`
`build_upstream_ssl_context()` calls `ssl.create_default_context()` (synchronous CA
parse, ~1-10ms) **on the event loop** per MITM connection and per live-quota fetch.
Worse, aiohttp keys its pool by the `SSLContext` object identity, so a fresh context
per call means **upstream connections are never reused** — every CLI tunnel pays a
full TCP+TLS handshake to GHE. Fix: build one module-level context at startup and
reuse it everywhere. Highest-impact, smallest-diff performance win.

### P1-5 · Client input errors crash to 500 — `api_server.py:69-80,174`, `web_routes.py:55,72,109`, `admin_routes.py:90`
`json_error_middleware` catches only `web.HTTPException`. Malformed JSON
(`JSONDecodeError`), non-object bodies (`AttributeError`/`patch.items()` on a list),
and pydantic `ValidationError` (e.g. `{"amount":"abc"}`) all escape → aiohttp default
500 with a non-JSON body, breaking the frontend `{error,message}` contract and
misclassifying client errors as server errors. Fix: catch `JSONDecodeError` /
`ValidationError` → 400/422 JSON; validate body is a dict.

### P1-6 · `POST /api/pat` 500s on re-submission — `ctc/auth/onboarding.py:35`, `api_server.py:183`
`engine.set_quota` raises `InvalidPledge` when new quota < already-consumed pool spend;
`api_pat` catches only `PatInvalid`. A giver re-submitting after entitlement dropped
→ 500 with no explanation. Fix: catch `InvalidPledge`/`AccountingError` → 409/422.

### P1-7 · `POST /api/requests` has no amount/reason validation — `web_routes.py:53-68`, `serializers.py:43`
`amount_needed <= 0` produces an instantly "fulfilled" request (`rules.py:7` —
`funded(0) >= needed(0)`), polluting the marketplace; `reason`/`target` are unbounded.
Fix: pydantic `Field(gt=0, le=MAX)` on amount, length bounds on strings.

### P1-8 · Upstream session tokens + client proxy tokens leak into proxy logs unredacted — `proxy.py:407,436,618`
Request-header log masks only `authorization`; response bodies go through `_log_block`
with **no redaction** (unlike `capture.py`). `POST /models/session` returns a
`session_token`; these land in the proxy log in cleartext (replayable secrets). Fix:
run response bodies through `capture.redact_text()`; mask the full sensitive-header set.

### P1-9 · Web session-bootstrap has no error path → permanently blank app — `web/src/store/AppContext.tsx:62`, `HttpCtcApi.ts:74`
`getSession()` only handles `!res.ok`; if `fetch` itself throws (control plane down,
VPN blip) the promise rejects, the mount effect has no rejection handler, `session`
stays `undefined` forever, and all guards render `null` → blank white page, no retry.
Fix: `try/catch` in `getSession` returning `null`, or a rejection handler + error UI.

### P1-10 · `X-CTC-User` header breaks every cross-origin API call — `web/src/api/http.ts:19`, `api_server.py:54,67`
The client attaches `X-CTC-User` to every `apiFetch`, but CORS `Allow-Headers` is
`content-type` only. Any cross-origin deployment (documented dev setup :3000→:8090,
or split web/API host) fails preflight on every call — while `getSession` (no header)
still works, so login succeeds and everything else silently dies. Fix: delete the
legacy header (its own comment says it's ignored) or add it to `Allow-Headers`.

### P1-11 · `reconcile_giver` write-transaction per candidate on every billable request — `proxy.py:651`, `engine.py:251`
Each candidate giver gets a `BEGIN IMMEDIATE` (exclusive write lock) + 4 `SUM` scans
per request **even when drift ≤ 0** (the common case), synchronously on the loop,
contending with the control plane on the same DB. Combined with `busy_timeout=5000`
(`db.py:124`, a synchronous C-level sleep), a control-plane write can freeze the entire
proxy — every in-flight SSE stream — for up to 5s. Fix: do the drift read without a
transaction; take the lock only when drift > 0; throttle reconcile per giver per
cache-TTL. Add `PRAGMA synchronous=NORMAL` (safe with WAL) and covering indexes.

### P1-12 · Docs materially wrong on `quota_aiu` + incomplete API contract — `docs/reference/control-plane-api.md`, `docs/guide/04-*`
`control-plane-api.md:136` documents `quota_aiu` as *entitlement*; code returns
*remaining* (`onboarding.py:53`). Guide 04 says a giver's cycle quota = *remaining*;
code sets it to *entitlement* (`onboarding.py:33`, contradicting its own comment).
The API doc also omits `DELETE /api/pat`, `/api/onboarding/complete`, all 11 web
routes, all 5 admin routes; documents a 409 identity-mismatch that can never fire
(`enforce_identity=False`); and has stale response schemas. Fix: regenerate from the
live route table (see the routes audit inventory).

---

## P2 — should fix

**Backend / accounting**
- `pinned_source` bypasses every credit gate for the 30-min pin TTL — a pool consumer
  can burn past allowance and the giver's pledge (debit uses `allow_overshoot=True`).
  Re-check bucket headroom in `pinned_source`. `attribution.py:131`.
- Unlimited PATs (`entitlement == -1`) are rejected at onboarding and dropped at
  rollover, yet `get_profile`/`reconcile_giver` have live `-1` branches — pick one.
  `onboarding.py:26`, `engine.py:160`.
- `any_giver_pat` ignores PAT health → non-billable GHE calls can ride a dead PAT while
  healthy ones exist (same shape as the `/responses` incident). Prefer `health='valid'`.
  `attribution.py:149`, `proxy.py:725`.
- `assemble_request_body` doesn't truncate the CL body to `Content-Length` (pipelining
  corrupts the next request); chunked reader silently truncates on timeout/EOF and
  doesn't consume trailers. `proxy.py:334-376`.
- `DELETE /api/pat` fabricates a `giver_cycles` row for plain consumers, misclassifying
  them as givers in dashboard aggregates. Skip zeroing when `get_giver_cycle` is None.
  `api_server.py:198`.
- Brotli/zstd are load-bearing for *relaying* (Node advertises `br`), not just log
  decoding as CLAUDE.md claims — a br response with `brotli` uninstalled → 502. Pin the
  forwarded `accept-encoding` to decodable codecs, or pass through compressed. `proxy.py:290`.
- Mid-stream upstream failure writes a raw `502` inside the open chunked body,
  corrupting the client stream — abortively close instead. `proxy.py:861`.
- `extract` rejects a float `total_nano_aiu` (bills 0) while `sentinel` accepts floats
  (stays silent) — a float-valued field would silently zero all billing with no alarm.
  Accept floats via `int(val)` in `extract`. `extract.py:15` vs `sentinel.py:32`.

**Security**
- `is_github_ish` uses unbounded `endswith` (`evilgithubcopilot.com` matches
  `githubcopilot.com`) — match on a dot boundary. `contract.py:74`.
- PAT-encryption key is bare `sha256(secret)` with no KDF/salt and no startup entropy
  check; a low-entropy `CTC_SECRET_KEY` is brute-forceable offline against an exfil'd
  DB. Enforce min length; consider scrypt/argon2. `crypto.py:9`.
- `UPSTREAM_INSECURE=1` disables upstream TLS verification, exposing the real PAT to an
  on-path attacker — gate behind a second explicit flag. `proxy.py:222`.

**Routes / API**
- No rate limiting anywhere; `POST /api/pat` is an unauthenticated-PAT validation
  oracle proxied to GHE. Add a per-user/IP token bucket on `/api/pat`, `/auth/login`,
  `/api/proxy-token`.
- Proxy tokens: minted unbounded, never rotated, and the frontend mints a **new** one
  on every Profile/checklist/onboarding view (`ProfileScreen.tsx:62` →
  `POST /api/proxy-token`). Cap active tokens per user; mint only on explicit action.

**Frontend**
- Session goes stale after connect/rotate/revoke PAT — Profile reloads local data but
  never `refresh()`es the session, so the dashboard still gates on old `hasPat`.
  `ProfileScreen.tsx:104`.
- Install one-liner runs `curl -fsSLk` (TLS verify off) — MITM can swap the script.
  Make `-k` conditional / print expected SHA-256. `HttpCtcApi.ts:133`.
- PAT inputs are `type="text"` with no `autocomplete="off"` — the crown-jewel secret is
  shoulder-surfable and browser-storable. Use `type="password"` + toggle. `ProfileScreen`, `OnboardingScreen`.
- Pledge slider commits only on mouse/touch — keyboard changes never persist (data loss
  + a11y). Commit on `onKeyUp`/`onBlur`. `CreditBar.tsx:69`.
- Donate has no double-submit guard → double-click chips in twice (real credit).
  `MarketplaceScreen.tsx:44`.
- Compose form offers expiry options and a default that can exceed the admin-set max →
  guaranteed 422; directed requests target by display *name* (non-unique) not id.
  `ComposeForm.tsx`.

**Performance (background / scale)**
- Report endpoints (`build_dashboard`, `build_leaderboard`, `build_cycle_report`,
  `list_requests`, `build_history`) are N+1-heavy and recomputed per view — fine at
  ≤50 users, will hurt at hundreds. Batch with `GROUP BY`; cache the live dashboard.
- `capture_full` buffers entire streamed responses in memory just to read the last SSE
  event; capture writes are synchronous and re-open the file each time. Keep a bounded
  tail; hold one handle / offload writes. `proxy.py:421`, `capture.py:74`.
- Quadratic `bytes +=` in chunked body assembly — use `bytearray`, 64KB reads. `proxy.py:358`.
- Per-request verbose INFO logging (30-80 records/request, JSON pretty-print) — gate
  behind DEBUG. `proxy.py:615`.

**Docs**
- `TDD.md:576` states `sock_read=30s`; code uses `120`. Env-var tables omit
  `CTC_ADMINS`, `CTC_CA_CERT`, `CTC_FREE_ALLOWANCE_AIU`, `CTC_DEFAULT_PLEDGE_PCT`,
  `CTC_DEFAULT_CHIP_IN_AIU`, `CTC_RESTRICT_CONNECT`, `CTC_EXTRA_ALLOWED_HOSTS`.
  `metering-contract.md:130` still references a "token exchange" that the corrected
  model says doesn't exist. `/models/session` pinning + 401 self-heal is undocumented.

---

## P3 — minor / cosmetic

- `/auth/callback` 500s on GitLab error responses (`body["access_token"]` KeyError) —
  return a clean 400/redirect. `oauth.py:47`. Login race: `upsert_user` `DO NOTHING`
  then `get_user_by_id` can return None → 500; also `display_name` never refreshes.
- `GET /api/users/{id}` 404 shape inconsistent (`{"error":"not found"}` vs middleware
  shape); `DELETE /api/proxy-token/{id}` returns 204 for unknown/foreign ids (no IDOR).
- LIKE wildcard injection in user search (`%`/`_` unescaped; authenticated, LIMIT 8).
- Admin `reveal-pat` returns plaintext PAT over the wire (audited, admin-only, but
  cleartext under `http` transport) — consider requiring https for that route.
- PAT ownership not verified on registration (`enforce_identity=False`) — any logged-in
  user can register any valid GHE PAT. Accepted consequence of GitLab-vs-GHE identity split.
- `rules.next_bucket` is dead code contradicting the real selection order — delete.
- Frontend: OnboardingScreen bounces to /signin while session is still loading
  (`=== undefined` not handled); HeaderSearch stale-response race; leaderboard
  divide-by-zero → `width:"NaN%"`; Dashboard "Top users" can link to `/users/null`;
  History/Marketplace missing empty/loading states; sub-0.005-AIU values render "0.00";
  clickable `<span>`s lack keyboard a11y; sign-out failure unhandled.
- Bytes after the CONNECT head are dropped (optimistic-TLS clients hang); `_read_head`
  buffers unboundedly on garbage input; response header dict collapses duplicate
  `Set-Cookie`.

---

## Verified sound (no action)

Nano-AIU ledger math (integer, no unit mixing); SSE extractor (last-event-wins,
`[DONE]`/truncation tolerant, bool excluded); 402/401 failover never double-debits;
grant-spill arithmetic; `BEGIN IMMEDIATE`+WAL discipline (no await inside txn);
leaderboard/tier banding. No committed secrets (`.env`, `*.pem`, `*.db` gitignored);
SQL fully parameterized; AES-256-GCM with per-message random nonce; timing-safe
session/OAuth-state HMAC; OAuth state-CSRF verified, no open redirect; token swap
scoped to exact `SWAP_HOSTS` (no cross-host PAT leak); admin authz on every admin
route (401-then-403). Frontend: no XSS sinks, no secrets in bundle/localStorage,
httpOnly SameSite=Lax cookie, endpoint parity with the server. Host sets
(`MITM/SWAP/_LOCALHOST_ALIASES`), billable paths/host/method, and the core
architecture claims in CLAUDE.md all match the code.
