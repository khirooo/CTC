# Copilot CLI Token Proxy — Technical Design Document

**Status:** Working prototype
**Owner:** CTC maintainers
**Date:** 2026-06-19

> **New to CTC? Don't start here.** This document is the deep, proxy-only
> technical reference. For the gentle, layered tour of the *whole* system
> (in plain language, with diagrams), start at the **[Guide](docs/guide/00-overview.md)**
> — in particular [01 · The Proxy](docs/guide/01-the-proxy.md), which links back
> down here for the exhaustive handshake (§11) and the "don't touch" checklist.

---

## 1. Goal

Build a local HTTPS interception proxy that lets multiple users invoke the
**GitHub Copilot CLI** against **your GHE instance** (`example.ghe.com`) using **disposable
fake tokens**, while the **single real Personal Access Token (PAT)** never
leaves the operator's machine.

Discovery sub-goal (achieved): enumerate every endpoint Copilot CLI calls during
normal operation. That map (§4) now backs a multi-tenant mode — per-user fake
tokens, encrypted giver PATs, and per-request credit accounting — layered on top
of the same MITM core (see Layer 10 and the control plane in §9).

---

## 2. Architecture

```
┌─────────────────────────┐    fake PAT    ┌─────────────────┐   real PAT    ┌──────────────────┐
│ Terminal B              │ ──CONNECT──▶  │  proxy.py       │ ────────────▶ │ *.example.ghe.com   │
│  copilot CLI            │                │  (your laptop)  │                │  (GHE)           │
│  fake token in env      │ ◀─────────────│  port 8080      │ ◀─────────────│                  │
└─────────────────────────┘                └─────────────────┘                └──────────────────┘
                                                  │
                                                  │  (blind pass-through)
                                                  ▼
                                          api.github.com
                                          npmjs.org
                                          (anything non-GHE)
```

The proxy is a plain **asyncio TCP server** speaking HTTP `CONNECT` (the
standard `HTTPS_PROXY` interface). For each tunnel it decides:

- **GHE host?** → **MITM**: terminate TLS with a self-signed cert that
  impersonates the target, decrypt the inner HTTP, swap the fake token for the
  real PAT, re-encrypt, forward.
- **Anything else?** → **Blind tunnel**: shuttle bytes both ways without
  inspection. Works exactly like having no proxy at all.

---

## 3. Stack

| Component | Why |
|---|---|
| Python 3, asyncio | Single-file (`proxy.py`), no framework lock-in, native TLS MITM via `loop.start_tls` |
| aiohttp | Async upstream HTTP client for forwarded requests |
| Self-signed OpenSSL cert with multi-SAN | One cert covers all GHE hosts |
| pytest + pytest-asyncio | Dev test suite (`tests/`); not required to run the proxy |

We initially used FastAPI + uvicorn but had to switch — uvicorn only speaks
HTTP, not raw CONNECT tunnels.

`proxy.py` remains a **single file** — the test suite lives in `tests/` as a
separate dev artifact and is not imported by the proxy at runtime. Dev
dependencies are tracked in `requirements-dev.txt` and `pyproject.toml`.

---

## 4. Discovered Copilot CLI endpoint map

Confirmed by intercepting one `copilot` session against your GHE instance:

| Host | Path | Purpose | Proxy mode |
|---|---|---|---|
| `api.example.ghe.com` | `GET /copilot_internal/user` | Auth check | MITM + token swap |
| `api.example.ghe.com` | `POST /copilot_internal/v2/token` | **Not used in this flow.** No token-exchange call was observed in the real captures, and the operator probe (`tools/verify_token_rewrite.py`) confirmed `copilot-api.*` accepts the swapped PAT **directly** as `Bearer` and bills that PAT — no exchange needed (fine-grained PATs even `403` here). Listed only because earlier discovery assumed it. | n/a (not observed) |
| `api.example.ghe.com` | `GET /copilot_internal/managed_settings` | Org policy (404 on GHE) | MITM + token swap |
| `api.example.ghe.com` | `GET /copilot/mcp_registry` | MCP server list | MITM + token swap |
| `example.ghe.com` | `GET /.well-known/oauth-authorization-server/login/oauth` | OAuth discovery | MITM + token swap |
| `copilot-api.example.ghe.com` | `POST /agents/sessions` | Start chat session | MITM + token swap |
| `copilot-api.example.ghe.com` | `GET  /models` | List models (+ per-model price table, see §4.1) | MITM + token swap |
| `copilot-api.example.ghe.com` | `POST /mcp/readonly` | MCP tool registration | MITM + token swap |
| `copilot-api.example.ghe.com` | `POST /chat/completions` | **Billable LLM call** (OpenAI-shape, JSON or SSE). Carries per-request credit cost (§4.1) | MITM + token swap |
| `copilot-api.example.ghe.com` | `POST /v1/messages` | **Billable LLM call** (Anthropic-shape, SSE). Carries per-request credit cost (§4.1) | MITM + token swap |
| `copilot-api.example.ghe.com` | `POST /responses` | **Billable LLM call** (OpenAI Responses API, SSE). Carries per-request credit cost (§4.1) | MITM + token swap |
| `copilot-telemetry-service.example.ghe.com` | various | Telemetry | Blind tunnel |
| `api.github.com` | `GET /repos/github/copilot-cli/releases/latest` | Update check (no token) | MITM (logged) |
| `api.githubcopilot.com` | (unused in the GHE flow) | github.com SaaS Copilot | Blind tunnel |

### Critical detail: `Authorization` header format

- `api.example.ghe.com` (standard GHE REST API) → accepts both `Bearer` and `token`
- **`copilot-api.example.ghe.com` only accepts `Bearer <pat>`** — sending `token`
  returns `400 bad request: Authorization header is badly formatted`

The proxy uses `Bearer` universally for GHE hosts.

### Token validation quirk

Copilot CLI validates the **format** of `COPILOT_GITHUB_TOKEN` locally before
making any network call. A token that doesn't look like a real GitHub PAT
(roughly: starts with `github_pat_` or `gho_`, ~93 chars long) is rejected
with "must be logged in" — no traffic is generated. Fake tokens must therefore
look real, e.g.:

```
github_pat_FAKE11ABFAKEFAKEFAKEFAKE_proxysession01234567890abcdefghij...
```

