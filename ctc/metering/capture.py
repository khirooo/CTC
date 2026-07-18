"""Capture harness for the metering spike.

Serializes request/response exchanges to a redacted NDJSON log so we can locate
the per-request credit cost and PAT quota in real Copilot traffic. Redaction is
the load-bearing safety property: no GitHub token may ever reach a fixture file.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Mapping, TextIO

_REDACTED = "***REDACTED***"

# One persistent append handle per capture file, so we don't re-open (+ re-seek
# to EOF) the NDJSON on every exchange. Keyed by absolute file path.
_CAPTURE_HANDLES: dict[str, TextIO] = {}


def _capture_handle(capture_dir: str) -> TextIO:
    path = os.path.join(capture_dir, "exchanges.ndjson")
    f = _CAPTURE_HANDLES.get(path)
    if f is None or f.closed:
        os.makedirs(capture_dir, exist_ok=True)
        f = open(path, "a", encoding="utf-8")
        _CAPTURE_HANDLES[path] = f
    return f


def close_captures() -> None:
    """Close all persistent capture handles (flushing them). Safe to call on
    shutdown or from tests."""
    for f in _CAPTURE_HANDLES.values():
        try:
            f.close()
        except Exception:
            pass
    _CAPTURE_HANDLES.clear()

# GitHub PAT / OAuth token formats, plus the short-lived copilot token carried
# as a JSON "token" field in the /copilot_internal/v2/token response.
_TOKEN_RE = re.compile(r"(?:gh[posru]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
_COPILOT_TOKEN_RE = re.compile(r'tid=[^\s"\';]+(?:;[^\s"\';]+)+')
_JSON_TOKEN_RE = re.compile(
    r'("(?:token|access_token|refresh_token|copilot_token|id_token|session_token)"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)

_SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "x-access-token",
                      "cookie", "set-cookie", "copilot-session-token"}


def redact_text(text: str) -> str:
    text = _TOKEN_RE.sub(_REDACTED, text)
    text = _COPILOT_TOKEN_RE.sub(_REDACTED, text)
    text = _JSON_TOKEN_RE.sub(r'\1"' + _REDACTED + '"', text)
    return text


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        out[k] = _REDACTED if k.lower() in _SENSITIVE_HEADERS else redact_text(v)
    return out


def record_exchange(
    capture_dir: str,
    *,
    method: str,
    path: str,
    upstream_host: str,
    status: int,
    request_headers: Mapping[str, str],
    response_headers: Mapping[str, str],
    response_body: bytes,
    response_content_type: str = "",
) -> dict:
    try:
        body = redact_text(response_body.decode("utf-8"))
        body_kind = "text"
    except UnicodeDecodeError:
        redacted = redact_text(response_body.decode("latin-1")).encode("latin-1")
        body = base64.b64encode(redacted).decode("ascii")
        body_kind = "base64"

    record = {
        "method": method,
        "host": upstream_host,
        "path": path,
        "status": status,
        "request_headers": redact_headers(request_headers),
        "response_headers": redact_headers(response_headers),
        "response_content_type": response_content_type,
        "body_kind": body_kind,
        "body": body,
    }
    f = _capture_handle(capture_dir)
    f.write(json.dumps(record) + "\n")
    f.flush()
    return record
