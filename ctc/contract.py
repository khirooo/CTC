"""Single source of truth for CTC's reverse-engineered contract with the
GitHub Copilot CLI. Pure data + pure helpers — no I/O, no logging.

Every entry here is a non-contractual behavior observed in traffic (see
TDD.md §4, §6, §11 and docs/reference/metering-contract.md).
A Copilot CLI update can change any of it; the sentinel and canary watch for
exactly that.
"""
from __future__ import annotations

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
    """True if `host` should be MITM'd rather than blind-tunneled."""
    h = host.lower()
    return h in _SENTINEL_WATCH_EXACT or any(h.endswith(s) for s in SENTINEL_WATCH_SUFFIXES)
