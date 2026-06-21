# Metering Contract (Copilot CLI ↔ GHE)

**Status:** Authoritative. Derived from real-traffic analysis of
`tests/fixtures/metering/exchanges.ndjson` (22 redacted exchanges captured by an
operator driving the real GitHub Copilot CLI through `proxy.py` with
`CTC_CAPTURE_DIR` set, 2026-06-20).

This is the answer to metering-spike sub-project #0: **where does Copilot expose
the per-request credit cost and a PAT's quota, and in what shape.** Sub-projects
#2 (accounting core) and #3 (routing/attribution) parse against this contract.

---

## 1. The billable currency: AIU ("AI Units")

Copilot meters a single quota called **`premium_interactions`**, and as of this
capture it is **token-priced** (`token_based_billing: true`), denominated in
**AIU (AI Units)**. The two other quotas (`chat`, `completions`) are
`entitlement: -1` (unlimited) and are **never charged** — they exist but do not
constrain anything.

Per-request cost is reported in **nano-AIU** (AIU × 10⁻⁹) as an **integer**.

### Canonical unit decision

> **1 CTC credit = 1 nano-AIU.**
> Human-facing "1 AIU" = `1_000_000_000` credits. A giver's monthly quota of
> 4000 AIU = `4_000_000_000_000` credits.

Rationale: Copilot's own per-request figure (`total_nano_aiu`) is already an
integer in nano-AIU, so storing credits as `int` nano-AIU is **exact, never
rounds, and never drifts** from Copilot's ledger. The accounting core (#2)
already stores all balances as `int`, so this is a unit *definition*, not a code
change. The display layer divides by 1e9 to show AIU.

---

## 2. Per-request credit cost

**Where:** the response **body** of every successful LLM call. Two endpoints, two
body shapes — both expose the same field.

| Endpoint | Host | Content-Type | Where `copilot_usage` lives |
|---|---|---|---|
| `POST /chat/completions` | `copilot-api.example.ghe.com` | `application/json` | top-level JSON object (sibling of `usage`) |
| `POST /v1/messages` | `copilot-api.example.ghe.com` | `text/event-stream` | the **final `message_delta` SSE event**, `data:` JSON |

**Field (authoritative):** `copilot_usage.total_nano_aiu` — integer, nano-AIU.

**Breakdown (verifiable):** `copilot_usage.token_details[]`, one entry per token
type (`input`, `cache_read`, `cache_write`, `output`), each:
```
{ "token_type": "...", "token_count": N, "cost_per_batch": C, "batch_size": B }
```
Per-type cost = `token_count × cost_per_batch ÷ batch_size` (nano-AIU). The sum
over all entries equals `total_nano_aiu` exactly — verified on every priced call.
**Do not re-derive from `token_details` for charging; read `total_nano_aiu`
directly.** The breakdown is for auditing/display only.

### Observed values (from the fixtures)

| ex | endpoint | model | `total_nano_aiu` | AIU |
|---|---|---|---|---|
| 13 | `/chat/completions` | `gpt-4o-mini-2024-07-18` | `0` | 0.00 (this call) |
| 14 | `/v1/messages` | `claude-sonnet-4-6` | `8262952500` | 8.26 |
| 19 | `/v1/messages` | `claude-sonnet-4-6` | `1210027500` | 1.21 |

ex19 reconciliation: input `3×330000` + cache_read `18725×33000` + cache_write
`409×412500` + output `256×1650000` = `1_210_027_500` ✓.

### Charging rules (derived)

- **A request priced `0` costs 0.** In this capture `gpt-4o-mini` returned
  `total_nano_aiu: 0`. This is GitHub's per-request price, **not** a guarantee
  that any model is always free (the same model can bill non-zero, and agent runs
  make many metered calls). A request that reports `0` doesn't draw the pool or a
  grant; one that reports non-zero does. (Maps to attack-plan: only priced AIU
  consumes credit.)
- **Failed requests do not charge.** The three `400`s (ex 16–18, invalid model
  name) carry **no** `copilot_usage` block. Charge only when the field is
  present. Treat absence as "no charge," not as an error.
- **The charge is the *realized* cost**, including cache economics (cache_write
  is expensive, cache_read is cheap) — we charge exactly what Copilot charges,
  not an estimate.

---

## 3. PAT quota (monthly entitlement)

**Where:** `GET /copilot_internal/user` on `api.example.ghe.com`, response body,
`quota_snapshots.premium_interactions`:

```json
{
  "quota_id": "premium_interactions",
  "entitlement": 4000,
  "remaining": 3830,
  "quota_remaining": 3830.0,
  "percent_remaining": 95.7,
  "unlimited": false,
  "token_based_billing": true,
  "overage_permitted": true,
  "overage_count": 0,
  "timestamp_utc": "2026-06-20T01:54:36.097Z"
}
```

- **Total monthly quota** = `entitlement` (here **4000 AIU** = 4e12 credits).
- **Remaining** = `quota_remaining` (float AIU) / `remaining` (int AIU).
- **Reset date** = top-level `quota_reset_date` (here `"2026-07-01"`) — the cycle
  boundary. `quota_reset_at: 0` inside the snapshot is not a usable timestamp;
  use `quota_reset_date`.
