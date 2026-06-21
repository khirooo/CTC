"""Passive drift detectors for the proxy. Pure functions: they take parsed
inputs and return an optional Finding. They never log, mutate state, or touch
the network — proxy.py logs whatever they return. See the contract module for
the expected truth these watch for divergence from.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ctc import contract


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str


def _field_present(obj) -> bool:
    outer, inner = contract.METERING_FIELD
    if not isinstance(obj, dict):
        return False
    cu = obj.get(outer)
    if not isinstance(cu, dict):
        return False
    v = cu.get(inner)
    # Only count the field as present when its value is a usable number.
    # A present-but-non-numeric value (null, string, bool, …) is drifted /
    # unusable — treat it as absent so classify_usage fires the silent-billing
    # sentinel correctly instead of crashing on the comparison.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _field_value(obj) -> int:
    outer, inner = contract.METERING_FIELD
    return obj[outer][inner]


def classify_usage(body: bytes | str, content_type: str, path: str) -> str:
    """Tri-state: 'present_positive' | 'present_zero' | 'absent'.

    Distinguishes a genuine 0-cost response (field present, value 0) from a
    drift (field absent entirely) — extract_total_nano_aiu collapses both to 0.
    """
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else (body or "")
    is_sse = "text/event-stream" in content_type.lower() or "\ndata:" in text or text.lstrip().startswith(("event:", "data:"))

    found = None  # last object that carried the field
    if is_sse:
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            if _field_present(obj):
                found = obj
    else:
        try:
            obj = json.loads(text)
        except ValueError:
            return "absent"
        if _field_present(obj):
            found = obj

    if found is None:
        return "absent"
    return "present_positive" if _field_value(found) > 0 else "present_zero"


def check_billable_response(status: int, body: bytes | str, content_type: str, path: str) -> Finding | None:
    """Finding when a billable 200 carries no metering field — the silent-
    billing break. Genuine 0-cost responses (present_zero) and errors (non-200)
    are fine."""
    if status != 200:
        return None
    if classify_usage(body, content_type, path) == "absent":
        return Finding(
            "metering_field_missing",
            f"billable 200 with no {'.'.join(contract.METERING_FIELD)} field (path={path})",
        )
    return None


def check_bypassed_host(host: str) -> Finding | None:
    """Finding when a GitHub-ish host is about to be blind-tunneled — either
    a known host escaping interception, or a new endpoint we haven't seen before.
    Any github-ish host on the blind-tunnel path is worth flagging."""
    if contract.is_github_ish(host):
        return Finding("bypassed_github_host", f"GitHub-ish host blind-tunneled (host={host})")
    return None


def check_billable_rejection(status: int, path: str) -> Finding | None:
    """Finding when a billable request is rejected — auth-scheme or endpoint
    contract drift (e.g. Bearer->token change)."""
    if status in (400, 401, 403):
        return Finding("billable_rejected", f"billable request rejected (status={status} path={path})")
    return None
