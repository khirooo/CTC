# Routing & Attribution Engine (#3) — Design

**Status:** Implemented and live (`ctc/routing/attribution.py`,
`ctc/metering/live_quota.py`, proxy integration in `proxy.py`). This document is
the design of record, kept in sync with the shipped behavior; later refinements
(health-aware selection, the `LiveQuotaCache`, grant spill, and 402 failover) are
folded into the relevant sections. Task 0 verification **complete** (see §6).
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

> **Update (2026-07 pool redesign):** the non-PAT `POOL` auto-routing path
> described below was **removed**. Consumers no longer draw from the pool at spend
> time; the pool now reaches people only through the marketplace, as `source='pool'`
> **grants** created when a requester fills their own request (see
> `docs/guide/04-credits-and-accounting.md`). A pool fill is still attributed to the
> giver(s) with the most spare pledge, so at spend time everything is a `GRANT`.
> Net effect on the rules here: a non-PAT consumer's order is now just `GRANT`
> (no `POOL` bucket at selection time), and the per-consumer allowance is gone.
> The rest of this section is the original design, kept for history.

Consumption order per live request — **first non-empty bucket wins**:

| Consumer | Order | Never |
|---|---|---|
| Giver (PAT user) | `OWN` → `GRANT` | `POOL` |
| Non-PAT user | `GRANT` (→ `POOL`, removed) | `OWN` |

- **Pool** *(historical)* was non-PAT-only; the POOL giver was the one with the
  **most remaining pledge capacity** (`engine.givers_with_pool_capacity`). This
  auto-routing is gone; pledge capacity is now consumed by pool-fill grants.
- **Grants** are consumed by live traffic (a consumer can only have a grant once
  their normal channel was exhausted — marketplace is a last resort), and a grant
  forwards the **donor's** PAT.
- **Invariant:** the PAT forwarded as the bearer == the giver debited. The real
  Copilot quota is consumed on the forwarded PAT, so the ledger only stays true
  to reality if we debit that same giver.
- **Grant spill (one debit, multiple grants):** a debit on a GRANT source is
  spilled across the consumer's active grants in engine order — the selected
  grant first (clamped to its remaining), then the consumer's other active
  grants (each clamped) — so no single grant is driven below zero. Only the
  residual left after every grant is drained is recorded with overshoot, on the
  original source. **OWN and POOL sources do not spill:** they record a single
  event on the source bucket, absorbing any overshoot there. So a request can
  overshoot a non-grant bucket by up to its full cost (the accepted one-request
  overshoot); the next request re-evaluates and moves on once that bucket is ≤ 0.

### Cap enforcement is a pre-gate + post-hoc debit

Because cost is only known after streaming:
- **Pre-gate (before forwarding):** select the first bucket in order with
  remaining > 0 (for POOL, also requires a giver with capacity). The pre-gate is
  also **health-aware**: candidate givers whose *live* GitHub quota
  (`premium_interactions.remaining`, fetched via the `LiveQuotaCache`, §4.4) is
  ≤ 0 are skipped at the source. If none qualify, **block before forwarding**
  (return `402 Payment Required` to the consumer).
- **Failover on a real 402:** if the upstream PAT still returns a genuine GitHub
  `quota_exceeded` 402 despite the pre-gate (the live snapshot lags), the proxy
  reconciles that giver's ledger to its consumed floor, excludes it, re-selects
  the next bucket, and retries — bounded to one attempt per pre-checked giver
  plus the original source (§7).
- **Debit (after streaming):** record the actual `total_nano_aiu` against the
  selected giver/bucket (spilling across grants for GRANT sources, §3 bullet).
  May overshoot by up to one request; tolerated.

Consequence — a consumer is blocked **only** when no eligible bucket has credit
(e.g. non-PAT: no active grant remaining — post-redesign, a consumer with no
funded/pool-filled request has nothing to draw), never because one arbitrary giver
ran dry. Giver re-selection happens **per request**.

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
- `select_source(cycle_id, consumer, *, health=None, exclude=frozenset()) ->
  Source | None`: walks the consumption order against live engine balances +
  `givers_with_pool_capacity`; returns `{bucket, giver_id, grant_id?, pat}` for
  the first eligible bucket — including the **PAT to swap in as the bearer** — or
  `None` (→ the proxy blocks with 402). Two optional health/exclusion inputs:
  - `health`: `{giver_id -> live remaining | None}`. A bucket is skipped iff its
    giver's entry is **not None and ≤ 0** (the live-quota gate); `None`/absent
    means *unknown → allow*, so a missing or failed live fetch never blocks.
  - `exclude`: a set of keys to skip entirely, used by the 402-failover retry.
    GRANT sources are keyed by `grant_id`; OWN/POOL sources by `giver_id`.
- `debit(cycle_id, consumer, source, cost_nano_aiu, ts)`: records the actual
  consumption, spilling GRANT-source cost across active grants (see §3, §5).

