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


def is_github_ish(host: str) -> bool:
    """True if `host` should be MITM'd rather than blind-tunneled.

    Suffix match is on a dot boundary (or exact equality): an unbounded
    endswith let `evilgithubcopilot.com` match the `githubcopilot.com` suffix,
    which the SSRF/open-relay guard (connect_allowed) treats as trusted."""
    h = host.lower()
    if h in _SENTINEL_WATCH_EXACT:
        return True
    return any(h == s or h.endswith("." + s) for s in SENTINEL_WATCH_SUFFIXES)
