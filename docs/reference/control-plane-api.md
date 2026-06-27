# Control-Plane HTTP API Contract

This document specifies the API contract for the control-plane server (`api_server.py`), which handles user authentication, PAT management, and proxy-token issuance.

**Client:** the React frontend app (via the frontend agent).
**Auth:** all `/api/*` endpoints require a valid session cookie (`ctc_session`); absent or invalid cookies return `401`.
**CORS:** the control plane allows credentials and requests from `CTC_APP_ORIGIN` (env var).
**Cookies:** `ctc_session` is httpOnly, SameSite=Lax, and server-signed with `CTC_SECRET_KEY`. Sessions are revocable and have a TTL.
**Error responses:** all errors return JSON: `{ "error": "<code>", "message": "<details>" }`.

---

## Authentication & Session Lifecycle

### GET /auth/login

Start the GitLab OAuth flow.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/auth/login` |
| **Auth** | none |
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
| **Side effects** | On valid `state`: exchanges code for GitLab access token, fetches GitLab identity (`read_user` scope), upserts user (if new), creates session record, sets `ctc_session` cookie. Deletes `ctc_oauth_state` cookie. |
| **Error (400)** | Bad/missing `state` or state signature mismatch: `{ "error": "bad oauth state", "message": "..." }` |

User is created as a `consumer` on first login. The `user_id` is an opaque uuid hex string, reused for accounting. The `ghe_login` field stores the GitLab username.

---

### POST /auth/logout

Revoke the session and clear cookies.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/auth/logout` |
| **Auth** | session cookie (optional) |
| **Request body** | — |
| **Success response** | 204 No Content |
| **Side effects** | Revokes the session record (if valid cookie present); clears `ctc_session` cookie. |

Safe to call without a valid session (idempotent).

---

## User & Account Management

### GET /api/me

Fetch the authenticated user's profile.

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/me` |
| **Auth** | session cookie (required) |
| **Request body** | — |
| **Success response** | 200 OK |

**Response body:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "ghe_login": "octocat",
  "display_name": "Octo Cat",
  "role": "consumer",
  "has_pat": false
}
```

| Field | Type | Description |
|---|---|---|
| `user_id` | string (uuid hex) | Opaque internal user ID, used by accounting. |
| `ghe_login` | string | GitLab username (identity; the field name is kept for compatibility). |
| `display_name` | string | User's display name from GitLab. |
| `role` | string | `"consumer"` (default) or `"giver"` (after storing a PAT). |
| `has_pat` | boolean | Whether the user has stored a valid PAT. |

**Error (401):** no session cookie: `{ "error": "no session", "message": "..." }`.

---

### POST /api/pat

Store the user's GitHub PAT for use as a giver.

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/pat` |
| **Auth** | session cookie (required) |
| **Request body** | JSON object |

**Request body:**
```json
{
  "pat": "github_pat_..."
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `pat` | string | yes | The user's GitHub Enterprise PAT (will be encrypted at rest). |

**Success response (200 OK):**
```json
{
  "ghe_login": "octocat",
  "quota_aiu": 4000
}
```

| Field | Type | Description |
|---|---|---|
| `ghe_login` | string | The GHE login the PAT is registered to (confirmed via `/copilot_internal/user`). |
| `quota_aiu` | integer | The PAT's current `premium_interactions.entitlement` quota in AIU. Used to initialize the giver's quota for the active billing cycle. |

**Side effects (on success):**
- Encrypts PAT at rest using AES-GCM (key: `CTC_SECRET_KEY`) and stores in `giver_pats` table.
- Sets the user's role to `"giver"`.
- Initializes the giver's quota in the accounting engine for the active cycle.
- The PAT itself is never returned, logged, or stored in plaintext.

**Error (400):**
- Empty/missing `pat`: `{ "error": "pat required", "message": "..." }`.
- `/copilot_internal/user` returns non-200: `{ "error": "invalid", "message": "... /copilot_internal/user -> <status>" }`.
- No valid `premium_interactions.entitlement` on the PAT: `{ "error": "invalid", "message": "no premium_interactions entitlement on this PAT" }`.

**Error (409):**
- PAT's GHE login does not match the session user's GHE login: `{ "error": "identity mismatch", "message": "PAT belongs to <login>, not <session_ghe_login>" }`.

**Error (401):** no session cookie: `{ "error": "no session", "message": "..." }`.

---

## Proxy Tokens (CLI Authentication)

Users get a per-device proxy token to set as `COPILOT_GITHUB_TOKEN` in the CLI. The token is shown only once; the list endpoint redacts it. The proxy maps proxy tokens to users.

### POST /api/proxy-token

Issue a new proxy token for the user (shown once).

| | |
|---|---|
| **Method** | POST |
| **Path** | `/api/proxy-token` |
| **Auth** | session cookie (required) |
| **Request body** | — (empty) |

**Success response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "token": "github_pat_11XXXXXXXXXXXXXXXXXXXXXXXXXX",
  "fingerprint": "XXXX"
}
```

| Field | Type | Description |
|---|---|---|
| `id` | string (uuid hex) | Client-facing token ID. Use this for revocation (DELETE) or display. |
| `token` | string | The actual proxy token (PAT-shaped: `github_pat_` + ~80 url-safe chars). **This is shown only in this response**; never again in list or other endpoints. Store it locally. |
| `fingerprint` | string | Last 4 characters of the token. Displayed in the list endpoint for identification. |

**Side effects:**
- Generates a random PAT-shaped token (≥256 bits entropy).
- Stores only `sha256(token)` in the `proxy_tokens` table (never the plaintext).
- Marks the token as active (`revoked_at = NULL`).

**Error (401):** no session cookie: `{ "error": "no session", "message": "..." }`.

---

### GET /api/proxy-token

List the user's proxy tokens (without the raw token values).

| | |
|---|---|
| **Method** | GET |
| **Path** | `/api/proxy-token` |
| **Auth** | session cookie (required) |
| **Request body** | — |

**Success response (200 OK):**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "fingerprint": "XXXX",
    "created_at": 1713456000,
    "revoked": false
  },
  {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "fingerprint": "YYYY",
    "created_at": 1713460000,
    "revoked": true
  }
]
```

