# Low-friction CLI onboarding — design

**Date:** 2026-06-21
**Status:** Approved (brainstorming complete)

## Problem

Onboarding a CLI user today fails and requires manual cert work. Running the
documented one-liner

    curl -fsSL https://<ctc-host>/install.sh | sh -s -- --token <token>

aborts with `curl: (60) SSL certificate problem: unable to get local issuer
certificate`. The CTC host is internal-only (no public DNS, so no Let's Encrypt)
and the fleet has no MDM (so the CA cannot be pushed centrally). Every cert in
the system is therefore self-signed and untrusted at first contact.

There are **two** untrusted certs, and the friction stacks:

1. **Caddy's TLS cert.** Caddy fronts the whole CTC host and terminates HTTPS
   (`Caddyfile:6`). With `CTC_DOMAIN=localhost` (the internal case) Caddy uses
   its own **internal CA** — untrusted — which is the `curl: (60)` failure. This
   cert is what `curl` and the browser see.
2. **The proxy MITM cert.** `gen-cert.sh:28` emits a single self-signed cert
   (`CN=copilot-proxy-ca`) that the proxy presents when intercepting
   `*.example.ghe.com`. It is served at `/ctc-ca.pem` (`Caddyfile:11-14` →
   `/certs/cert.pem`) and must land in the macOS System keychain because Copilot
   bundles its own Node and ignores `NODE_EXTRA_CA_CERTS`.

Because Caddy's cert is untrusted, **all three bootstrap fetches fail before any
trust exists** (chicken-and-egg):

- the `install.sh` one-liner itself,
- `install.sh` downloading the `ctc` binary (`cli/install.sh:27`),
- `ctc login` downloading `/ctc-ca.pem` (`cli/ctc:55`).

All three currently use plain `curl -fsSL` (no `-k`).

## Goal

Reduce the entire user experience to:

1. **One browser click** — first dashboard visit (to mint the per-user token)
   shows a cert warning; user clicks "proceed".
2. **One paste** — the install one-liner.
3. **One password** — the `sudo` that trusts the MITM CA in the System keychain.

No manual cert download, no `security add-trusted-cert`, no separate
`ctc login` step.

## Hard constraints (cannot be removed in this environment)

- **First dashboard visit warns.** The token is minted per-user behind session
  auth (`POST /api/proxy-token`), so the user must log into the dashboard in a
  browser *before* anything is trusted. That first visit warns. One click.
- **One `sudo`.** Copilot only honors the System keychain; trusting a cert there
  requires admin. No MDM = no way to pre-push it. `ctc login` already automates
  this into a single prompt (`cli/ctc:61`).
- **Bootstrap is trust-on-first-use.** With no public/MDM-trusted cert, the first
  `curl -k` fetch cannot be cryptographically verified. The fingerprint check
  below is advisory defense-in-depth, not enforcement.

## Design

### Decision 1 — One cert covers both proxy and dashboard

Reuse the existing self-signed proxy cert as Caddy's TLS cert, so the cert
`ctc login` trusts is the *same* cert the browser sees. After install the
dashboard stops warning.

- `scripts/gen-cert.sh`: add `DNS:${CTC_DOMAIN}` to the SAN list. The cert today
  covers `localhost` + the MITM hosts (`gen-cert.sh:30`); it must also be valid
  for the dashboard host. `CTC_DOMAIN` comes from `.env`. Keep
  `CN=copilot-proxy-ca`, single self-signed cert, no CA hierarchy.
- `Caddyfile`: replace Caddy's implicit internal-CA TLS with explicit
  `tls /certs/cert.pem /certs/key.pem` on the `{$CTC_DOMAIN}` site block.

Trade-off accepted: any cert regeneration forces every client to re-trust — but
that is already true today (`gen-cert.sh:7`), and the SANs change rarely.

### Decision 2 — Bootstrap over `-k`, with fingerprint defense-in-depth

All three bootstrap fetches switch to `curl -fsSLk`:

- Dashboard install one-liner →
  `curl -fsSLk https://{host}/install.sh | sh -s -- --token {token}`
  (`web/src/api/HttpCtcApi.ts` `installCommand`).
- `install.sh` fetching `/ctc` (`cli/install.sh:27`).
- `ctc login` fetching `/ctc-ca.pem` (`cli/ctc:55`).

Defense-in-depth (chosen posture: *TOFU + show fingerprint*):

- `ctc login` computes the SHA-256 of the downloaded CA and **prints it before
  the `sudo`** (e.g. `Trusting CA <sha256> — verify this matches the dashboard`).
- The dashboard **displays the same fingerprint** next to the install command so
  a careful user can compare. Most users just proceed.

This requires the control plane to expose the fingerprint:

- The control plane reads the CA cert (the same file Caddy serves at
  `/ctc-ca.pem`, i.e. `/certs/cert.pem`) and computes its SHA-256.
- `getCliCredentials` gains a `caFingerprint` field
  (`web/src/api/CtcApi.ts` contract + `HttpCtcApi.ts` impl), sourced from a
  control-plane field on the `POST /api/proxy-token` response (or a sibling
  endpoint). The control plane needs read access to the cert path; the plan
  resolves the exact mount/config (Caddy already mounts `/certs`).

### Decision 3 — Docs + tests

- Docs: `README.md`, `CLAUDE.md`, `cli/README.md` updated for the `-k` +
  fingerprint flow (the README one-liner currently omits `-k`).
- Tests: `cli/tests/test_install.sh` and `cli/tests/test_login.sh` assert the
  `-k` flag and the fingerprint print; regenerate test cert SANs in
  `tests/conftest.py` if the added SAN affects fixtures.

## Affected files

| File | Change |
|---|---|
| `scripts/gen-cert.sh` | Add `DNS:${CTC_DOMAIN}` SAN |
| `Caddyfile` | Explicit `tls /certs/cert.pem /certs/key.pem` |
| `cli/install.sh` | `-k` on the `/ctc` fetch |
| `cli/ctc` | `-k` on `/ctc-ca.pem` fetch; compute + print CA SHA-256 before sudo |
| `web/src/api/CtcApi.ts` | `caFingerprint` in `getCliCredentials` contract |
| `web/src/api/HttpCtcApi.ts` | `-k` in `installCommand`; surface `caFingerprint` |
| `web/src/screens/Profile/ProfileScreen.tsx` | Show fingerprint by install cmd |
| `web/src/screens/Onboarding/OnboardingScreen.tsx` | Show fingerprint by install cmd |
| control plane (`api_server.py` / `ctc/api/*`) | Compute CA SHA-256, expose it |
| `README.md`, `CLAUDE.md`, `cli/README.md` | Doc the `-k` + fingerprint flow |
| `cli/tests/test_install.sh`, `cli/tests/test_login.sh` | Assert `-k` + fingerprint |
| `tests/conftest.py` | Regenerate fixture cert SANs if needed |

## Out of scope (YAGNI)

- Root CA hierarchy with per-service leaves (Decision 2 alt, not chosen).
- MDM cert push / public DNS / Let's Encrypt (ruled out by environment).
- Binary hash pinning — moot once the first fetch is itself unauthenticated.

## Verification

Per the project's real-binary validation preference, validate end-to-end against
a running stack (Caddy + control plane + proxy) on `CTC_DOMAIN=localhost`:

1. Fresh machine/keychain: dashboard loads with one warning → proceed → copy
   one-liner.
2. Paste one-liner: installs with a single `sudo` prompt; `ctc login` prints a
   fingerprint matching the dashboard.
3. `ctc` launches Copilot through the proxy; a subsequent dashboard visit shows
   **no** warning.
4. `cli/tests/run.sh` (stubbed) and the `cli/tests/smoke.sh` real-binary smoke
   pass.
