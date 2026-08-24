"""Single source of truth for CTC's reverse-engineered contract with the
GitHub Copilot CLI. Pure data + pure helpers — no I/O, no logging.

Every entry here is a non-contractual behavior observed in traffic (see
TDD.md §4, §6, §11 and docs/reference/metering-contract.md).
A Copilot CLI update can change any of it; the sentinel and canary watch for
exactly that.
"""
from __future__ import annotations

import json
import os

# Your GitHub Enterprise domain. Override per deployment via the GHE_DOMAIN env
# var (e.g. GHE_DOMAIN=your.ghe.example for production). The default is a neutral
# placeholder so the codebase carries no organization-specific host name.
GHE_DOMAIN: str = os.environ.get("GHE_DOMAIN", "example.ghe.com")

# Hosts we decrypt + inspect. SANs on the proxy cert MUST cover every entry.
EXPECTED_MITM_HOSTS: set[str] = {
    f"api.{GHE_DOMAIN}",
    GHE_DOMAIN,
    f"copilot-api.{GHE_DOMAIN}",
    "api.github.com",
    "api.localhost",
    "localhost",
}

# Subset that gets the REAL_PAT swap (normalized to Bearer).
SWAP_HOSTS: set[str] = {
    f"api.{GHE_DOMAIN}",
    GHE_DOMAIN,
    f"copilot-api.{GHE_DOMAIN}",
}

BILLABLE_HOST: str = f"copilot-api.{GHE_DOMAIN}"
BILLABLE_PATHS: set[str] = {"/chat/completions", "/v1/messages", "/responses"}
BILLABLE_METHOD: str = "POST"

# ---------------------------------------------------------------------------
# Native Anthropic Claude Code -> Copilot bridge (ctc/routing/anthropic_bridge.py)
# ---------------------------------------------------------------------------
# The native Anthropic Claude Code CLI points ANTHROPIC_BASE_URL at CTC and POSTs
# the Anthropic Messages API to copilot-api's /v1/messages. Copilot's Anthropic
# endpoint accepts a *narrower* schema than the public Anthropic API, so requests
# from Claude Code must be normalized on this one path before the swapped PAT will
# be accepted (attribution/metering/swap are untouched — this only rewrites the
# outbound request). The Copilot CLI's own /chat/completions path is unaffected.
ANTHROPIC_BRIDGE_PATH: str = "/v1/messages"

# 1. Client identity. copilot-api rejects a Personal Access Token unless the
#    request carries the CLI's client-identity headers ("Personal Access Tokens
#    are not supported for this endpoint" 400 otherwise). The native Copilot CLI
#    already sends these; Claude Code does not, so we inject them.
#    These default to the current proven client-identity values but are each
#    env-overridable: if GitHub deprecates an old Copilot client version, bridge
#    traffic would otherwise silently 400 with no field-patch path. Override via
#    CTC_COPILOT_INTEGRATION_ID / CTC_COPILOT_EDITOR_VERSION / CTC_COPILOT_USER_AGENT.
COPILOT_API_IDENTITY_HEADERS: dict[str, str] = {
    "copilot-integration-id": os.environ.get(
        "CTC_COPILOT_INTEGRATION_ID", "copilot-developer-cli"),
    "editor-version": os.environ.get(
        "CTC_COPILOT_EDITOR_VERSION", "copilot/1.0.63"),
    "user-agent": os.environ.get(
        "CTC_COPILOT_USER_AGENT", "GitHubCopilotChat/copilot/1.0.63"),
}

# 2. anthropic-beta allowlist. Copilot 400s on beta values it does not know
#    (observed: advisor-tool-2026-03-01, mid-conversation-system-2026-04-07). The
#    real Copilot CLI sends none, and prompt caching is GA via cache_control in the
#    body (needs no beta). Default EMPTY = drop the header entirely. Extend via
#    CTC_ANTHROPIC_BETA_ALLOW (comma list) only once a value is proven accepted.
ANTHROPIC_BETA_ALLOWLIST: frozenset[str] = frozenset(
    b.strip() for b in os.environ.get("CTC_ANTHROPIC_BETA_ALLOW", "").split(",") if b.strip()
)

