# Control-Plane HTTP API Contract

This document specifies the API contract for the control-plane server (`api_server.py`,
plus the route modules `ctc/api/web_routes.py` and `ctc/api/admin_routes.py`), which
handles user authentication, PAT management, proxy-token issuance, the marketplace,
and the admin panel.

**Client:** the React frontend app.
**Auth:** all `/api/*` endpoints require a valid session cookie (`ctc_session`); absent or invalid cookies return `401`.
**CORS:** the control plane allows credentials and requests from `CTC_APP_ORIGIN` (env var). `Access-Control-Allow-Headers` is `content-type` only, `Access-Control-Allow-Methods` is `GET,POST,PATCH,DELETE,OPTIONS`. OPTIONS preflight is answered `204` before routing. (The frontend sends **no** custom headers — the legacy `X-CTC-User` header was removed so cross-origin preflight passes.)
**Cookies:** `ctc_session` is httpOnly, SameSite=Lax, and server-signed with `CTC_SECRET_KEY`. Sessions are revocable and have a TTL.
**Error responses:** all errors return JSON: `{ "error": "<code>", "message": "<details>" }`. The `error` code is derived from the HTTP reason phrase (lower-cased, spaces → `_`); e.g. malformed JSON → `{"error":"bad_request",...}` (400), pydantic validation failure → `{"error":"unprocessable_entity",...}` (422).

**Rate limits (in-process token bucket, per 60 s window):**

| Endpoint | Scope | Limit |
|---|---|---|
| `GET /auth/login` | per client IP | 10 / min |
| `POST /api/pat` | per user | 5 / min |
| `POST /api/proxy-token` | per user | 10 / min |

Exceeding a limit returns `429 { "error": "too_many_requests", ... }`. The limiter is
single-process (adequate for the one control-plane process); a multi-node deployment
would need a shared store.

---

## Route index