### 4.1 Metering: where the credit cost & quota live (Copilot response format)

Discovered from real-traffic capture (`tests/fixtures/metering/exchanges.ndjson`,
2026-06-20). Full analysis + edge cases:
`docs/reference/metering-contract.md`. Summary of the response
format so it is recorded here for the future:

**Currency.** Copilot meters one quota, `premium_interactions`, token-priced in
**AIU (AI Units)**. `chat`/`completions` quotas are `entitlement: -1` (unlimited)
and never charged. **CTC stores credits as integer nano-AIU: 1 credit = 1 nano-AIU.**

**Per-request cost — in the RESPONSE BODY of billable calls** (`POST
/chat/completions`, `POST /v1/messages`, `POST /responses`). The billable set
lives in `ctc/contract.py` (`BILLABLE_PATHS`); the proxy's `is_billable()` reads
it directly, so adding a path there is the single point of change:

| Body shape | Content-Type | Location of cost |
|---|---|---|
| JSON | `application/json` | top-level `copilot_usage` object (sibling of `usage`) |
| SSE | `text/event-stream` | the **final `message_delta` event**'s `data:` JSON |

`/chat/completions` reports cost top-level (JSON) or in the final SSE event;
`/v1/messages` and `/responses` report it in the **final SSE `message_delta`
event** (`ctc/contract.py` `METERING_LOCATION`). The extractor
(`ctc/metering/extract.py` `extract_total_nano_aiu`) handles both shapes: for SSE
it scans to the **last** `data:` event carrying `copilot_usage` (robust to the
trailing `[DONE]` sentinel and to truncation).

- Authoritative field: **`copilot_usage.total_nano_aiu`** (integer nano-AIU).
- Breakdown (audit only): `copilot_usage.token_details[]`, each
  `{token_type, token_count, cost_per_batch, batch_size}`; per-type cost =
  `token_count × cost_per_batch ÷ batch_size`, and the sum equals
  `total_nano_aiu` exactly. **Charge `total_nano_aiu` directly; don't re-derive.**
- **A request can legitimately report `total_nano_aiu: 0`** (in our capture, a
  `gpt-4o-mini` `/chat/completions` call did). This is GitHub's per-request price,
  **not** a fixed "free models" category — the same model can bill non-zero
  another time, and an agent run makes many metered calls that add up. We charge
  exactly what each response reports. **Failed requests (4xx) carry no
  `copilot_usage`** → charge 0. Field present-and-0 = a real 0 charge; field
  absent = no charge (and, on a billable 200, a drift signal — see §14).
- Each HTTP call is self-contained — no before/after diff needed, so concurrent
  requests on a shared PAT attribute correctly.

**PAT quota — in `GET /copilot_internal/user` response body:**
`quota_snapshots.premium_interactions` → `entitlement` (total AIU, e.g. 4000),
`remaining`/`quota_remaining` (AIU left), `token_based_billing: true`; cycle reset
= top-level `quota_reset_date` (e.g. `2026-07-01`). This is what the proxy reads
when a giver uploads a PAT.

**Quota-snapshot HEADERS are NOT per-request truth.** Billable responses also
carry `x-quota-snapshot-premium_interactions: ent=…&rem=…&totRem=…&rst=…` (plus
`-chat`/`-completions`). `totRem` was **identical across consecutive priced
calls** → it is a lagged/sampled cycle snapshot. Use it for display/reconciliation
only; use the **body `total_nano_aiu`** for attribution/debits.

> **Streaming gotcha for attribution code:** the `copilot_usage` SSE event is at
> the **tail** of the stream, past `LOG_BODY_CAP`. The attribution path must scan
> the SSE stream to its final `message_delta`, not reuse the truncated log tee.
> `_relay_response` therefore takes a `capture_full` flag for billable requests
> that buffers the **whole** body (not just the `LOG_BODY_CAP` tee) so
> `extract_total_nano_aiu` sees the final event.

---

## 5. Design decisions

### 5.1 Selective MITM vs full MITM

Early attempts MITM'd everything. This broke `api.githubcopilot.com` (cert
issues, header mismatch) and caused noisy `npmjs.org` failures. **Selective
MITM** is the right granularity:

- We only need to inspect/modify traffic to **the hosts we care about** (the GHE hosts).
- Everything else is a TCP byte pump — equivalent to no proxy at all.

This also means non-GHE services (npm update checks, github.com OAuth pages)
keep working with their real upstream certs and credentials.

### 5.2 Per-terminal isolation

To avoid polluting the operator's normal gh CLI config, each test session uses:

```bash
tmp="$(mktemp -d)"
HOME="$tmp" XDG_CONFIG_HOME="$tmp/.config" \
XDG_STATE_HOME="$tmp/.local/state" XDG_CACHE_HOME="$tmp/.cache"
```

This gives the Copilot CLI a completely fresh state directory. Only the
current terminal is affected. Other terminals (and the operator's normal
github.com workflow) are untouched.

### 5.3 No `/etc/hosts` or `pfctl`

We considered DNS / firewall redirection (`/etc/hosts` + macOS `pfctl`) but
rejected it — too invasive, system-wide, requires `sudo`. The `HTTPS_PROXY`
env var achieves the same interception per-process with no system changes.

### 5.4 Why not mock `/copilot_internal/user`?

We tried mocking these endpoints to avoid hitting GHE entirely. But Copilot
CLI uses the real `user` response to decide it is entitled and how to proceed;
feed it a wrong/faked response and it changes behaviour (or aborts) in ways
that are fragile to reproduce. **Forwarding with PAT swap** is simpler and
always correct: the real PAT is valid for every endpoint we proxy, so GitHub
returns correct responses for free and we only have to swap one header.

**Note (corrected):** there is **no token-exchange step** in this flow. The
real captures contain no `/copilot_internal/v2/token` call, and the operator
probe (`tools/verify_token_rewrite.py`) confirmed `copilot-api.*` accepts the
swapped PAT **directly** as `Bearer` and bills that PAT. Copilot keeps using
its single token on every call; the proxy swaps it to the real PAT on each
outbound request. (Earlier drafts described a `v2/token` exchange whose response
Copilot "continues with" — that does not happen here.)

---

## 6. Operator setup

