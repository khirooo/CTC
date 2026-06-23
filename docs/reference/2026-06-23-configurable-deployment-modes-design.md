# Configurable deployment modes — design

**Date:** 2026-06-23
**Status:** Approved (brainstorm), pending spec review
**Author:** brainstorming session

## Summary

CTC currently assumes one deployment shape: the web app/API served over HTTPS,
GitHub Enterprise OAuth login, a giver/consumer marketplace, and an automatic
shared credit pool (pledging + per-consumer free allowance). This spec makes that
shape **configurable along four orthogonal axes** so CTC can also run as: a website
served over plain HTTP (no TLS cert for the control plane), email magic-link login
(for users with no GHE account), a license-holders-only marketplace, and with the
automatic shared pool turned off (credits move only by explicit request→grant).

**The CLI/proxy data path is out of scope and unchanged** — clients keep
`HTTPS_PROXY`, the proxy keeps MITM with the self-signed cert, and users keep
trusting that cert in the keychain. Axis 1 concerns *only the website* (control
plane + web UI), not the proxy.

The four axes are independent; any combination is valid.

| # | Axis | Values | Configured via | Applies |
|---|------|--------|----------------|---------|
| 1 | Web transport (website only) | `https` / `http` | env `CTC_WEB_TRANSPORT` | boot (control plane + Caddy) |
| 2 | Auth mode | `ghe_oauth` / `email` | env `CTC_AUTH_MODE` | boot (control plane) |
| 3 | Participants | `givers_and_consumers` / `givers_only` | **live admin toggle** (DB setting) | runtime |
| 4 | Shared pool | `on` / `off` | **live admin toggle** (DB setting) | runtime |

### Shipped defaults (fresh deploy)

The shipped defaults target the "license-holders trade credits, website on plain
HTTP" deployment: **`CTC_AUTH_MODE=email`, `CTC_WEB_TRANSPORT=http`,
`participants_mode=givers_only`, `shared_pool_enabled=off`.**

> **Upgrade caveat (must appear in release notes + docs):** these defaults change
> behavior for an existing deployment that upgrades without setting env vars. An
> operator who wants today's behavior must explicitly set
> `CTC_AUTH_MODE=ghe_oauth`, `CTC_WEB_TRANSPORT=https`, and turn the two admin
> toggles to `givers_and_consumers` / pool `on`.
>
> **Security note:** `CTC_WEB_TRANSPORT=http` serves session cookies and magic-link
> URLs over plaintext. Use it only behind a trusted network (VPN/internal LAN).
> Documented prominently in `.env.example` and the deploy guide.

## Design principles

- **One enforcement seam per axis.** Each axis is gated in exactly one place so a
  reader can understand it in isolation and a change can't leak across axes.
- **Reuse existing machinery.** The live toggles extend the existing
  `EFFECTIVE_KEYS` / `EffectiveConfig` / admin-`PATCH` settings path
  (`ctc/domain/settings.py`, `ctc/store/settings_store.py`,
  `ctc/api/admin_routes.py`). The email provider sits beside `GheOAuth` behind the
  same "produce a session" seam. The marketplace request→grant engine is unchanged.
- **Fail fast on bad config.** Invalid env enum values refuse to start (mirrors how
  the control plane refuses to start without `CTC_SECRET_KEY`).
- **No schema-breaking migrations.** New settings are rows in the existing
  `settings` table; the email identity reuses the existing `users.ghe_login`
  column as the identity string. Only additive tables (`magic_links`) are new.

---

## Axis 1 — Web transport, website only (`CTC_WEB_TRANSPORT=https|http`)

**Goal:** let the website (control plane API + web UI) be served over plain HTTP for
deployments that have no TLS cert for the web host (internal/VPN). **The proxy data
path is untouched** — this axis does not affect how the CLI talks to the proxy.

**`https` (legacy):** unchanged. Caddy terminates TLS for the web host (`Caddyfile`),
`CTC_APP_ORIGIN` is `https://…`, and session/state cookies are set `Secure`
(`api_server.py` already keys the cookie `secure` flag off
`app_origin.startswith("https")`).

**`http` (new):** the website is served over plain `http://`. Caddy serves the host
without TLS, `CTC_APP_ORIGIN` is `http://…`, and the cookie `Secure` flag is
correspondingly off (the existing `app_origin.startswith("https")` logic already
handles this — no new cookie code). The control plane already listens as plain HTTP
behind Caddy, so the control-plane process itself is unchanged.

**Seams:**
- `Caddyfile`: a transport-conditional site block (TLS vs `http://` / `auto_https
  off`). Driven by `CTC_WEB_TRANSPORT` at deploy time.
- `CTC_APP_ORIGIN` scheme set to match (`http://` in http mode). No code change in
  `api_server.py` — the `Secure`-cookie behavior follows the origin scheme already.
