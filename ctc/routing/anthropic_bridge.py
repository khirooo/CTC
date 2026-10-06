"""Normalize native Anthropic Claude Code requests to Copilot's accepted schema.

The native Anthropic Claude Code CLI drives the GitHub Copilot backend through
CTC's forward proxy: it points ANTHROPIC_BASE_URL at CTC and POSTs the Anthropic
Messages API to copilot-api's ``/v1/messages``. Copilot's Anthropic endpoint
accepts a narrower schema than the public Anthropic API and 400s on payloads the
Claude Code CLI sends verbatim. This module holds the four empirically required
transforms (see ``TDD.md`` and ``docs/reference/metering-contract.md``):

  1. inject Copilot client-identity headers (else the swapped PAT is rejected),
  2. filter ``anthropic-beta`` to an allowlist (default drop — Copilot 400s on
     unknown beta values; the real Copilot CLI sends none),
  3. strip ``output_config`` (reasoning-effort / structured-output; Copilot 400s),
  4. coerce ``thinking`` to Copilot's ``{disabled|between_tools|enabled}`` schema,
     or pass ``adaptive`` through for models that accept nothing else.

Everything here is pure (no I/O, no logging) and unit-testable. Config lives in
``ctc/contract.py``. The proxy applies these ONLY on the billable copilot-api
``/v1/messages`` path (``is_bridge_request``); every other request — including the
Copilot CLI's own ``/chat/completions`` — is forwarded byte-for-byte unchanged.

Attribution, metering, and the PAT swap are untouched: this layer only rewrites
the outbound request body/headers before CTC's existing forward path runs.
"""
from __future__ import annotations

import json
from typing import Optional

from ctc import contract

# Copilot rejects thinking:{type:"enabled"} unless budget_tokens >= 1024.
_MIN_THINKING_BUDGET = 1024


def _min_budget(budget: object) -> int:
    """The configured thinking budget, floored at Copilot's 1024 minimum.
    Crash-safe: a non-int / bool default falls back to the floor."""
    if isinstance(budget, bool) or not isinstance(budget, int):
        return _MIN_THINKING_BUDGET
    return budget if budget >= _MIN_THINKING_BUDGET else _MIN_THINKING_BUDGET


def _model_in(model: object, prefixes) -> bool:
    """Prefix match after lowercasing and mapping "." to "-"."""
    if not isinstance(model, str):
        return False
    m = model.lower().replace(".", "-")
    return any(m.startswith(p) for p in prefixes)


def _off_type(model: object, between_tools_models) -> str:
    """The thinking "off" value this model accepts: ``between_tools`` for models
    that reject ``disabled`` (e.g. Sonnet 5.5), ``disabled`` for everything else."""
    return "between_tools" if _model_in(model, between_tools_models) else "disabled"


def is_bridge_request(upstream_host: str, method: str, path: str) -> bool:
    """True when this request is native Claude Code hitting copilot-api's
    Anthropic Messages endpoint and must be normalized. Scoped tightly so no
    other path (Copilot CLI's /chat/completions, /responses, /models/session,
    /v1/messages on any non-copilot-api host) is ever touched."""
    return (
        upstream_host == contract.BILLABLE_HOST
        and method.upper() == "POST"
        and path.split("?", 1)[0] == contract.ANTHROPIC_BRIDGE_PATH
    )


def transform_request_headers(
    fwd: dict,
    *,
    identity: Optional[dict] = None,
    beta_allow=None,
) -> dict:
    """Inject the Copilot client-identity headers and filter ``anthropic-beta``
    down to an allowlist. Mutates and returns ``fwd`` (whose keys are already
    lowercased by ``build_upstream_headers``).

    Transform 1 (identity) + transform 2 (beta filter).
    """
    if identity is None:
        identity = contract.COPILOT_API_IDENTITY_HEADERS
    if beta_allow is None:
        beta_allow = contract.ANTHROPIC_BETA_ALLOWLIST

    fwd.update(identity)

    # anthropic-beta may arrive under any casing; find and drop every variant,
    # then re-add only the allowlisted values (if any).
    beta_val = None
    for k in [k for k in fwd if k.lower() == "anthropic-beta"]:
        beta_val = fwd.pop(k)
    if beta_val is not None:
        keep = [b.strip() for b in beta_val.split(",") if b.strip() in beta_allow]
        if keep:
            fwd["anthropic-beta"] = ",".join(keep)
    return fwd


