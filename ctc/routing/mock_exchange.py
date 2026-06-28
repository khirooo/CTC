"""Fabricate the /copilot_internal/v2/token response for the VS Code Copilot
extension. The extension requires this exchange (the CLI never makes it) and the
endpoint accepts no PAT, so the proxy answers it locally. The fabricated token is
replayed by the extension to copilot-api.*, where the proxy swaps ALL auth to the
real PAT (and rewrites copilot-integration-id) — so the token only needs to be
replayable, not valid. Pure, no I/O.
See docs/superpowers/specs/2026-06-28-vscode-extension-integration-design.md.
"""
from __future__ import annotations

import copy

from ctc import contract


def build_token_response(now_epoch: int) -> dict:
    expires_at = int(now_epoch) + contract.MOCK_TOKEN_TTL_SECONDS
    out = copy.deepcopy(contract.MOCK_TOKEN_TEMPLATE)
    # `exp=` is embedded in the real Copilot token string; the extension reads it
    # to schedule refresh. `tid=ctc` marks it as CTC-fabricated in logs/captures.
    out["token"] = f"tid=ctc;exp={expires_at}"
    out["expires_at"] = expires_at
    out["refresh_in"] = contract.MOCK_TOKEN_REFRESH_SECONDS
    return out