- `cli/ctc` install/launcher: any `https://$CTC_HOST` URL the install step hits
  (e.g. the install command, CA download) uses the configured scheme. **The proxy
  envvars (`HTTPS_PROXY`, `NODE_EXTRA_CA_CERTS`, cert download/keychain trust) are
  unchanged** — only website-facing URLs follow the scheme.

**No validation spike** — serving the website over HTTP is standard; there is no
dependency on Copilot CLI behavior.

---

## Axis 2 — Auth mode (`CTC_AUTH_MODE=ghe_oauth|email`)

**Goal:** let users with no GHE account sign in.

**Provider seam.** A new `EmailMagicLink` provider lives in `ctc/auth/` beside
`GheOAuth`. Both converge on the same downstream seam: upsert a user and call
`sessions.create(user_id, now)`. `make_app` selects which login routes to register
based on `CTC_AUTH_MODE`. Sessions, `AuthRegistry`, proxy-token issuance, and the
accounting engine are all auth-mode-agnostic and unchanged.

**Email magic-link flow:**
1. `POST /auth/email` `{email}` → validate email shape → mint a single-use token:
   random id stored in a new `magic_links` table `(id, email, expires_at,
   consumed_at)`, plus an HMAC signature using the existing `CTC_SECRET_KEY`.
   Always respond `204` (do not reveal whether the email is known).
2. Send the link `<CTC_APP_ORIGIN>/auth/magic?token=<id>.<sig>` via the configured
   `EmailSender`.
3. `GET /auth/magic?token=…` → verify signature, not expired, not consumed → mark
   consumed → upsert user (identity string = the **email**, stored in
   `users.ghe_login`) with role `consumer` (or `giver` per onboarding) → create
   session cookie → redirect to `CTC_APP_ORIGIN`.

**Token policy:** short TTL (default 15 min, constant), single-use (consumed on
first successful verify), HMAC-signed so the DB row id alone is not a bearer token.

**EmailSender seam** (`ctc/auth/email_sender.py`):
- `EmailSender` protocol: `send_magic_link(email, link) -> None`.
- `SmtpEmailSender` — stdlib `smtplib` over `CTC_SMTP_HOST/PORT/USER/PASS/FROM`
  (+ `CTC_SMTP_STARTTLS`). Production.
- `ConsoleEmailSender` — logs the link to the server log. Dev/local; lets the flow
  be built and tested with no SMTP infra.
- Selected by `CTC_EMAIL_BACKEND=smtp|console` (default `console`).

**Admin allowlist note:** in `email` mode `CTC_ADMINS` contains **email addresses**
(it is matched against `users.ghe_login`, which now holds the email). Documented in
`.env.example` and the deploy guide.

---

## Axis 3 — Participants (`participants_mode`, live: `givers_and_consumers|givers_only`)

**Goal:** a deployment where everyone holds a license (PAT); no free-riding
consumers.

**Storage:** new key in the `settings` table, surfaced through `EffectiveConfig` /
`effective_view` / `validate_patch` and the admin `PATCH /api/admin/settings`
endpoint. The **default** follows the existing `default_pledge_pct` pattern: a code
default in `ctc/domain/config.py` (`givers_only`), optionally seeded at first boot
via env (`CTC_PARTICIPANTS_MODE`), and overridden live by the admin toggle (DB row).
Precedence: DB setting → env seed → code default.

**Enforcement seam — `AttributionService.select_source`** (`ctc/routing/attribution.py`):
- `givers_only`: if the resolved `ConsumerIdentity` is **not** a giver (no PAT on
  file), return `None`. The proxy already maps `None` → **HTTP 402 Payment
  Required** (`proxy.py:418-428`). The web app translates 402 / the `/api/me`
  flags into an "add a license to continue" prompt.
- `givers_and_consumers`: unchanged (consumers allowed via GRANT→POOL).

**Flip behavior:** turning `givers_only` ON blocks existing consumers
**immediately** — their proxy tokens still resolve, but `select_source` denies, so
the next request 402s. No data migration, no token revocation; fully reversible by
toggling back.

**Onboarding/UI:** in `givers_only`, the web app requires a PAT before showing a
usable proxy token, and hides consumer-only affordances.

---

## Axis 4 — Shared pool (`shared_pool_enabled`, live, default **off**)

**Goal:** the automatic pool (pledging + per-consumer free allowance) is confusing;
make it optional. When off, credits move **only** via the explicit marketplace
(request → grant), which already exists and funds each grant from the donor's own
`personal_remaining`.

**Storage:** new boolean key in the `settings` table, same machinery as axis 3.
Code default **off** (`ctc/domain/config.py`), seedable via env `CTC_SHARED_POOL`,
overridden live by the admin toggle. Precedence: DB setting → env seed → code
default.

**Enforcement seam — `AttributionService.select_source`:**
- pool **off**: skip the `POOL` branch entirely. Givers resolve OWN→GRANT;
  consumers resolve GRANT-only (no allowance draw). `free_allowance` is not
  consulted.