def transform_request_body(
    body: bytes,
    *,
    strip_fields=None,
    thinking_mode: Optional[str] = None,
    thinking_budget: Optional[int] = None,
    between_tools_models=None,
    adaptive_models=None,
) -> bytes:
    """Strip Copilot-unsupported top-level fields and coerce ``thinking`` to
    Copilot's accepted schema. Returns the re-serialized body (caller must
    recompute content-length) or the original bytes unchanged if nothing applied
    or the body is not a JSON object.

    Transform 3 (strip output_config) + transform 4 (thinking coercion). Models
    in ``adaptive_models`` keep ``output_config`` (it is how they set effort).
    """
    if strip_fields is None:
        strip_fields = contract.ANTHROPIC_STRIP_BODY_FIELDS
    if thinking_mode is None:
        thinking_mode = contract.ANTHROPIC_THINKING_MODE
    if thinking_budget is None:
        thinking_budget = contract.ANTHROPIC_THINKING_BUDGET
    if between_tools_models is None:
        between_tools_models = contract.ANTHROPIC_BETWEEN_TOOLS_MODELS
    if adaptive_models is None:
        adaptive_models = contract.ANTHROPIC_ADAPTIVE_MODELS

    try:
        obj = json.loads(body or b"")
    except Exception:
        return body
    if not isinstance(obj, dict):
        return body

    changed = False
    adaptive_only = _model_in(obj.get("model"), adaptive_models)

    for field in strip_fields:
        if adaptive_only and field == "output_config":
            continue
        if field in obj:
            obj.pop(field)
            changed = True

    # Copilot's Anthropic endpoint knows only an "off" value and
    # {type:"enabled", budget_tokens:>=1024}. The off value is model-specific:
    # {type:"disabled"} for most, {type:"between_tools"} for models that reject
    # disabled (see _off_type). Claude Code sends {type:"adaptive"} (and may send
    # other future values); coerce anything that isn't an accepted shape.
    th = obj.get("thinking")
    if isinstance(th, dict) and adaptive_only:
        # Adaptive is the only mode these models take. Anything else is dropped
        # (not rewritten to adaptive) so a client asking for "off" gets the
        # model's default rather than thinking it explicitly opted into.
        if th.get("type") != "adaptive":
            obj.pop("thinking")
            changed = True
    elif isinstance(th, dict):
        th_type = th.get("type")
        off = _off_type(obj.get("model"), between_tools_models)
        if th_type in ("disabled", "between_tools"):
            # Either off value is normalized to the one this model accepts, so a
            # client-sent between_tools passes through and a disabled sent to a
            # between_tools-only model doesn't 400.
            if th_type != off:
                obj["thinking"] = {"type": off}
                changed = True
        elif th_type != "enabled":
            # adaptive / future values -> coerce per configured mode.
            if thinking_mode == "enabled":
                obj["thinking"] = {"type": "enabled", "budget_tokens": _min_budget(thinking_budget)}
            else:
                obj["thinking"] = {"type": off}
            changed = True
        else:
            # Copilot requires budget_tokens >= 1024 for enabled; a bare or
            # too-small budget would 400. Floor it to a valid value.
            budget = th.get("budget_tokens")
            if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1024:
                th["budget_tokens"] = _min_budget(thinking_budget)
                changed = True

    if not changed:
        return body
    try:
        return json.dumps(obj).encode()
    except Exception:
        return body