### 6.1 One-time

```bash
# 1. Generate cert covering every GHE host we MITM
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes \
  -subj "/CN=copilot-proxy-ca" \
  -addext "subjectAltName=DNS:localhost,DNS:api.example.ghe.com,DNS:example.ghe.com,DNS:copilot-api.example.ghe.com,DNS:api.github.com,DNS:github.com,DNS:api.githubcopilot.com,DNS:githubcopilot.com,DNS:api.localhost,IP:127.0.0.1"

# 2. Trust the cert (macOS)
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain cert.pem

# Linux alternative:
# sudo cp cert.pem /usr/local/share/ca-certificates/copilot-proxy.crt
# sudo update-ca-certificates

# 3. Install runtime dep
pip install aiohttp

# 3b. (Optional) install dev deps to run the test suite
pip install -r requirements-dev.txt
```

### 6.2 Run the proxy

```bash
REAL_GHE_HOST=api.example.ghe.com \
REAL_PAT=github_pat_yourRealPATHere \
python proxy.py
```

### 6.3 Client (any terminal, any teammate)

```bash
tmp="$(mktemp -d)"
HOME="$tmp" \
XDG_CONFIG_HOME="$tmp/.config" \
XDG_STATE_HOME="$tmp/.local/state" \
XDG_CACHE_HOME="$tmp/.cache" \
GITHUB_API_URL=https://example.ghe.com/api/v3 \
GH_HOST=example.ghe.com \
COPILOT_GITHUB_TOKEN=github_pat_FAKE_must_look_like_a_real_pat_with_correct_length... \
HTTPS_PROXY=http://localhost:8080 \
NODE_EXTRA_CA_CERTS="$PWD/cert.pem" \   # see trust note below — NOT sufficient for copilot alone
copilot
```

> **Cert trust (verified by the §11 real-CLI smoke):** the Copilot CLI bundles its
> **own Node runtime** and does **NOT** honor `NODE_EXTRA_CA_CERTS` (nor
> `NODE_TLS_REJECT_UNAUTHORIZED=0`) for its auth fetch — with only those set, copilot
> aborts the TLS handshake with `CERTIFICATE_UNKNOWN`. The trust that actually works is
> the **OS trust store**: run the §6.1 step 2 `security add-trusted-cert` (macOS System
> keychain). `NODE_EXTRA_CA_CERTS` still helps plain `node`/`gh` tooling, so keep it, but
> it is not the operative mechanism for `copilot`.

| Env var | Purpose |
|---|---|
| `HOME` + `XDG_*` | Isolated config — won't touch your normal gh CLI |
| `GITHUB_API_URL` / `GH_HOST` | Point Copilot at GHE (not github.com) |
| `COPILOT_GITHUB_TOKEN` | Fake session token (looks like a real PAT) |
| `HTTPS_PROXY` | Route HTTPS traffic through our proxy |
| `NODE_EXTRA_CA_CERTS` | Trust hint for plain node/gh — **copilot ignores it**; trust the cert via the System keychain (§6.1 step 2) instead |

#### Proxy-side env vars (operator)

| Env var | Default | Purpose |
|---|---|---|
| `CERT_FILE` | `cert.pem` | Path to proxy TLS cert |
| `KEY_FILE` | `key.pem` | Path to proxy TLS key |
| `REAL_GHE_HOST` | `api.example.ghe.com` | Real GHE hostname for upstream forwarding |
| `REAL_PAT` | _(required)_ | Real PAT swapped in for GHE requests |
| `PORT` | `8080` | Proxy listen port |
| `UPSTREAM_CA_BUNDLE` | _(unset)_ | Path to a CA bundle for verifying GHE's TLS cert (e.g. corporate CA); if unset, system CAs are used |
| `UPSTREAM_INSECURE` | _(unset / `0`)_ | Request to skip upstream cert verification. **On its own it does nothing** — verification stays ON and the proxy logs an ERROR — unless `UPSTREAM_INSECURE_CONFIRM` is also set. Disabling verification exposes the real PAT to an on-path attacker. |
| `UPSTREAM_INSECURE_CONFIRM` | _(unset / `0`)_ | Confirmation flag. Upstream TLS verification is disabled **only when both** `UPSTREAM_INSECURE` and this are truthy. |
| `CTC_RESTRICT_CONNECT` | _(unset / `0`)_ | Set to `1` when the proxy is reachable from an untrusted network: **both** CONNECT tunnels and direct (non-CONNECT) plain-HTTP proxy requests are then honored only for the GitHub/GHE/Copilot host set, closing the open-relay/SSRF path on both dispatch branches. Default off keeps VPN/localhost-only deployments unchanged. |
| `CTC_EXTRA_ALLOWED_HOSTS` | _(unset)_ | Comma-separated extra hostnames allowed through when `CTC_RESTRICT_CONNECT=1` (e.g. an internal Jira/Confluence host an MCP server needs). Case-insensitive, exact host match only (no wildcard/suffix). |
| `LOG_BODY_CAP` | `8192` | Maximum bytes buffered/logged per request or response body |
| `CTC_DB_PATH` | _(unset)_ | Shared SQLite path. Set (with `CTC_SECRET_KEY`) to enable **multi-tenant mode** (Layer 10): per-request attribution/metering/failover. Unset → legacy single-`REAL_PAT` mode. |
| `CTC_SECRET_KEY` | _(unset)_ | Key for decrypting stored giver PATs from the shared DB. Required alongside `CTC_DB_PATH` for multi-tenant mode. |
| `CTC_CAPTURE_DIR` | _(unset)_ | Metering spike: append token-redacted request/response exchanges for MITM'd hosts to `<dir>/exchanges.ndjson`. Off by default. |

> `GHE_DOMAIN` (default `example.ghe.com`) feeds `ctc/contract.py`, which derives
> `MITM_HOSTS`/`SWAP_HOSTS` and `BILLABLE_HOST`. Override it per deployment; the
> cert SANs must match (see `gen-cert.sh`).

### 6.4 Two ways to point Copilot at the proxy

The proxy code supports **two client configurations**. They differ only in what
`GH_HOST` is set to; the proxy ends up forwarding to `REAL_GHE_HOST` either way.