| Field | Type | Description |
|---|---|---|
| `id` | string (uuid hex) | Token ID. |
| `fingerprint` | string | Last 4 characters of the token (for user identification). |
| `created_at` | integer (unix timestamp) | When the token was created. |
| `revoked` | boolean | Whether the token has been revoked (`revoked_at IS NOT NULL`). |

**Note:** the raw token is never returned here; it was shown only in the `POST` response.

**Error (401):** no session cookie: `{ "error": "no session", "message": "..." }`.

---

### DELETE /api/proxy-token/:id

Revoke a proxy token.

| | |
|---|---|
| **Method** | DELETE |
| **Path** | `/api/proxy-token/<id>` |
| **Auth** | session cookie (required) |
| **Request body** | — |
| **URL params** | `id` (uuid hex, from the list endpoint) |

**Success response (204):** No Content.

**Side effects:**
- Sets `revoked_at` to the current timestamp on the token record.
- The token is immediately invalidated for CLI requests.

**Error (401):** no session cookie: `{ "error": "no session", "message": "..." }`.

---

## Session & Security Details

### Cookie Scheme

All session cookies are:
- **Name:** `ctc_session`
- **HttpOnly:** yes (not accessible to JavaScript)
- **Secure:** yes (HTTPS only; in dev/localhost only, can be disabled)
- **SameSite:** Lax (prevents cross-site token leakage; allows same-site link navigation)
- **Value:** signed with `CTC_SECRET_KEY` (HMAC-SHA256); server-side session records with TTL (configurable, typically hours).

### CORS

The control plane allows:
- **Origin:** `CTC_APP_ORIGIN` (env var, e.g., `http://localhost:3000` for dev, `https://app.ctc.example.com` for prod)
- **Methods:** GET, POST, DELETE
- **Credentials:** included (cookies)
- **Headers:** standard (Content-Type, etc.)

### Secrets (Never Exposed)

The following secrets are never logged, returned in responses, or sent to the client:
- `CTC_SECRET_KEY` (symmetric key for PAT encryption + cookie/state signing)
- `GITLAB_OAUTH_CLIENT_SECRET` (OAuth app secret)
- User PATs (encrypted, decrypted only in-process at proxy-routing time)
- Raw proxy tokens (shown only in the `POST /api/proxy-token` response)
- OAuth access tokens (used only to read identity, never stored or returned)

---

## Example Flow

1. **User opens the React app.**
   - React redirects to `GET /auth/login`.
   - Server responds 302 to GitLab's authorize endpoint (with signed state cookie).

2. **User authenticates on GitLab.**
   - GitLab redirects to `GET /auth/callback?code=...&state=...`.
   - Server verifies state, exchanges code for GitLab OAuth token, fetches GitLab identity (`read_user` scope), upserts user, creates session, sets `ctc_session` cookie, redirects to the app origin.
   - Browser now has the session cookie in its jar.

3. **React calls `GET /api/me`.**
   - Request includes `ctc_session` cookie.
   - Server responds with user profile: `{ user_id, ghe_login, display_name, role: "consumer", has_pat: false }` (where `ghe_login` is the GitLab username).

4. **(If giver) React prompts for PAT; calls `POST /api/pat { pat: "github_pat_..." }`.**
   - Server validates against `/copilot_internal/user`, confirms login matches, sets quota, stores encrypted PAT, sets role to `"giver"`.
   - Responds with `{ ghe_login, quota_aiu: 4000 }`.
   - React updates profile display.

5. **React calls `POST /api/proxy-token`.**
   - Server generates and returns `{ id, token: "github_pat_11...", fingerprint }`.
   - React displays the token to the user: "Copy this and set `COPILOT_GITHUB_TOKEN=<token>`".

6. **React calls `GET /api/proxy-token`.**
   - Server responds with the list (no raw tokens, only IDs and fingerprints for identification).

7. **User sets `COPILOT_GITHUB_TOKEN=github_pat_11...` locally; runs copilot.**
   - Copilot proxy intercepts the request, resolves the token hash to the user, decrypts the giver's PAT, routes/bills as configured.

8. **(Optional) User calls `DELETE /api/proxy-token/:id`.**
   - Server revokes the token; future CLI requests with it fail.

---