# 3. Top-level body fields to strip. output_config carries reasoning-effort /
#    structured-output settings that Copilot rejects ("model does not support
#    reasoning effort" 400 for e.g. haiku).
ANTHROPIC_STRIP_BODY_FIELDS: frozenset[str] = frozenset(
    f.strip() for f in os.environ.get(
        "CTC_ANTHROPIC_STRIP_FIELDS", "output_config").split(",") if f.strip()
)

# 4. thinking coercion. Claude Code sends thinking:{type:"adaptive"}; Copilot's
#    endpoint accepts only {type:"disabled"} or {type:"enabled",budget_tokens>=1024}.
#    Default disabled (fine for v1 / non-thinking models). Set CTC_ANTHROPIC_THINKING
#    =enabled to forward extended thinking on thinking-capable models.
ANTHROPIC_THINKING_MODE: str = os.environ.get("CTC_ANTHROPIC_THINKING", "disabled")
ANTHROPIC_THINKING_BUDGET: int = int(os.environ.get("CTC_ANTHROPIC_THINKING_BUDGET", "8192"))

# Resolves auto_mode.model_hints (e.g. ["auto"]) to a concrete model and
# issues a copilot-session-token used on the following billable call. Not
# itself billable/metered, but the session token it returns is bound to
# whichever giver identity requested it -- see
# AttributionService.pin_source/pinned_source in ctc/routing/attribution.py.
SESSION_BOOTSTRAP_PATH: str = "/models/session"

# Read-only model catalogue on the Copilot API host. NOT in BILLABLE_PATHS, so
# it costs no credit — which is what makes it usable as the PAT-health
# permission probe (ctc/auth/pat_health.py): the Copilot API host is the only
# one that enforces the fine-grained "Copilot Requests" permission, so a PAT
# lacking it 401s here while /copilot_internal/user still answers 200.
MODELS_PATH: str = "/models"

# Plain-text marker returned when a session_token minted for one giver is sent
# through a different giver's PAT on the next billable call.
INVALID_AUTO_MODE_SELECTOR_BODY: str = "Invalid auto-mode selector"

# Header carrying the opaque session_token from /models/session to billable calls.
COPILOT_SESSION_TOKEN_HEADER: str = "copilot-session-token"

# Default auto-mode bootstrap body used by the proxy's nested self-heal retry.
SESSION_BOOTSTRAP_BODY: bytes = json.dumps({"auto_mode": {"model_hints": ["auto"]}}).encode()

# copilot-api rejects "token <pat>" with 400 badly formatted.
AUTH_SCHEME: str = "Bearer"

# Per-request charge field. JSON: top-level. SSE: final message_delta event.
METERING_FIELD: tuple[str, str] = ("copilot_usage", "total_nano_aiu")
METERING_LOCATION: dict[str, str] = {
    "/chat/completions": "json-top-level",
    "/v1/messages": "sse-final-message_delta",
    "/responses": "sse-final-message_delta",
}

# GitHub-ish hosts that must never be blind-tunneled (a new one signals a
# Copilot endpoint that escaped interception). Suffix match + exact api.github.com.
SENTINEL_WATCH_SUFFIXES: tuple[str, ...] = (GHE_DOMAIN, "githubcopilot.com")
_SENTINEL_WATCH_EXACT: frozenset[str] = frozenset({"api.github.com"})


def is_github_ish(host: str) -> bool:
    """True if `host` should be MITM'd rather than blind-tunneled.

    Suffix match is on a dot boundary (or exact equality): an unbounded
    endswith let `evilgithubcopilot.com` match the `githubcopilot.com` suffix,
    which the SSRF/open-relay guard (connect_allowed) treats as trusted."""
    h = host.lower()
    if h in _SENTINEL_WATCH_EXACT:
        return True
    return any(h == s or h.endswith("." + s) for s in SENTINEL_WATCH_SUFFIXES)
