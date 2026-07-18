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

# Resolves auto_mode.model_hints (e.g. ["auto"]) to a concrete model and
# issues a copilot-session-token used on the following billable call. Not
# itself billable/metered, but the session token it returns is bound to
# whichever giver identity requested it -- see
# AttributionService.pin_source/pinned_source in ctc/routing/attribution.py.
SESSION_BOOTSTRAP_PATH: str = "/models/session"

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


# --- VS Code Copilot extension integration (see spec 2026-06-28) ---------------
# The extension REQUIRES this token exchange (the CLI never makes it) and the
# endpoint accepts no PAT (fine-grained 403, classic 404). The proxy answers it
# locally with MOCK_TOKEN_TEMPLATE; the fabricated token is opaque to the
# extension (it only replays it as Bearer to copilot-api, where we swap it out).
TOKEN_EXCHANGE_PATH: str = "/copilot_internal/v2/token"

# TTL/refresh for the fabricated token (seconds), matching the real capture.
MOCK_TOKEN_TTL_SECONDS: int = 1800
MOCK_TOKEN_REFRESH_SECONDS: int = 1500

# Field set the extension reads from /v2/token (captured 2026-06-28, token
# redacted). `token`/`expires_at`/`refresh_in` are overwritten per request by
# build_token_response(); the rest are static. endpoints.* are derived from
# GHE_DOMAIN so they track the deployment.
MOCK_TOKEN_TEMPLATE: dict = {
    "agent_mode_auto_approval": True,
    "annotations_enabled": False,
    "azure_only": False,
    "chat_enabled": True,
    "chat_jetbrains_enabled": True,
    "code_quote_enabled": False,
    "code_review_enabled": False,
    "codesearch": True,
    "copilotignore_enabled": False,
    "endpoints": {
        "api": f"https://copilot-api.{GHE_DOMAIN}",
        "origin-tracker": f"https://origin-tracker.{GHE_DOMAIN}",
        "proxy": f"https://copilot-proxy.{GHE_DOMAIN}",
        "telemetry": f"https://copilot-telemetry-service.{GHE_DOMAIN}",
    },
    "individual": False,
    "limited_user_quotas": None,
    "limited_user_reset_date": None,
    "public_suggestions": "enabled",
    "refresh_in": 0,            # overwritten per request
    "sku": "copilot_for_business_seat_quota",
    "telemetry": "disabled",
    "token": "",               # overwritten per request
    "expires_at": 0,           # overwritten per request
    "tracking_id": "ctc-fabricated",
    "xcode": True,
    "xcode_chat": False,
}

# copilot-api gates PAT acceptance on copilot-integration-id: it accepts the PAT
# for the CLI's id (copilot-developer-cli) but rejects it for the extension's
# (vscode-chat) with "Personal Access Tokens are not supported for this endpoint".
# The proxy rewrites these on copilot-api requests to the CLI's allowlisted
# identity so the swapped PAT is accepted on every endpoint the extension uses
# (R1, capture 3). Lowercase keys so they overwrite the client's own headers.
COPILOT_API_IDENTITY_HEADERS: dict[str, str] = {
    "copilot-integration-id": "copilot-developer-cli",
    "editor-version": "copilot/1.0.63",
    "user-agent": "GitHubCopilotChat/copilot/1.0.63",
}


def is_github_ish(host: str) -> bool:
    """True if `host` should be MITM'd rather than blind-tunneled.

    Suffix match is on a dot boundary (or exact equality): an unbounded
    endswith let `evilgithubcopilot.com` match the `githubcopilot.com` suffix,
    which the SSRF/open-relay guard (connect_allowed) treats as trusted."""
    h = host.lower()
    if h in _SENTINEL_WATCH_EXACT:
        return True
    return any(h == s or h.endswith("." + s) for s in SENTINEL_WATCH_SUFFIXES)