There is **no broker** — the PAT to forward comes straight from the #1 registry
for the selected giver; the proxy swaps it in directly.

### 4.3 `ctc/auth/` — identity/PAT seam (STUB here)
Interface #3 needs; #1 provides the real implementation (GHE OAuth + registry):
- `IdentityProvider.resolve(fake_token) -> ConsumerIdentity`
- `PatRegistry.pat_for(giver_id) -> str`, `PatRegistry.list_givers() -> list[str]`

This worktree ships an **in-memory/env-seeded stub** so #3 builds and tests
standalone. #1 swaps in the real provider behind the same interface.

### 4.4 `ctc/metering/live_quota.py` — `LiveQuotaCache`
On-read + TTL cache (default 60s) of each giver's **live** GitHub
`premium_interactions` quota, feeding the pre-gate's health input. One instance
per process (the proxy and control plane each own one).
- `get(giver_id) -> {entitlement, remaining, reset_date} | None` /
  `remaining(giver_id) -> int | None`: returns the cached value, refetching via
  `GET /copilot_internal/user` (with that giver's PAT) when the entry is stale.
- **Failed fetches are never cached** (always retried) and return `None` so they
  never block the caller — matching `select_source`'s *unknown → allow* rule.
- `invalidate(giver_id)` drops an entry; `set_exhausted(giver_id)` pins
  `remaining = 0` so the 402-failover path can mark a giver dead without an
  extra round-trip.

---

## 5. Change to the accounting core (#2) — `allow_overshoot` (landed)

`AccountingEngine.record_consumption` normally enforces hard caps and refuses to
overspend. But #3's debit is **post-hoc**: the spend already physically occurred
on the forwarded PAT, and the design *accepts* one-request overshoot. A debit
that threw would lose the record and desync our ledger from Copilot's reality.

The implemented fix is the `allow_overshoot: bool = False` parameter on
`record_consumption`. With it set, the call still validates bucket/giver/grant
consistency and writes the event but does **not** reject when `credits` exceeds
remaining. The pre-gate (§3) is the authorization point; this call records a fact.

`debit` uses both modes: the per-grant spill records (`allow_overshoot=False`,
each clamped to that grant's `grant_remaining`) followed by a single residual
record on the original source with `allow_overshoot=True`. OWN/POOL sources skip
the spill loop and take only the overshoot-allowed residual record.

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
    `routing.resolve_consumer`. Before selecting, **pre-fetch each candidate
    giver's live quota** (`candidate_givers` → `LIVE_QUOTA.remaining`, §4.4) into
    a `health` map, then `routing.select_source(cycle.id, consumer,
    health=health)`. If `None`, respond without forwarding — `402` for no
    eligible credit, `401` for an unknown consumer token, `503` for no active
    cycle; else swap the bearer to `source.pat` and forward. (The live fetch
    awaits **before** `select_source`, preserving the no-await-inside-transaction
    invariant for the synchronous engine calls.)
  - **Failover on a real 402:** if the upstream returns a genuine GitHub
    `quota_exceeded` 402 (`is_quota_exceeded_402`), `reconcile_exhausted` drives
    that giver's ledger to its consumed floor and `LIVE_QUOTA.set_exhausted`s it,
    the giver/grant is added to `exclude`, and `select_source` re-runs for the
    next bucket. Bounded to `len(health)+1` attempts (one per pre-checked giver
    plus the original source); CTC's own 402 block (code `"ctc"`) is not retried.
  - Relay the response as today (`_relay_response`, `capture_full=billable`), but
    tee the **full** stream through `extract.py` (streaming scan) to obtain
    `total_nano_aiu`.
  - After relay: on a `200`, `routing.debit(cycle.id, consumer, source, cost,
    ts)` (a no-op when cost ≤ 0).
- On a **non-billable** GHE request (`/copilot_internal/user`, `/models`,
  `/mcp/*`, etc.): swap to a **bootstrap PAT** via `any_giver_pat()` (any stored
  giver PAT), gated on `should_swap` so non-GHE MITM hosts never receive a giver
  PAT. These are not routed/attributed. Known cosmetic note:
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
- **engine overshoot / grant spill** (`tests/test_overshoot_spill.py`) — a
  single GRANT-source debit spills across the consumer's active grants without
  driving any below zero; OWN/POOL sources still record a single overshoot event.
- **live-quota gate** — `select_source` skips a giver whose `health` entry is ≤ 0
  but allows one whose entry is `None` (unknown).
- **proxy routing & failover** (`tests/test_proxy_failover.py`) — a billable
  request swaps to the selected giver's PAT and debits post-relay; no source →
  402; a real `quota_exceeded` 402 reconciles + excludes the giver and reroutes
  to the next bucket, while CTC's own 402 is relayed straight through.
- **`reconcile_exhausted`** — drives a dead giver's quota to its consumed floor,
  marks the live cache exhausted, and never raises (swallows `set_quota` failures
  and a `None` cache).
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