| Mode | Client sets | Copilot connects to | How the proxy handles it |
|---|---|---|---|
| **A — direct host (canonical, used above)** | `GH_HOST=example.ghe.com` | `api.example.ghe.com:443` (Copilot auto-prepends `api.`) | Host is in `MITM_HOSTS` → MITM'd and swapped directly. No remap needed. |
| **B — localhost alias** | `GH_HOST=localhost` | `api.localhost` | `_LOCALHOST_ALIASES` remaps the upstream to `REAL_GHE_HOST` (see §11, Layer 6). |

**Mode A is canonical** — it's the one verified end-to-end and shown in §6.3.
Mode B exists because Copilot's auto-`api.` prepend plus a `localhost` host lands
on `api.localhost`, which the proxy explicitly remaps. Keep the cert SANs and
host sets covering both so either mode works.

---

## 7. Security model

| Threat | Mitigation |
|---|---|
| Fake token leaking the real PAT | Real PAT only lives in proxy process env. It is **never logged** and **never sent to the client**. |
| Proxy MITMing arbitrary internet traffic | Selective MITM — only GHE hosts. Everything else is byte-passthrough. |
| Cert trust pollution | Self-signed CA is added to keychain, scoped by `subjectAltName` to only the listed hostnames. |
| Other terminals affected | Per-shell `HTTPS_PROXY` + `HOME=$tmp` ensures complete isolation. |
| Session attribution | Proxy logs `session=<first 12 chars of fake token>` so we can audit who did what. |

---

## 8. What this does NOT solve (future work)

1. **Multi-tenancy at scale** — the single-PAT mode is still the default, but a
   multi-tenant mode now exists (Layer 10): the control plane (`api_server.py`)
   issues per-user fake tokens mapped to encrypted giver PATs in a shared SQLite
   DB, and the proxy attributes/meters/debits per request with health-aware giver
   selection and 402 failover. Remaining at-scale gaps:
   - Per-token rate limiting (quota is enforced via the credit ledger, not rate)
   - Horizontal scale-out (the shared sqlite connection assumes one proxy process)
2. **High availability** — single process on `localhost`. Production would
   need a real deployment, possibly behind a load balancer.
3. **TLS to clients via real CA** — currently a self-signed cert needs manual
   trust. Production would use a corporate-trusted CA or distribute the cert
   via MDM.
4. **Audit log persistence** — logs go to stdout only.
5. **Telemetry interception** — `copilot-telemetry-service.example.ghe.com` is
   currently blind-tunneled. We could MITM it to scrub or redirect telemetry.

Previously listed as future work, now resolved:

- **Streaming interception** — `_relay_response` streams large/SSE/chunked
  responses live via `Transfer-Encoding: chunked` re-framing, with a bounded
  `LOG_BODY_CAP`-byte tee into the log. Small responses with a numeric
  `Content-Length ≤ LOG_BODY_CAP` are buffered and logged in full. ✅
- **Upstream TLS verification** — `build_upstream_ssl_context` now verifies
  GHE's cert by default (system CAs). Use `UPSTREAM_CA_BUNDLE` for a
  corporate CA, or opt out with **both** `UPSTREAM_INSECURE=1` **and**
  `UPSTREAM_INSECURE_CONFIRM=1` (a bare `UPSTREAM_INSECURE` keeps verification ON
  and logs an ERROR — disabling it exposes the real PAT to an on-path attacker). ✅

---

## 9. Files