- **Overage:** `overage_permitted: true`, `overage_count: 0` — the PAT *can* go
  past entitlement (billed as overage). The CTC pledge is our own safety cap
  *below* this; we do not rely on Copilot to stop draws.

This is the endpoint the proxy reads when a **giver uploads a PAT** to learn that
giver's quota (attack-plan #1/#3). It must be **forwarded + PAT-swapped**, never
mocked (per `CLAUDE.md` — the CLI needs the real response for token exchange).

The `chat` and `completions` snapshots also appear here with `entitlement: -1,
unlimited: true` — ignore them for credit purposes.

---

## 4. The quota-snapshot HEADERS are NOT per-request attribution

Successful LLM calls also return three response headers:

```
x-quota-snapshot-premium_interactions: ent=4000&ov=0.0&ovPerm=true&rem=95.7&rst=2026-07-01T00%3A00%3A00Z&totRem=3830.1
x-quota-snapshot-chat:                 ent=-1&...&rem=100.0&...&totRem=-1
x-quota-snapshot-completions:          ent=-1&...&rem=100.0&...&totRem=-1
```

Fields (URL-encoded query-string form): `ent`=entitlement, `ov`=overage count,
`ovPerm`=overage permitted, `rem`=percent remaining, `rst`=reset timestamp,
`totRem`=total remaining (AIU).

**Critical finding:** `totRem=3830.1` was **identical on ex13, ex14, and ex19**
even though ex14 cost 8.26 AIU between them. The header is a **lagged / sampled
cycle snapshot**, not a post-charge balance.

**Consequences for #2/#3:**
- **Use `total_nano_aiu` (body) for per-request attribution.** It is
  self-contained and exact — no before/after quota diff is needed, which is
  essential for charging **concurrent requests on a shared PAT** correctly.
- Use the header / `/copilot_internal/user` snapshot only for **display and
  periodic reconciliation** of our internal ledger against Copilot's, never as
  the source of a debit.

---

## 5. Model price reference (display only)

`GET /models` (`copilot-api.example.ghe.com`) returns per-model metadata including
`billing.token_prices` (`input_price`, `output_price`, `cache_price`,
`cache_write_price`, `batch_size`, plus a `long_context` tier) and a coarse
`model_picker_price_category` (`high` / … ). Useful for showing users "what a
model costs" before they run it. **Not needed for metering** — the realized cost
is always in the response body. Treat as an optional UI enrichment.

The `400` on ex16 also enumerated the live model list (handy reference):
`gpt-4.1, claude-opus-4.6/4.7/4.8, claude-sonnet-4.6, claude-sonnet-4.5,
claude-opus-4.5, claude-haiku-4.5, gemini-3.1-pro-preview, gemini-3.5-flash,
gpt-5.x family, gpt-4o-mini, …`.

---

## 6. Attribution surface for #3 (proxy routing)

What #3 must do per request, derived from this contract:

1. Identify priced calls: `POST /chat/completions` and `POST /v1/messages` on
   `copilot-api.example.ghe.com`. All other MITM'd traffic is non-billable.
2. After relaying the response, extract `copilot_usage.total_nano_aiu`:
   - JSON body → parse the object, read the field.
   - SSE body → scan events for the **final `message_delta`** (the one carrying
     `copilot_usage`); its `data:` JSON holds the field.
3. If the field is absent (error, non-priced, free model returning 0 or nothing)
   → charge 0.
4. Attribute `total_nano_aiu` (nano-AIU = credits) to the identity behind the
   fake token and call the accounting core's `record_consumption`.

### Implication for the proxy streaming path (flagged for #3)

`_relay_response` currently streams SSE live to the client and **tees only the
first `LOG_BODY_CAP` bytes** into the log. The `copilot_usage` event is at the
**tail** of the stream. So #3 cannot reuse the truncated tee — it must observe
the **last** `message_delta` event as bytes flow (a small running "last-usage"
extractor over the SSE stream), independent of `LOG_BODY_CAP`. This does **not**
require buffering the whole body; it requires scanning to the end-of-stream
usage event. Capacity/latency neutral if implemented as a streaming scan.

---

## 7. Open questions / gaps

- **Non-streaming vs streaming `/chat/completions`.** The fixture's one success
  (ex13) was non-streaming JSON. Streaming `/chat/completions` (SSE) was not
  captured; by analogy with `/v1/messages` the usage should arrive in a trailing
  SSE event, but #3 should confirm against a real streaming completion.
- **Header lag bound unknown.** We know the `x-quota-snapshot` header lags; we do
  not know by how long or what triggers refresh. Reconciliation in #5 should
  treat our body-summed ledger as truth and the snapshot as eventually-consistent.
- **Overage behavior past entitlement** not observed (quota was 95.7% remaining).
  CTC's own pledge cap should make this moot, but #3/#5 should decide policy if a
  giver's real PAT enters overage.
- **`total_nano_aiu` for tool-call / multi-turn agent loops:** each HTTP call is
  charged independently (self-contained `copilot_usage`), so an agent turn that
  makes N model calls produces N charges — attribution is per-HTTP-call, which is
  the correct granularity.