- pool **on**: today's behavior (GRANT→POOL for consumers, allowance enforced).

**Pledge handling when off:**
- `default_pledge_pct` is treated as `0` at onboarding (no auto-pledge); the
  pledge/pool widgets are hidden in the web app.
- The engine's `set_pledge`/`set_quota` remain callable but are not exercised by
  the UI; no engine change required.

**Marketplace unchanged:** `create_request` / `fund_request` / `Bucket.GRANT`
consumption work identically in both pool states. This is the only cross-user
credit path when the pool is off.

---

## Cross-cutting changes

### `/api/me`
Add `auth_mode`, `web_transport`, `participants_mode`, `shared_pool_enabled` to the
payload so the web app renders the correct UI (hide pledge/pool widgets when pool
off; show "add a license" gating when givers_only; marketplace always shown).

### Admin settings endpoint
`GET /api/admin/settings` returns all four axes. The two **live** settings
(`participants_mode`, `shared_pool_enabled`) are editable via `PATCH`. The two
**boot** values (`auth_mode`, `web_transport`) are reported read-only with a
`source: "env"` marker and a "set in .env — restart to change" hint. `validate_patch`
rejects attempts to PATCH the env-sourced keys and validates the two new enum/bool
settings.

### Startup validation
`build_from_env` validates `CTC_AUTH_MODE`, `CTC_WEB_TRANSPORT`, `CTC_EMAIL_BACKEND`
against their allowed values and refuses to start on an invalid value (clear error
message), consistent with the existing `CTC_SECRET_KEY` / required-env behavior.

### Web app
Read mode flags from `/api/me`; conditionally render: email-login screen vs
OAuth-login screen (axis 2 affects the pre-login screen too — the web app must know
the auth mode before login, so expose it via an unauthenticated `GET /api/config`
returning `{auth_mode}`), pledge/pool widgets (axis 4), add-a-license gating
(axis 3).

### Docs / `.env.example`
Document the four knobs, the email-mode admin-allowlist semantics, the SMTP vars,
the shipped-defaults upgrade caveat, and a "deployment shapes" table (legacy vs
license-holders-trade-credits).

---

## Data model changes

- `settings` table: two new logical keys (`participants_mode`,
  `shared_pool_enabled`). No schema change (key/value table already exists).
- `magic_links` table (new, email mode only):
  `(id TEXT PK, email TEXT, expires_at INTEGER, consumed_at INTEGER NULL,
  created_at INTEGER)`. Additive; created in `init_db`.
- `users`: no change. `ghe_login` holds the email string in email mode.

---

## Error handling

| Condition | Behavior |
|---|---|
| Invalid `CTC_AUTH_MODE`/`CTC_WEB_TRANSPORT`/`CTC_EMAIL_BACKEND` | Refuse to start, clear message |
| Magic link expired / consumed / bad signature | `400` "link invalid or expired" |
| `POST /auth/email` for unknown email | `204` (no enumeration) |
| SMTP send failure | log error; still `204` to client (avoid leaking deliverability); operator sees the log |
| `givers_only` + non-PAT user request | proxy `402` → web "add a license" |
| pool off + consumer with no grant | `select_source` → `None` → proxy `402` |
| PATCH of an env-sourced setting key | `400` "set via environment; restart to change" |

---

## Testing

**Unit (pytest):**
- `select_source`: pool off (POOL branch skipped, GRANT still works); givers_only
  (non-giver → None); all four on/off combinations of axes 3×4.
- `validate_patch`: accepts `participants_mode`/`shared_pool_enabled` valid values,
  rejects invalid values and rejects env-sourced keys.
- Magic link: mint → verify happy path; expired; already-consumed; tampered
  signature.
- Email-mode `auth_callback`/`/auth/magic`: upserts user with email identity,
  creates session; admin allowlist matches email.
- `EmailSender`: `ConsoleEmailSender` logs link; `SmtpEmailSender` builds the
  expected message (mock smtplib).
- Startup validation: bad enum → raises.
- `/api/me` exposes the four flags; `/api/config` exposes `auth_mode`.
- Cookie `Secure` flag follows `CTC_WEB_TRANSPORT` (off in http mode, on in https).

**Manual smoke (operator, documented in plan):**
- Axis 1: load the web app over `http://` (http mode), sign in, confirm session
  cookie works without `Secure`. Proxy/CLI flow is unchanged, so no proxy smoke
  needed for this axis.
- Email magic-link end-to-end with `ConsoleEmailSender`.

---

## Out of scope

- Live (no-restart) switching of auth mode or web transport (explicitly chosen as
  boot-time env config).
- **Any change to the CLI/proxy data path** — the proxy keeps HTTPS-MITM with the
  self-signed cert and keychain trust. Axis 1 is website-only.
- Password auth, admin-pre-provisioned accounts (magic link chosen).
- Auto-rotation / load-balancing of PATs (explicit peer grants chosen as the
  cross-user model).
- Any change to the metering contract or the upstream-TLS path.
