# Routing & Attribution Engine (#3) — Design

**Status:** Approved design, ready for implementation planning. Task 0
verification **complete** (see §6).
**Sub-project:** #3 of the CTC backend attack plan.
**Depends on:** the metering contract
(`docs/reference/metering-contract.md`), the accounting core #2
(`ctc/accounting`, `ctc/store`, `ctc/domain`), and the identity/PAT registry #1
(consumed via a stubbed seam here; #1 implements it for real).

---

## 1. Goal

When real Copilot CLI traffic flows through `proxy.py`, attribute each billable
request's actual credit cost to the correct CTC consumer, debit the correct
giver's bucket, and forward the request using that giver's real PAT — enforcing
credit caps per request so no consumer can overspend and no single giver is
unfairly drained.

This turns the proxy from a single-PAT pass-through into a multi-tenant
credit-routed data plane.

---

## 2. Key facts this design is built on (all verified against real traffic)

From the metering contract and the Task 0 probe (`tools/verify_token_rewrite.py`):

- **Credential model: the PAT is the bearer.** `copilot-api.example.ghe.com`
  accepts a GitHub PAT directly as `Authorization: Bearer <PAT>` and bills that
  PAT. There is **no `/copilot_internal/v2/token` exchange** in the no-login PAT
  flow (a fine-grained PAT actually gets `403` on that endpoint). `proxy.py`
  already swaps the bearer to `REAL_PAT` on every `copilot-api` call
  (`SWAP_HOSTS`, `proxy.py:131`). **So per-request giver routing is simply:
  swap the bearer to the *selected* giver's PAT instead of a fixed one.** No
  token broker, no token lifecycle, no refresh.
- **Billable calls:** `POST /chat/completions` (JSON) and `POST /v1/messages`
  (SSE) on `copilot-api.example.ghe.com`. Everything else is non-billable.
- **Per-request cost** is in the response body: `copilot_usage.total_nano_aiu`
  (integer nano-AIU). JSON → top-level object; SSE → final `message_delta` event.
  Free models report `0`; failed requests omit it. **Cost is known only at
  end-of-stream — after the response has been relayed.**
- **Credit unit:** 1 CTC credit = 1 nano-AIU.
- **Consumer identity:** each consumer drives the CLI with a **unique fake
  token** (`COPILOT_GITHUB_TOKEN`). The proxy sees that fake token on the
  inbound request *before* it swaps the bearer, so the fake token is the key
  that maps a request → consumer identity (the proxy already tags sessions by
  the fake token's first 12 chars).
- **The `/user` quota snapshot lags** (verified: flat across a billing call) — so
  it is for display/reconciliation only, never for per-request debits.

---

## 3. Credit model recap (the rules #3 enforces)

Consumption order per live request — **first non-empty bucket wins**:

| Consumer | Order | Never |
|---|---|---|
| Giver (PAT user) | `OWN` → `GRANT` | `POOL` |
| Non-PAT user | `GRANT` → `POOL` | `OWN` |

- **Pool** is non-PAT-only; the POOL giver is the one with the **most remaining
  pledge capacity** (`engine.givers_with_pool_capacity`).
- **Grants** are consumed by live traffic (a consumer can only have a grant once
  their normal channel was exhausted — marketplace is a last resort), and a grant
  forwards the **donor's** PAT.
- **Invariant:** the PAT forwarded as the bearer == the giver debited. The real
  Copilot quota is consumed on the forwarded PAT, so the ledger only stays true
  to reality if we debit that same giver.
- **No split:** a single request is charged in full to one giver/bucket, even if
  its actual cost exceeds that bucket's remaining (the accepted one-request
  overshoot). The next request re-evaluates and moves on once the bucket is ≤ 0.

### Cap enforcement is a pre-gate + post-hoc debit

Because cost is only known after streaming:
- **Pre-gate (before forwarding):** select the first bucket in order with
  remaining > 0 (for POOL, also requires a giver with capacity). If none qualify,
  **block before forwarding** (return `402 Payment Required` to the consumer).
- **Debit (after streaming):** record the actual `total_nano_aiu` against the
  selected giver/bucket. May overshoot by up to one request; tolerated.

Consequence — a consumer is blocked **only** when no eligible bucket has credit
(e.g. non-PAT: allowance exhausted *and* no pool giver has capacity), never
because one arbitrary giver ran dry. Giver re-selection happens **per request**.

---

## 4. Components

All new logic lives in the `ctc/` package; `proxy.py` stays thin and calls into it.

### 4.1 `ctc/metering/extract.py` — usage extractor
Pure function over response bytes → `int` nano-AIU.
- JSON body: parse, return `copilot_usage.total_nano_aiu` (or 0 if absent).
- SSE body: scan events for the **final `message_delta`** carrying `copilot_usage`;
  return its `total_nano_aiu` (or 0).
- Must operate as a **streaming scan to end-of-stream**, independent of
  `LOG_BODY_CAP` (the usage event is past the truncated log tee).
- **Directly unit-testable against `tests/fixtures/metering/exchanges.ndjson`**
  (known values: ex13=0, ex14=8262952500, ex19=1210027500).

### 4.2 `ctc/routing/` — attribution service
The orchestrator the proxy calls.
- `resolve_consumer(fake_token) -> ConsumerIdentity` (via the #1 seam): maps the
  inbound fake token to `{user_id, is_giver}`.
- `select_source(consumer, cycle) -> Source | None`: walks the consumption order
  against live engine balances + `givers_with_pool_capacity`; returns
  `{bucket, giver_id, grant_id?, pat}` for the first eligible bucket — including
  the **PAT to swap in as the bearer** — or `None` (→ the proxy blocks with 402).
- `debit(source, cost_nano_aiu, ts)`: records the actual consumption (see §5).

There is **no broker** — the PAT to forward comes straight from the #1 registry
for the selected giver; the proxy swaps it in directly.

### 4.3 `ctc/auth/` — identity/PAT seam (STUB here)
Interface #3 needs; #1 provides the real implementation (GHE OAuth + registry):
- `IdentityProvider.resolve(fake_token) -> ConsumerIdentity`
- `PatRegistry.pat_for(giver_id) -> str`, `PatRegistry.list_givers() -> list[str]`

This worktree ships an **in-memory/env-seeded stub** so #3 builds and tests
standalone. #1 swaps in the real provider behind the same interface.

---

## 5. Required change to the accounting core (#2) — flagged plan-conflict

`AccountingEngine.record_consumption` currently enforces hard caps and raises
`InsufficientCredit`, refusing to overspend. But #3's debit is **post-hoc**: the
spend already physically occurred on the forwarded PAT, and the design *accepts*
one-request overshoot. A debit that throws would lose the record and desync our
ledger from Copilot's reality.

**Add a record-actual path that bypasses the cap gate**, e.g.
`record_consumption(..., allow_overshoot: bool = False)` or a sibling
`record_actual_consumption(...)`. Semantics: still validates bucket/giver/grant
consistency and writes the event, but does **not** reject when `credits` exceeds
remaining. The pre-gate (§3) is the authorization point; this call records a fact.

This is the one change #3 requires outside its own package. It must land (with
tests) as part of #3's plan.

---

## 6. Task 0 verification — COMPLETE

`tools/verify_token_rewrite.py` (operator-run against real GHE, 2026-06-20)
confirmed the load-bearing assumptions:
- `copilot-api` accepts a PAT directly as bearer (`200`) — **no token exchange
  needed** (the original `/v2/token` plan was a dead end: fine-grained PATs `403`
  there, and the proxy never used it).
- A billable `/chat/completions` call billed a real, non-zero
  `copilot_usage.total_nano_aiu` (0.0037 AIU for a tiny `claude-haiku-4.5` call).
- The `/user` premium snapshot read flat across the call → confirms the lag; debit
  from the body, reconcile from the snapshot.

Because the bearer is just the PAT, "rewrite Authorization to a different giver's
credential per request" is exactly the swap the proxy already performs — so the
multi-tenant routing assumption is verified by construction. **No further
verification capture is required before implementation.**

---

## 7. Proxy integration (`proxy.py`)

Minimal, surgical changes to the existing request loop (`_serve`) and the
token-swap (`build_upstream_headers`, `proxy.py:124-133`):
- The swap is already per-request; today it always uses `REAL_PAT`. Make the
  PAT a **function of routing** for billable calls:
  - On a **billable** request: read the inbound fake token →
    `routing.resolve_consumer` → `routing.select_source`. If `None`, respond
    `402` without forwarding; else swap the bearer to `source.pat` and forward.
  - Relay the response as today (`_relay_response`), but tee the **full** stream
    through `extract.py` (streaming scan) to obtain `total_nano_aiu`.
  - After relay: if cost > 0, `routing.debit(source, cost, ts)`.
- On a **non-billable** GHE request (`/copilot_internal/user`, `/models`,
  `/mcp/*`, etc.): swap to a **bootstrap PAT** — any healthy giver (or a
  configured house PAT). These are not routed/attributed. Known cosmetic note:
  `/copilot_internal/user` then reflects the bootstrap giver's quota to the
  consumer; billing-irrelevant, accepted for MVP.

**Error handling:** the debit happens after the response is already sent, so it
must never break the consumer's response. A failed/slow debit is logged and left
to reconciliation (#5); it does not surface to the consumer. The pre-gate is the
only consumer-visible enforcement point.

---

## 8. Testing (real-binary bar)

- **`extract.py`** — unit tests over `tests/fixtures/metering/exchanges.ndjson`:
  JSON (ex13=0), SSE (ex14, ex19), 400-with-no-usage (→0), truncated/short streams.
- **selection/pre-gate** — unit tests over engine states: giver `OWN` exhausted →
  `GRANT`; non-PAT `GRANT` exhausted → `POOL`; POOL picks max-capacity giver;
  all-dry → block; giver depleted mid-cycle → next request reroutes.
- **engine overshoot** — unit test the new record-actual path (records past cap).
- **proxy routing** — test that a billable request swaps to the selected giver's
  PAT, a 402 is returned when no source qualifies, and the debit fires post-relay.
- **real-CLI smoke** — two consumers + ≥2 givers through the live proxy: drive
  real traffic, drain one giver, confirm the next request reroutes to another
  giver and that our debits reconcile against Copilot's `quota_snapshot`
  (per-giver). This is the acceptance gate.

---

## 9. Out of scope (later sub-projects)

- Control-plane REST API and marketplace request *creation* eligibility (#4).
- Cycle reset/archive (#5); leaderboard/history (#6).
- Real GHE OAuth identity + persistent PAT registry (#1 — stubbed here).

---

## 10. Open questions / risks

- **Consumer↔fake-token mapping** — assumes each consumer has a unique fake token
  the proxy can read inbound before swapping. The proxy already tags sessions by
  fake-token prefix, so this is low-risk; confirm the full fake token (not just a
  prefix) is the registry key.
- **Bootstrap giver health** — if the chosen bootstrap giver's PAT is invalid,
  session bootstrap fails for the consumer; needs a health check / fallback list.
- **Pool-giver concentration** — "most remaining pledge capacity" could repeatedly
  pick one giver within a cycle; acceptable for MVP, revisit if it skews real
  consumption unfairly (the snapshot reconciliation in #5 will surface it).