| Method | Path | Auth | Section |
|---|---|---|---|
| GET | `/auth/login` | none | [Auth](#authentication--session-lifecycle) |
| GET | `/auth/callback` | none (state check) | [Auth](#authentication--session-lifecycle) |
| POST | `/auth/logout` | session (optional) | [Auth](#authentication--session-lifecycle) |
| GET | `/healthz` | none | — (returns `{"status":"ok"}`) |
| GET | `/api/me` | session | [User & Account](#user--account-management) |
| POST | `/api/pat` | session | [User & Account](#user--account-management) |
| DELETE | `/api/pat` | session | [User & Account](#user--account-management) |
| POST | `/api/onboarding/complete` | session | [User & Account](#user--account-management) |
| POST | `/api/proxy-token` | session | [Proxy Tokens](#proxy-tokens-cli-authentication) |
| GET | `/api/proxy-token` | session | [Proxy Tokens](#proxy-tokens-cli-authentication) |
| DELETE | `/api/proxy-token/{id}` | session | [Proxy Tokens](#proxy-tokens-cli-authentication) |
| GET | `/api/users/search` | session | [Users](#users) |
| GET | `/api/users/{id}` | session | [Users](#users) |
| GET | `/api/requests` | session | [Marketplace](#marketplace-requests--funding) |
| POST | `/api/requests` | session | [Marketplace](#marketplace-requests--funding) |
| POST | `/api/requests/{id}/donate` | session | [Marketplace](#marketplace-requests--funding) |
| POST | `/api/requests/{id}/pool-fund` | session | [Marketplace](#marketplace-requests--funding) |
| POST | `/api/pool/return` | session | [Marketplace](#marketplace-requests--funding) |
| DELETE | `/api/requests/{id}` | session | [Marketplace](#marketplace-requests--funding) |
| GET | `/api/settings` | session | [Settings](#settings) |
| PATCH | `/api/settings` | session | [Settings](#settings) |
| GET | `/api/profile` | session | [Reports](#reports-profile-dashboard-leaderboard-history) |
| GET | `/api/dashboard` | session | [Reports](#reports-profile-dashboard-leaderboard-history) |
| GET | `/api/leaderboard` | session | [Reports](#reports-profile-dashboard-leaderboard-history) |
| GET | `/api/history` | session | [Reports](#reports-profile-dashboard-leaderboard-history) |
| GET | `/api/admin/users` | admin | [Admin](#admin) |
| GET | `/api/admin/users/{id}` | admin | [Admin](#admin) |
| POST | `/api/admin/users/{id}/reveal-pat` | admin | [Admin](#admin) |
| POST | `/api/admin/users/{id}/pledge` | admin | [Admin](#admin) |
| GET | `/api/admin/settings` | admin | [Admin](#admin) |
| PATCH | `/api/admin/settings` | admin | [Admin](#admin) |

**Wire units:** all credit/AIU values on `/api/*` endpoints are **raw nano-AIU integers**
(1 AIU = 1,000,000,000 nano-AIU). The frontend divides by 1e9 for display. The two
exceptions are the `POST /api/pat` response and the `*_aiu` fields it returns, which are
whole AIU (see below).

---

## Authentication & Session Lifecycle

### GET /auth/login

Start the GitLab OAuth flow.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/auth/login` |
| **Auth** | none |
| **Rate limit** | 10 / min per client IP → `429` |
| **Request body** | — |
| **Success response** | 302 redirect to `GITLAB_BASE/oauth/authorize?...&state=...` |
| **Side effects** | Sets `ctc_oauth_state` cookie (httpOnly, SameSite=Lax, short-lived 10 min) containing signed OAuth state. |

---

### GET /auth/callback

Complete the GitLab OAuth flow.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/auth/callback?code=<code>&state=<state>` |
| **Auth** | none (but verifies `state` against `ctc_oauth_state` cookie) |
| **Request body** | — |
| **Query params** | `code` (from GitLab), `state` (CSRF token) |
| **Success response** | 302 redirect to `CTC_APP_ORIGIN` |
| **Side effects** | On valid `state`: exchanges code for GitLab access token, fetches GitLab identity (`read_user` scope), **upserts** the user (insert-or-update display name), creates a session record, sets `ctc_session` cookie. Deletes `ctc_oauth_state` cookie. |
| **Error (400)** | Bad/missing `state` or state signature mismatch: `{ "error": "bad_request", "message": "bad oauth state" }`. Also `400` when GitLab's token/identity exchange returns no `access_token`/`login` (`OAuthExchangeError`). |

User is created as a `consumer` on first login. The `user_id` is an opaque uuid hex
string, reused for accounting. The `ghe_login` field stores the **GitLab username**
(the column name is kept for compatibility). Upsert-then-get-by-login avoids the
concurrent-first-login race and refreshes a stale display name.

---

### POST /auth/logout

Revoke the session and clear cookies.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/auth/logout` |
| **Auth** | session cookie (optional) |
| **Success response** | 204 No Content |
| **Side effects** | Revokes the session record (if valid cookie present); clears `ctc_session` cookie. |

Safe to call without a valid session (idempotent).

---

## User & Account Management

### GET /api/me

Fetch the authenticated user's profile plus the effective deployment config the
frontend needs to render itself.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/me` |
| **Auth** | session cookie (required) |
| **Success response** | 200 OK |

**Response body:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "ghe_login": "octocat",
  "display_name": "Octo Cat",
  "role": "consumer",
  "has_pat": false,
  "onboarded": false,
  "is_admin": false,
  "web_transport": "http",
  "participants_mode": "givers_only",
  "shared_pool_enabled": false,
  "credit_to_euro_rate": 0.0,
  "default_chip_in_aiu": 100,
  "request_expiry_hours": 24,
  "request_expiry_max_hours": 72
}
```

| Field | Type | Description |
|---|---|---|
| `user_id` | string (uuid hex) | Opaque internal user ID, used by accounting. |
| `ghe_login` | string | GitLab username (identity; name kept for compatibility). |
| `display_name` | string | Display name from GitLab. |
| `role` | string | `"consumer"` (default) or `"giver"` (after storing a PAT). |
| `has_pat` | boolean | Whether the user currently has a stored PAT. |
| `onboarded` | boolean | Whether the user finished the first-run walkthrough. |
| `is_admin` | boolean | Whether the user's login is in `CTC_ADMINS`. |
| `web_transport` | string | `"http"` or `"https"` (from `CTC_WEB_TRANSPORT`). |
| `participants_mode` | string | Effective `givers_only` / `givers_and_consumers` (admin-controllable). |
| `shared_pool_enabled` | boolean | Whether the shared pool is on (admin-controllable). |
| `credit_to_euro_rate` | number | Optional display rate (0 = disabled). |
| `default_chip_in_aiu` | integer | Default chip-in amount presented in the UI (AIU). |
| `request_expiry_hours` | integer | Default request expiry (hours); the compose form uses it as the default. |
| `request_expiry_max_hours` | integer | Admin-set ceiling; the compose form clamps its options to ≤ this to avoid a guaranteed 422. |

**Error (401):** no session cookie: `{ "error": "unauthorized", "message": "no session" }`.

---

### POST /api/pat

Store the user's GitHub PAT for use as a giver. Validated live against
`/copilot_internal/user` on the GHE API host.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/pat` |
| **Auth** | session cookie (required) |
| **Rate limit** | 5 / min per user → `429` |
| **Request body** | JSON object |

**Request body:**
```json
{ "pat": "github_pat_..." }
```

| Field | Type | Required | Description |
|---|---|---|---|
| `pat` | string | yes | The user's GitHub Enterprise PAT (encrypted at rest). |

**Success response (200 OK):**
```json
{
  "ghe_login": "octocat",
  "quota_aiu": 3830,
  "entitlement_aiu": 4000,
  "remaining_aiu": 3830,
  "reset_date": "2026-07-01",
  "pledged_nano": 383000000000,
  "used_nano": 170000000000
}
```

| Field | Type | Description |
|---|---|---|
| `ghe_login` | string | Echoes the session user's login (see the identity note below — the PAT's own GHE owner is **not** cross-checked). |
| `quota_aiu` | integer (AIU) | The PAT's **remaining** premium-interactions headroom (compat alias of `remaining_aiu`). *This is remaining, not entitlement.* |
| `remaining_aiu` | integer (AIU) | `premium_interactions.remaining` at submit time (0 if GitHub omits it — assume spent). |
| `entitlement_aiu` | integer (AIU) | `premium_interactions.entitlement` (the monthly ceiling). The giver's **cycle quota** is set to this entitlement; the pre-connect burn (`entitlement − remaining`) is booked immediately as the owner's own usage. |
| `reset_date` | string \| null | GitHub's `quota_reset_date` (cycle boundary), or null. |
| `pledged_nano` | integer (nano-AIU) | The giver's current pledge into the shared pool (a default pledge of `CTC_DEFAULT_PLEDGE_PCT`% of remaining is applied on first connect when pool is on). |
| `used_nano` | integer (nano-AIU) | Own + bypass consumption booked so far this cycle (includes the pre-connect burn). |

**Side effects (on success):**
- Encrypts the PAT at rest (AES-256-GCM, key derived from `CTC_SECRET_KEY`) and stores it in `giver_pats`.
- Sets the user's role to `"giver"` and marks PAT health `valid`.
- Sets the giver's **cycle quota to the entitlement ceiling**, stores a quota snapshot (entitlement / remaining / reset date), applies the default pledge, and reconciles the pre-connect burn immediately.
- The PAT itself is never returned, logged, or stored in plaintext.

**Error (400):**
- Body is not a JSON object: `{ "error": "bad_request", "message": "body must be a JSON object" }`.
- Empty/missing `pat`: `{ "error": "bad_request", "message": "pat required" }`.
- `/copilot_internal/user` returns non-200 or no valid entitlement (`PatInvalid`): `{ "error": "bad_request", "message": "..." }`.

**Error (409):**
- `AccountingError` (e.g. `InvalidPledge` when a giver **re-submits** after their entitlement dropped below already-consumed pool spend): `{ "error": "conflict", "message": "..." }`.

**Error (401):** no session cookie.

> **Identity note — ownership is deliberately unverified.** Under GitLab OAuth the CTC
> login is a GitLab username, which can never equal a PAT's GHE owner, so the server
> calls `validate_and_store_pat(..., enforce_identity=False)`. **There is no
> identity-mismatch (`409`) response** — the check is disabled by design. Any logged-in
> user can register any valid GHE PAT; this is an accepted consequence of the
> GitLab-vs-GHE identity split (the PAT is validated for *entitlement*, not *ownership*).

---

### DELETE /api/pat

Disconnect the giver — delete the stored PAT and neutralize their cycle credit.

| | |
|---|---|
| **Method** | DELETE |
| **Path** | `/api/pat` |
| **Auth** | session cookie (required) |
| **Success response** | 204 No Content |

**Side effects:**
- Deletes the encrypted PAT (attribution can then forward neither the user's own calls nor the pool from them, so the credit becomes inert).
- If the user already had a `giver_cycles` row, zeroes its quota **and** pledge, floored at already-consumed pool spend so the accounting invariants hold. A plain consumer (no PAT ever connected) is **not** given a fabricated `giver_cycles` row — that would misclassify them as a giver in dashboard aggregates.
- Sets the user's role back to `"consumer"`.

**Error (401):** no session cookie.

---

### POST /api/onboarding/complete

Mark the first-run walkthrough as finished.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/onboarding/complete` |
| **Auth** | session cookie (required) |
| **Request body** | — |
| **Success response** | 204 No Content |
| **Side effects** | Sets the user's `onboarded` flag (reflected in `/api/me`). |

**Error (401):** no session cookie.

---

## Proxy Tokens (CLI Authentication)

Users get a per-device proxy token to set as `COPILOT_GITHUB_TOKEN` in the CLI. The
token is shown **once**; list endpoints redact it. The proxy maps the token's hash to
the user. The frontend calls `GET /api/proxy-token` on the profile screen and mints a
**new** token only on an explicit user action (button click) — never on page mount.

### POST /api/proxy-token

Issue a new proxy token for the user (shown once).

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/proxy-token` |
| **Auth** | session cookie (required) |
| **Rate limit** | 10 / min per user → `429` |
| **Request body** | — (empty) |

**Success response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "token": "github_pat_11XXXXXXXXXXXXXXXXXXXXXXXXXX",
  "fingerprint": "XXXX",
  "ca_fingerprint": "AB12CD34..."
}
```

| Field | Type | Description |
|---|---|---|
| `id` | string (uuid hex) | Client-facing token ID (for revocation / display). |
| `token` | string | The actual proxy token (PAT-shaped). **Shown only in this response.** |
| `fingerprint` | string | Last 4 characters of the token (shown in the list endpoint). |
| `ca_fingerprint` | string | SHA-256 of the proxy's MITM CA cert (`CTC_CA_CERT`), so the install one-liner can display the expected cert fingerprint. |

**Side effects:**
- Generates a random PAT-shaped token (≥256 bits entropy); stores only `sha256(token)`.
- **Active-token cap:** at most `MAX_ACTIVE_PROXY_TOKENS` (10) active tokens per user. When minting at the cap, the **oldest** active token is auto-revoked first, so a client that keeps minting can't accumulate unbounded live tokens.

**Error (401):** no session cookie.

---

### GET /api/proxy-token

List the user's proxy tokens (raw token values redacted). Consumed by the frontend
profile screen to show existing tokens without minting a new one.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/proxy-token` |
| **Auth** | session cookie (required) |
| **Success response** | 200 OK |

**Response body:**
```json
[
  { "id": "...", "fingerprint": "XXXX", "created_at": 1713456000, "revoked": false },
  { "id": "...", "fingerprint": "YYYY", "created_at": 1713460000, "revoked": true }
]
```

| Field | Type | Description |
|---|---|---|
| `id` | string (uuid hex) | Token ID. |
| `fingerprint` | string | Last 4 characters (for identification). |
| `created_at` | integer (unix seconds) | When the token was created. |
| `revoked` | boolean | Whether the token is revoked (`revoked_at IS NOT NULL`). |

**Error (401):** no session cookie.

---

### DELETE /api/proxy-token/{id}

Revoke a proxy token.

| | |
|---|---|
| **Method** | DELETE |
| **Path** | `/api/proxy-token/<id>` |
| **Auth** | session cookie (required) |
| **URL params** | `id` (uuid hex, from the list endpoint) |
| **Success response** | 204 No Content |
| **Side effects** | Sets `revoked_at` on the token record (scoped to the caller's user id); the token is immediately invalid for CLI requests. Unknown/foreign ids also return `204` (no information leak). |

**Error (401):** no session cookie.

---

## Users

### GET /api/users/search

Search users by login/display name for the compose-form target picker and header search.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/users/search?q=<query>` |
| **Auth** | session cookie (required) |
| **Success response** | 200 OK — `{ "users": [ { id, login, name, initials, role } ] }` (max 8; empty `q` → `{ "users": [] }`). LIKE wildcards in `q` are escaped. |

### GET /api/users/{id}

Public profile of another user (used by profile links).

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/users/<id>` |
| **Auth** | session cookie (required) |
| **Success response** | 200 OK — `PublicProfileDTO` (camelCase; nano-AIU): `id, name, login, initials, role, tier, net, donated, donationsMade`, plus a public **credit cycle** for givers (`entitlement, used, pledged, pledgedConsumed, pledgedRemaining, donatedConsumed, donatedRemaining, left`). Consumers omit the credit block. |
| **Error (404)** | Unknown id → `{ "error": "not_found", "message": "user not found" }` (middleware shape). |

The public credit block uses the giver's **snapshot entitlement** (no live GHE call on a
profile visit); usage/pledge splits come from events.

---

## Marketplace (requests & funding)

All amounts are **nano-AIU** integers. Request/response DTOs are camelCase
(`ctc/api/serializers.py`).

### GET /api/requests

List the active cycle's marketplace requests plus viewer funding context.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/requests?filter=all\|pro\|noob` |
| **Auth** | session cookie (required) |
| **Success response** | 200 OK |

**Response body:** `{ requests: PublicRequest[], counts: {all, pro, noob}, poolEnabled,
poolAvailable, viewerPersonalRemaining, viewerReceivedRemaining }`.

`PublicRequest`: `id, requesterId, requesterName, initials, requesterRole ('pro'|'noob'),
amountNeeded, amountFunded, fundedConsumed, reason, target, createdAt, expiresAt,
status, donorCount, isOwn, poolFunded`.

- `status` ∈ `open | partially_funded | fulfilled | expired | cancelled` (derived, never stored).
- `target` is resolved to a **display name** for rendering (see the directed-target note under `POST /api/requests`).

### POST /api/requests

Create a marketplace request.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/requests` |
| **Auth** | session cookie (required) |
| **Request body** | `CreateRequestDTO` |
| **Success response** | 200 OK — the created `PublicRequest`. |

**Request body (`CreateRequestDTO`):**

| Field | Type | Constraints |
|---|---|---|
| `amountNeeded` | integer (nano-AIU) | `> 0` and `≤ 10,000 AIU` (`MAX_REQUEST_NANO`). |
| `reason` | string | length 1–500. |
| `target` | string \| null | ≤ 200 chars; the **giver's userId** for a directed request (optional). |
| `expiryHours` | integer \| null | Defaults to `request_expiry_hours`; must be `1 ≤ h ≤ request_expiry_max_hours` else `422`. Clamped to the cycle end. |

> **Directed-target contract.** For a directed request the client sends the target
> giver's **userId** (from the search picker, `option value={userId}`). The server
> stores it verbatim and the serializer resolves the id → the giver's **display name**
> when building `PublicRequest.target`. Legacy rows that stored a raw name (no matching
> user id) render **verbatim**.

**Errors:** `422` for out-of-range `expiryHours`; pydantic validation (bad amount/reason) → `422`.

### POST /api/requests/{id}/donate

Chip in to a request from your own retained credit or from credit routed to you.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/requests/<id>/donate` |
| **Auth** | session cookie (required) |
| **Request body** | `DonateDTO`: `{ amount: >0 (nano-AIU), source: "personal" \| "received" }` |
| **Success response** | 200 OK — the updated `PublicRequest`. |
| **Errors** | `404` unknown request; `409` request closed; `422` insufficient/invalid credit. |

`source: "received"` re-donates credit granted to the caller (chains attribution to the
original PAT holder); `"personal"` (default) spends the caller's own retained credit.

### POST /api/requests/{id}/pool-fund

The **requester** tops up their own request from the shared pool.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/requests/<id>/pool-fund` |
| **Auth** | session cookie (required) |
| **Request body** | `DonateDTO` (`amount` used; `source` ignored) |
| **Success response** | 200 OK — the updated `PublicRequest`. |
| **Errors** | `404` unknown request; `403` not the requester; `409` request closed **or** shared pool disabled; `422` insufficient/invalid amount. |

### POST /api/pool/return

Return credit routed to you back into the shared pool.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/pool/return` |
| **Auth** | session cookie (required) |
| **Request body** | `DonateDTO` (`amount`) |
| **Success response** | 200 OK — `{ poolAvailable, receivedRemaining }` (nano-AIU). |
| **Errors** | `409` shared pool disabled; `422` insufficient/invalid amount. |

### DELETE /api/requests/{id}

Soft-cancel your own request (kept for history, hidden from the board; unspent grant
credit returns to donors/pool).

| | |
|---|---|
| **Method** | DELETE |
| **Path** | `/api/requests/<id>` |
| **Auth** | session cookie (required) |
| **Success response** | 204 No Content |
| **Errors** | `404` unknown request; `403` not the requester; `409` already closed. |

---

## Settings

### GET /api/settings

Own giver settings for the profile/settings screen.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/settings` |
| **Auth** | session cookie (required) |
| **Success response** | 200 OK — `SettingsDTO`: `name, login, role, hasPat, patHealth (valid\|expired\|forbidden\|no_entitlement\|unreachable\|null), patHealthCheckedAt, totalCredit (nano-AIU\|null), pledgedSurplus (nano-AIU)`. |

### PATCH /api/settings

Update the giver's pledge.

| | |
|---|---|
| **Method** | PATCH |
| **Path** | `/api/settings` |
| **Auth** | session cookie (required) |
| **Request body** | `SettingsPatchDTO`: `{ pledgedSurplus?, name?, role?, pat? }` (only `pledgedSurplus` is acted on today). |
| **Success response** | 200 OK — the updated `SettingsDTO`. |
| **Errors** | `422` invalid pledge (`InvalidPledge`), or setting a non-zero pledge while the shared pool is off. |

---

## Reports (profile, dashboard, leaderboard, history)

All four are session-gated reads returning wire-ready JSON with **camelCase keys and raw
nano-AIU** values.

### GET /api/profile

The caller's own profile. For a giver, triggers a live-quota reconcile before reading
usage so profile/leaderboard/dashboard all derive the same number (no-op when the quota
snapshot is stale). Returns `OwnProfileDTO` — the received/donated/pledged/retained
breakdown, entitlement/remaining/used/left, aristocracy tier, and `resetDate`.

### GET /api/dashboard

The live cycle dashboard (per-user aggregates + pool state), computed for the active cycle.

### GET /api/leaderboard

Giver standings (tiers/net) for the active cycle.

### GET /api/history

Past-cycle history reports. Archived cycles are served from a **frozen** snapshot
(`cycle_reports`); the active cycle is recomputed live.

All four require a session (`401` otherwise) and a resolvable active cycle
(`503 { "error": "service_unavailable", "message": "no active cycle" }` if none).

---

## Admin

Admin routes require the caller's `ghe_login` to be in `CTC_ADMINS`. The auth model is
**401-then-403**: no session → `401 "no session"`; valid session but not an admin →
`403 "admin only"`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/users` | List all users with role, onboarded, PAT fingerprint/health, token count, and giver balances (quota/pledge/pledge-remaining, plus `used`/`donated` so the admin pledge control can size its percentage presets against the shareable slice). |
| GET | `/api/admin/users/{id}` | One user's detail: proxy tokens, PAT fingerprint, health, balances. `404` if unknown. |
| POST | `/api/admin/users/{id}/reveal-pat` | Return a giver's PAT **in cleartext** (audited via `admin_audit`). **`403` unless `web_transport == "https"`** (never over plain HTTP). `404` if no PAT on file. |
| POST | `/api/admin/users/{id}/pledge` | Route an idle giver's credit to the shared pool on their behalf (same primitive as the user's own pledge slider, `engine.set_pledge`). Body `{ "pledge": <nano-AIU int> }`. Audited via `admin_audit` (`action="set_pledge"`). `409` if the pool is off / user is not a giver / has no credit this cycle; `422` if the pledge is outside `[already-consumed, quota]`; `400` on a bad body; `404` if unknown. Returns the giver's updated balances. |
| GET | `/api/admin/settings` | Effective runtime settings + boot config (`web_transport`, source). |
| PATCH | `/api/admin/settings` | Update runtime settings. Body must be a JSON object (`400` otherwise); invalid values → `400` (`validate_patch`). Returns the new effective view. |

---

## Session & Security Details

### Cookie scheme

- **Name:** `ctc_session`
- **HttpOnly:** yes
- **Secure:** set when `CTC_APP_ORIGIN` is https (plain-HTTP VPN/LAN mode omits it)
- **SameSite:** Lax
- **Value:** signed with `CTC_SECRET_KEY` (HMAC-SHA256); server-side session records with a TTL.

`CTC_SECRET_KEY` must be **≥ 16 characters** — the server (and proxy) refuse to start
otherwise (`validate_secret`). It is used for PAT encryption (AES-256-GCM, key =
`sha256(secret)`, per-message random nonce) and cookie/state signing.

### CORS

- **Origin:** `CTC_APP_ORIGIN`
- **Methods:** `GET,POST,PATCH,DELETE,OPTIONS`
- **Headers:** `content-type` only
- **Credentials:** included (cookies)

### Secrets (never exposed)

Never logged, returned, or sent to the client: `CTC_SECRET_KEY`,
`GITLAB_OAUTH_CLIENT_SECRET`, user PATs (encrypted; decrypted only in-process at
proxy-routing time, or by the audited admin reveal-pat route under https), raw proxy
tokens (shown only in the `POST /api/proxy-token` response), and OAuth access tokens
(used only to read identity).

---

## Example Flow

1. **User opens the React app** → `GET /auth/login` → 302 to GitLab (signed state cookie).
2. **User authenticates on GitLab** → `GET /auth/callback?code&state` → server verifies state, exchanges code, fetches identity, upserts user, sets `ctc_session`, redirects to the app origin.
3. **React calls `GET /api/me`** → user profile + effective deployment config.
4. **(Giver) React calls `POST /api/pat { pat }`** → validated against `/copilot_internal/user`; quota set to the entitlement ceiling, PAT encrypted, role → `giver`; responds `{ ghe_login, quota_aiu (remaining), entitlement_aiu, remaining_aiu, reset_date, pledged_nano, used_nano }`.
5. **React calls `GET /api/proxy-token`** on the profile screen to show existing tokens; **`POST /api/proxy-token`** only when the user clicks "generate" → `{ id, token, fingerprint, ca_fingerprint }` (shown once).
6. **User sets `COPILOT_GITHUB_TOKEN=<token>` and runs copilot** → the proxy resolves the token hash to the user, picks a giver source, forwards + swaps the giver's PAT, and bills.
7. **(Optional) `DELETE /api/proxy-token/:id`** revokes a token; **`DELETE /api/pat`** disconnects the giver.