| File | Purpose |
|---|---|
| `proxy.py` | The entire proxy implementation (~800 lines: MITM + multi-tenant attribution/metering/failover) |
| `cert.pem`, `key.pem` | Self-signed TLS cert + key |
| `ctc/contract.py` | Single source of truth for host sets, `BILLABLE_PATHS`, the metering field/location, and auth scheme |
| `ctc/routing/attribution.py` | `select_source` (bucket selection + health/exclude gate) and `debit` (grant-spill) |
| `ctc/metering/extract.py` | `extract_total_nano_aiu` — per-request charge from JSON/SSE bodies |
| `ctc/metering/live_quota.py` | `LiveQuotaCache` — on-read + TTL live giver-quota cache for the health gate / failover |
| `api_server.py`, `ctc/auth/`, `ctc/store/` | Control plane: GitLab-OAuth login, sessions, encrypted PAT storage, proxy-token issuance (shares the proxy's DB) |
| `TDD.md` | This document |

---

## 10. Key learnings from the discovery process

1. **`gh copilot` is not `gh` at all.** It's a Node binary (`@github/copilot`)
   invoked via a VS Code shim. It ignores `gh`-specific env vars like
   `GH_DEBUG`, `GH_TOKEN` etc. — it reads its own `COPILOT_GITHUB_TOKEN`,
   `GITHUB_API_URL`, `HTTPS_PROXY`.
2. **`gh` and `copilot` use different code paths.** `gh auth status` calls
   `/api/v3/` on `GH_HOST`. `copilot` calls `/copilot_internal/*` on
   `api.<GH_HOST>` (auto-prepends `api.`).
3. **GHE Copilot uses a different API surface than github.com Copilot.**
   github.com → `api.githubcopilot.com`. Your GHE instance → `copilot-api.example.ghe.com`.
   Different hosts, same-ish paths.
4. **Cert SANs matter a lot.** Every new host discovered required cert
   regeneration. Final cert has 10 SANs.
5. **Authorization header format is endpoint-specific.** Even within the same
   `*.example.ghe.com` domain, different sub-services accept different prefixes.

---

## 11. The handshake, layer by layer

> **Read this before changing proxy behavior.** This is the contract that makes
> Copilot CLI accept us as the real backend. It traces one `copilot` session
> from launch to a working chat and names every layer we deliberately bend.
> Each layer is tagged **🔒 LOAD-BEARING** (changing it breaks the connection) or
> **⚙️ mechanism** (supporting plumbing). For load-bearing layers, the
> *failure signature* tells you how it breaks, and the *update signal* tells you
> what a future Copilot release might change.

### 11.0 One session, end to end

```
copilot CLI                         proxy.py                         *.example.ghe.com
  │
  │ (1) start with isolated HOME + COPILOT_GITHUB_TOKEN + HTTPS_PROXY
  │ (2) validate token *shape* locally — no network if it looks fake-fake
  │
  │ (3) CONNECT api.example.ghe.com:443 ───────▶│
  │                                          │ (4) host ∈ MITM_HOSTS?  yes → MITM
  │ ◀──────── 200 Connection established ─────│
  │ (5) TLS ClientHello ─────────────────────▶│  server cert = our self-signed
  │ ◀──── cert (trusted via NODE_EXTRA_CA) ───│  cert; SAN must list this host
  │ ===================== TLS up =============│
  │ (7) GET /copilot_internal/user ──────────▶│ strip fake tok, set Bearer PAT ─▶│
  │ ◀──────────────────── 200 user json ──────│◀─────────────────────────────────│
  │   (no token-exchange step — Copilot keeps using its same token throughout;   │
  │    the proxy swaps it to the real PAT on every call, incl. copilot-api)      │
  │ (8) POST /agents/sessions  (copilot-api) ─▶│ swap ──────────▶ copilot-api.example.ghe.com
  │                                            │
  │ telemetry / npm / github.com OAuth ───────▶│ (4-blind) byte-pump, untouched ─▶ real upstreams
```

Steps map to the layers below.

### Layer 1 — Client launch & state isolation · 🔒 LOAD-BEARING
- **What:** each session runs with a throwaway `HOME=$tmp` + `XDG_*`, plus
  `GH_HOST` / `GITHUB_API_URL` / `COPILOT_GITHUB_TOKEN` / `HTTPS_PROXY` /
  `NODE_EXTRA_CA_CERTS`. Copilot reads its **own** env (it ignores `gh`'s
  `GH_TOKEN`, `GH_DEBUG`, etc. — see §10.1).
- **Why load-bearing:** a real cached login under `~/.config` would let Copilot
  authenticate normally and never present our fake token. The fresh `HOME` is
  what forces it down the proxy path.
- **Failure signature:** requests never appear, or appear with the operator's
  *real* token instead of the fake one.
- **Update signal:** Copilot reads a new env var / config file for its
  token or host → the fake token stops being picked up.

### Layer 2 — Token-shape gate · 🔒 LOAD-BEARING (client-side, before any network)
- **What:** Copilot validates the *format* of `COPILOT_GITHUB_TOKEN` locally
  before making a single call. It must look like a real PAT (`github_pat_…` or
  `gho_…`, ~93 chars). See §4 "Token validation quirk."
- **Why load-bearing:** a too-short / wrong-prefix fake token is rejected with
  "must be logged in" and **zero traffic is generated** — there's nothing for
  the proxy to intercept.
- **Failure signature:** `copilot` exits with a login error and the proxy log
  stays empty (no `[CONNECT]` line).
- **Update signal:** Copilot tightens token validation (e.g. checksums, new
  prefixes) → previously-working fake tokens get rejected with no traffic.

### Layer 3 — Traffic capture via `CONNECT` · 🔒 LOAD-BEARING
- **What:** `HTTPS_PROXY` makes Copilot send a raw HTTP `CONNECT host:443` to us
  for every HTTPS target. `_dispatch` reads that first line and decides what to do.
- **Why load-bearing:** this is the only interception point. It's also **why the
  proxy is hand-rolled asyncio and not FastAPI/uvicorn** — uvicorn speaks HTTP
  but cannot handle a raw `CONNECT` tunnel (§3).
- **Failure signature:** no `[CONNECT]` lines at all → `HTTPS_PROXY` isn't set
  in the client env, or points at the wrong port.
- **Update signal:** Copilot (or its Node runtime) stops honoring `HTTPS_PROXY`,
  or switches to a transport that ignores it (e.g. a bundled QUIC/HTTP-3 client).

### Layer 4 — Selective MITM vs blind tunnel · 🔒 LOAD-BEARING
- **What:** `do_mitm = host in MITM_HOSTS`. Listed hosts get decrypted; **every
  other host is a blind byte-pump** (`_blind_tunnel`) that behaves exactly like
  no proxy (§5.1).
- **Why load-bearing in both directions:**
  - Hosts we *must* inspect (`*.example.ghe.com`, `api.github.com`,
    `api.localhost`, `localhost`) must be in `MITM_HOSTS` or we can't swap their
    token. The exact set is `contract.EXPECTED_MITM_HOSTS`.
  - Hosts we *must not* touch (`api.githubcopilot.com`, `npmjs.org`,
    `github.com` OAuth) must stay out — MITMing them broke cert validation and
    OAuth in early attempts.
- **Failure signature:** a GHE host being blind-tunneled → token never swapped
  (401/403). A non-GHE host being MITM'd → cert/OAuth errors for that service.
- **Update signal:** Copilot starts calling a **new host** for auth or
  completions. It'll show up in `[CONNECT]` logs tagged `[tunnel]`; promote it
  to `MITM_HOSTS` (and add a cert SAN, and `SWAP_HOSTS` if it needs the swap).

### Layer 5 — TLS impersonation + client trust · 🔒 LOAD-BEARING
- **What:** for MITM hosts we reply `200 Connection established`, then
  `loop.start_tls(transport, protocol, _server_ssl, server_side=True)` to become
  the TLS server using our self-signed cert. The server-side context pins ALPN to
  `http/1.1`. For copilot to accept the cert it must be in the **OS trust store**
  (macOS System keychain — §6.1 step 2). **The real-CLI smoke (§11 testing notes)
  proved copilot bundles its own Node runtime and ignores `NODE_EXTRA_CA_CERTS` and
  `NODE_TLS_REJECT_UNAUTHORIZED=0`** — with only those set it aborts the handshake with
  `CERTIFICATE_UNKNOWN`. Keychain trust is the operative mechanism.
- **Why load-bearing:** two independent requirements — (a) the cert must be trusted by
  the client's runtime (keychain, per above), and (b) **the cert's `subjectAltName` must
  list every host in `MITM_HOSTS`.** Miss either and the TLS handshake dies before any HTTP.
- **Failure signature:** `[CONNECT] TLS MITM failed (<host>): CERTIFICATE_UNKNOWN` →
  cert not trusted by the client (keychain step skipped); `ERR_TLS_CERT_ALTNAME_INVALID`
  / SAN error → a `MITM_HOSTS` host missing from the cert SANs.
- **Update signal:** Copilot enforces cert pinning, or changes which trust store its
  bundled runtime reads → MITM breaks for all hosts at once even though SANs are correct.
- **Don't:** narrow `verify_mode`/`check_hostname` on the *client-facing* context
  expecting it to help — the trust decision is the client's, set by its env vars.

### Layer 6 — `api.localhost` remap · ⚙️ mechanism (only Mode B; see §6.4)
- **What:** Copilot auto-prepends `api.` to `GH_HOST`. With `GH_HOST=localhost`
  it connects to `api.localhost`, which isn't a real upstream. `decide_route`
  remaps the `_LOCALHOST_ALIASES` set (`api.localhost`, `localhost`, `127.0.0.1`)
  to `REAL_GHE_HOST:443` for both the CONNECT decision and the `_serve` forward.
- **Why it matters:** without the remap, `api.localhost` resolves to the proxy
  itself → loop / 502. Mode A (`GH_HOST=example.ghe.com`, canonical) never hits this
  because it connects straight to the real GHE hostname.
- **Failure signature:** 502s, or the proxy trying to forward to `api.localhost`.
- **Update signal:** Copilot changes how it derives the API host from `GH_HOST`
  (stops prepending `api.`, or uses a separate `GITHUB_API_URL` host).

### Layer 7 — Request rewrite: header surgery + token swap · 🔒 LOAD-BEARING
- **What:** `_serve` rebuilds the outbound headers:
  - drops hop-by-hop headers (`host`, `authorization`, `content-length`,
    `transfer-encoding`, `connection`, `proxy-connection`) and recomputes
    `content-length` / `host` for the upstream;
  - **token swap:** if `upstream_host ∈ SWAP_HOSTS` and a PAT is available →
    `Authorization: Bearer <PAT>`. Otherwise the client's original token is
    passed through (this is why `api.github.com` keeps the client token).
  - **which PAT:** in legacy single-PAT mode it's `REAL_PAT`. In multi-tenant
    mode (`ATTRIBUTION` enabled — see Layer 10) the PAT is *selected per request*:
    for a **billable** call, `select_source()` picks the giver PAT backing the
    consumer's credit (OWN → GRANT → POOL); for non-billable GHE calls
    (`/copilot_internal/*`) the proxy borrows `any_giver_pat()` so token
    validation still has a real PAT upstream (no credit consumed).
- **Why load-bearing:**
  - `SWAP_HOSTS` is the swap gate — a GHE host missing from it gets the *fake*
    token forwarded (401). A non-GHE host wrongly added to it leaks the PAT.
  - **`Bearer` is mandatory for `copilot-api.example.ghe.com`** — `token <pat>`
    returns `400 Authorization header is badly formatted` (§4). The proxy
    normalizes all GHE hosts to `Bearer`.
- **Failure signature:** `400 …badly formatted` (wrong prefix) /
  `401`/`403` (swap not applied or PAT invalid).
- **Update signal:** a new GHE sub-service requires a different auth scheme, or
  copilot-api starts accepting only a copilot-token (not the PAT) on some path.

### Layer 8 — `/copilot_internal/*`: forward, never mock · 🔒 LOAD-BEARING
- **What:** `/copilot_internal/user` (and `managed_settings`) are forwarded for
  real **with the PAT swap**, not mocked. There is **no token-exchange step**:
  the real captures show no `/copilot_internal/v2/token` call, and the operator
  probe (`tools/verify_token_rewrite.py`) confirmed `copilot-api.*` accepts the
  swapped PAT **directly** as `Bearer` and bills that PAT. Copilot uses one token
  on every call; the proxy swaps it to the real PAT each time.
- **Why load-bearing:** Copilot reads the real `user` response to decide it is
  entitled and how to proceed; mocking it risks Copilot misbehaving or aborting.
  The PAT is valid for these endpoints, so forwarding is both simpler and correct.
- **Failure signature:** auth/login succeeds but chat/completions fail on
  `copilot-api.*` (401/403) — usually the host missing from `SWAP_HOSTS`/SAN, or
  the swap not reaching `copilot-api.*`.
- **Update signal:** Copilot starts requiring a real `v2/token` exchange (a new
  field/flow it depends on) → chat breaks while login works. If that happens,
  re-run discovery; today the direct-PAT path is what works.

### Layer 9 — Upstream forward & response relay · ⚙️ mechanism
- **What:** one shared `aiohttp` session forwards to `https://<upstream_host><path>`
  with a verified upstream SSL context (default: system CAs; see `UPSTREAM_CA_BUNDLE`
  / `UPSTREAM_INSECURE` in §6.3) and `allow_redirects=False`. Timeouts are
  `sock_connect=10 s`, `sock_read=120 s` (no `total`, so long streams survive).
  Timeout errors return `504 Gateway Timeout`; other forward errors return
  `502 Bad Gateway`.
- **Response relay (`_relay_response`):** strips
  `transfer-encoding`/`content-encoding`/`content-length`/`connection` from
  upstream headers. Then:
  - **Buffered path:** if `Content-Length` is a numeric value ≤ `LOG_BODY_CAP`,
    the full body is read, logged, and returned with a recomputed `Content-Length`.
  - **Streaming path:** everything else (SSE, chunked, no/large length) is
    re-framed as `Transfer-Encoding: chunked` and forwarded live chunk-by-chunk.
    Only the first `LOG_BODY_CAP` bytes are tee'd into the log.
- **Why it matters:** the header strip prevents double-encoding; the streaming path
  keeps SSE and large completions flowing without buffering the entire body in memory.

### Layer 10 — Attribution, metering & failover (multi-tenant mode) · ⚙️ mechanism
> Active only when `ATTRIBUTION` is built — i.e. `CTC_DB_PATH` + `CTC_SECRET_KEY`
> are set (or the legacy `CTC_IDENTITY_JSON`/`CTC_PATS_JSON` stub). With none of
> these the proxy stays in legacy single-PAT mode and this layer is a no-op. The
> control plane (`api_server.py`) and proxy share the same SQLite DB; the proxy
> reads encrypted PATs + the consumer registry via `ctc/auth/registry.py`.

- **What:** for a **billable** request (`is_billable()` — `POST` to
  `copilot-api.*` on a path in `contract.BILLABLE_PATHS`) the proxy:
  1. resolves the consumer from the fake token (`resolve_consumer`),
  2. runs a **live-quota health gate** — for each candidate giver (the consumer
     if a giver, plus every donor of an active grant) it reads the giver's real
     GitHub `premium_interactions.remaining` via `LiveQuotaCache`
     (`ctc/metering/live_quota.py`; on-read + 60 s TTL, failed fetches never
     cached, never block),
  3. calls `select_source(cycle, consumer, health=…)` to pick the first eligible
     bucket (OWN → GRANT → POOL), skipping any giver the health map marks dead
     (`remaining ≤ 0`),
  4. forwards with that giver's PAT, then on a `200` extracts
     `total_nano_aiu` and **debits** the source. Grant-source debits **spill
     across the consumer's active grants** (each clamped to its remaining) before
     any residual overshoots the original bucket; OWN/POOL debits record once with
     overshoot allowed (`ctc/routing/attribution.py` `debit`).
- **Pre-gate block:** if `select_source` returns `None` the proxy blocks **before
  forwarding** and renders a readable error body in the endpoint's native envelope
  (`_ctc_block_response`): `503` (no active cycle), `401` (unknown consumer
  token), or `402` (no eligible credit). The old empty-body 402 showed the user
  nothing; now the Copilot CLI surfaces the CTC message like a real quota error.
- **Failover on 402:** if an upstream giver returns a *real* GitHub quota 402
  (`error.code == "quota_exceeded"`, distinguished from CTC's own `code: "ctc"`
  402 by `is_quota_exceeded_402`), the proxy reconciles that giver's ledger down
  to its consumed floor (`reconcile_exhausted`), marks the live cache exhausted,
  excludes it, re-selects the next bucket, and retries — capped at one attempt per
  pre-checked giver plus the initial source. A non-retriable 402 (or no next
  bucket) is relayed to the client as-is.
- **Non-billable / failed requests:** non-billable calls make exactly one attempt
  and consume no credit. A billable response that isn't `200` carries no
  `copilot_usage` → charge 0. Debit failures are logged, never surfaced (the
  response was already relayed).
- **Why it's a mechanism, not load-bearing:** none of this is needed for Copilot
  to *work* — it's the CTC credit-accounting overlay. A bug here mis-bills or
  over/under-blocks, but the proxy/Copilot handshake (Layers 1–9) is unaffected.

### Quick "don't touch" checklist

When editing `proxy.py`, the three host sets must stay coherent — they are the
spine of every routing decision:

- `MITM_HOSTS` — decrypt + inspect. **Add a host here ⇒ add a cert SAN (§6.1).**
- `SWAP_HOSTS` — subset that gets the `REAL_PAT` swap. Adding a non-GHE host
  here leaks the PAT; omitting a GHE host forwards the fake token.
- `_LOCALHOST_ALIASES` — remapped to `REAL_GHE_HOST` (Mode B only).

`REAL_PAT` must never be logged or returned to the client (auth header is masked;
sessions are tagged by the first 12 chars of the *fake* token).

---

## 12. Copilot-update runbook

When a Copilot CLI update breaks the proxy, the symptom points straight at a
layer in §11. Run a session with the proxy and read the log top to bottom.

### 12.1 Symptom → layer → fix

| Symptom in client / proxy log | Most likely layer | Fix |
|---|---|---|
| `copilot` errors "must be logged in", **proxy log empty** (no `[CONNECT]`) | L2 token shape, or L1 env not set | Make the fake token look like a real PAT; confirm `COPILOT_GITHUB_TOKEN` + `HTTPS_PROXY` are exported |
| No `[CONNECT]` lines but Copilot does reach the network | L3 capture | `HTTPS_PROXY` unset / wrong port, or Copilot ignoring it (new transport) |
| `[CONNECT] TLS MITM failed (<host>)`; client cert error | L5 cert / SAN | Regenerate cert with a SAN for `<host>` (§6.1); confirm `NODE_EXTRA_CA_CERTS` |
| New host appears as `[CONNECT] … [tunnel]` that should be inspected | L4 routing | Add it to `MITM_HOSTS` (+ SAN, + `SWAP_HOSTS` if it needs the swap) |
| `400 Authorization header is badly formatted` | L7 Bearer norm | Ensure the host is normalized to `Bearer` (it is for `SWAP_HOSTS`) |
| `401`/`403` on `/copilot_internal/*` | L7 swap / PAT | Host missing from `SWAP_HOSTS`, or `REAL_PAT` invalid/expired/under-scoped |
| Login works but **chat/completions fail** on `copilot-api.*` | L8 forward/swap | Confirm `copilot-api.example.ghe.com` is in `SWAP_HOSTS`, MITM'd, swapped to `Bearer` PAT, and has a SAN. (No token-exchange to fix — the PAT is sent directly.) |
| Client sees `502 Bad Gateway` | L9 forward / L6 remap | `REAL_GHE_HOST` wrong/unreachable, or `api.localhost` not remapped |
| A GHE host forwards the **fake** token | L7 `SWAP_HOSTS` | Add the host to `SWAP_HOSTS` |
| `402` with body `{"error":{…"code":"ctc"…}}` | L10 pre-gate | Expected CTC block — consumer is out of credit (or `401`/`503` variants: unknown token / no cycle). Not a proxy bug; check the user's quota/grants. |
| `402` with body `error.code == "quota_exceeded"`, repeated across givers | L10 failover | All candidate givers' real GitHub quotas are exhausted; failover ran out of buckets. Add/refresh giver PATs or wait for `quota_reset_date`. |
| `404` on `/copilot_internal/managed_settings` | — (expected) | Normal on GHE (§4); not a failure |

### 12.2 Re-running discovery after an update

The proxy doubles as the discovery tool. To re-map Copilot after an update:

1. Run the proxy and start a fresh isolated session (§6.3).
2. Watch `[CONNECT]` lines for **new hosts**. Anything tagged `[tunnel]` that
   looks Copilot-related is a candidate for `MITM_HOSTS` (+ SAN).
3. Watch `[→ REQUEST]` / `[→ COPILOT]` lines for **new paths** and
   `[← RESPONSE]` for new auth schemes or token contracts.
4. Update the §4 endpoint map, the three host sets in `proxy.py`, and the cert
   SANs together — they must stay in sync.

---

## 13. Testing

The `tests/` directory contains a pytest suite that exercises `proxy.py` without
running a real GHE instance. All tests run against a local TLS mock server
(`conftest.py` stands up an `aiohttp.web` server with a generated cert, then
patches proxy module globals to point at it).

### 13.1 Install dev dependencies

```bash
pip install -r requirements-dev.txt
# installs: aiohttp, pytest, pytest-asyncio
```

`pyproject.toml` sets `asyncio_mode = "auto"` so async test functions run
without explicit `@pytest.mark.asyncio` decorators.

### 13.2 Run the suite

```bash
pytest tests/ -v
```

All tests must pass before merging changes to `proxy.py`.

### 13.3 What the tests cover

| File | Coverage |
|---|---|
| `test_body.py` | `decode_body` — gzip/deflate/br/zstd decoding, JSON pretty-print, truncation |
| `test_hostsets.py` | `should_swap` host membership; absence of deleted `MOCK_USER` constants |
| `test_routing.py` | `decide_route` — MITM vs tunnel decisions, localhost alias remap |
| `test_request_body.py` | `assemble_request_body` — `Content-Length` and `Transfer-Encoding: chunked` paths |
| `test_ssl.py` | `build_upstream_ssl_context` — default verification on, `UPSTREAM_CA_BUNDLE` load, `UPSTREAM_INSECURE=1` opt-out |
| `test_headers.py` | `build_upstream_headers` — hop-by-hop stripping, token swap for GHE hosts, pass-through for non-GHE |
| `test_e2e.py` | End-to-end through a live proxy against the mock TLS upstream: token swap, blind tunnel, SSE streaming, chunked request body, verified TLS handshake |
| `test_contract.py` | `ctc/contract.py` — host sets, `BILLABLE_PATHS` (incl. `/responses`), `is_github_ish` |
| `test_extract.py` | `extract_total_nano_aiu` — JSON top-level + SSE final-event extraction, `[DONE]`/truncation robustness |
| `test_billable_routing.py` / `test_proxy_routing.py` | `is_billable` host/method/path gate; multi-tenant PAT selection in `_serve` |
| `test_attribution.py` / `test_attribution_health.py` / `test_attribution_modes.py` | `select_source` bucket order, health/exclude gate, participants/pool modes |
| `test_overshoot_spill.py` | `debit` grant-spill across active grants + residual overshoot |
| `test_live_quota_cache.py` | `LiveQuotaCache` — on-read fetch, TTL, no-cache-on-failure, `set_exhausted` |
| `test_proxy_failover.py` | 402 failover: `is_quota_exceeded_402`, `reconcile_exhausted`, giver retry + buffered relay |
| `test_proxy_db_registry.py` | DB-backed `_build_attribution` path (`CTC_DB_PATH` + `CTC_SECRET_KEY`) |
| `test_canary_verdict.py` | `ctc.canary.evaluate` + `write_status` + `load_exchanges` — pure verdict logic over fixture exchanges |
| `test_canary_cli.py` | `tools.canary.should_skip` — version-skip helper; no quota spent |

> The control plane (`api_server.py`, `ctc/auth/`, `ctc/store/`, `ctc/accounting/`)
> has its own large test set (OAuth login, sessions, onboarding, accounting,
> admin routes, etc.) — out of scope for this proxy-focused table; run the full
> suite with `pytest tests/ -v`.

## 14. Drift detection canary

`tools/canary.py` is a daily runnable that stands up an isolated proxy, drives one
real paid Copilot completion through it, evaluates the contract, and writes a status
file. The full live path (keychain trust, proxy spawn, driving the real `copilot`
binary) is an **operator-only step** — it cannot run in the unit suite because it
spends quota and mutates the System keychain.

### 14.1 Daily cron

```cron
# /etc/cron.d/ctc-canary  (or launchd plist equivalent)
0 6 * * * ctc-operator CANARY_PAT=<see vault> CANARY_MODEL=<a-paid-copilot-model> \
    python3 -m tools.canary --if-version-changed \
    --status ~/.local/state/ctc/canary-status.json
```

`--if-version-changed` skips the run (and quota spend) when the installed
`copilot --version` matches the version recorded in the previous status file.

### 14.2 Required environment variables (operator)

| Variable | Purpose |
|---|---|
| `CANARY_PAT` | Dedicated canary PAT — NEVER the production PAT. Never logged. |
| `CANARY_MODEL` | A **paid** model name confirmed PAID on your Copilot deployment — set this to a model you have verified bills non-zero AIU (use `<a-paid-copilot-model>` as a placeholder; never use a free model or the canary's non-zero-AIU assertion becomes meaningless). Free models cost 0 nano-AIU, which is indistinguishable from the silent billing break the canary exists to catch. The canary will exit 2 if this is unset. |

### 14.3 Sudoers rule (scoped)

The canary calls `sudo security add-trusted-cert` and `sudo security delete-certificate`
to trust/untrust the throwaway cert in the System keychain. Grant only those two
commands to the cron user:

```sudoers
# /etc/sudoers.d/ctc-canary
ctc-operator ALL=(root) NOPASSWD: /usr/bin/security add-trusted-cert *
ctc-operator ALL=(root) NOPASSWD: /usr/bin/security delete-certificate *
```

### 14.4 Status file

Written to `~/.local/state/ctc/canary-status.json` by default (override with
`--status`). Schema:

```json
{
  "ran_at": "2026-06-20T06:00:01Z",
  "verdict": "pass",
  "copilot_version": "1.42.0",
  "extracted_nano_aiu": 12345678,
  "failures": []
}
```

A non-empty `failures` list means the contract drifted; each entry has `assertion`
and `detail` fields. Exit code is 1 on any failure, 2 on setup error (missing PAT
or model), 0 on pass or skip.

### 14.5 Manual live-run verification (operator step)

Run once after setup to confirm the full pipeline works end-to-end:

```bash
CANARY_PAT=<real canary token> CANARY_MODEL=<a-paid-copilot-model> \
    python3 -m tools.canary --status /tmp/canary-test-status.json
cat /tmp/canary-test-status.json
```

Expected: `"verdict": "pass"` with `extracted_nano_aiu > 0`. Paste the resulting
JSON into the deployment commit message for audit trail.
