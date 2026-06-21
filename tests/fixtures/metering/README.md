# Metering fixtures

`exchanges.ndjson` — 22 **token-redacted** request/response exchanges captured by
an operator driving the real GitHub Copilot CLI through `proxy.py` with
`CTC_CAPTURE_DIR` set (2026-06-20). Produced by `ctc/metering/capture.py`; every
`authorization`/token field is `***REDACTED***` (verified — no token-shaped
strings present). Non-secret identifiers (GitHub logins, a hashed
`analytics_tracking_id`) remain to preserve realism.

Each line is one JSON record: `{method, host, path, status, request_headers,
response_headers, response_content_type, body_kind, body}`. Only the **response**
body is captured (not the request body). Some `body` values contain raw newlines
(SSE), so a strict NDJSON line reader fails — decode with a tolerant
`json.JSONDecoder(strict=False).raw_decode` loop over the whole file.

## What the session did
A single Copilot CLI chat turn ("how to generate an SSL certificate on macOS"):
auth/bootstrap calls, MCP registration, then the billable LLM calls.

## Key exchanges for metering (see `docs/reference/metering-contract.md`)

| ex | call | note |
|----|------|------|
| 0  | `GET /copilot_internal/user` | quota source: `quota_snapshots.premium_interactions` (ent=4000, rem=3830) |
| 6  | `GET /models` | per-model `billing.token_prices` (display only) |
| 13 | `POST /chat/completions` (JSON) | `gpt-4o-mini`, `total_nano_aiu: 0` (free model) |
| 14 | `POST /v1/messages` (SSE) | `claude-sonnet-4-6`, `total_nano_aiu: 8262952500` |
| 16–18 | `POST /chat/completions` → 400 | invalid model; **no** `copilot_usage` (no charge) |
| 19 | `POST /v1/messages` (SSE) | `claude-sonnet-4-6`, `total_nano_aiu: 1210027500` |

The per-request cost (`copilot_usage.total_nano_aiu`) lives in the response body;
for SSE it is in the **final `message_delta` event**.
