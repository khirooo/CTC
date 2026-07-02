from __future__ import annotations

import json

from ctc.contract import METERING_FIELD


def _usage_from_obj(obj) -> int | None:
    if not isinstance(obj, dict):
        return None
    outer, inner = METERING_FIELD
    cu = obj.get(outer)
    # bool is an int subclass; exclude it so a stray `total_nano_aiu: true` isn't
    # debited as 1 (matches sentinel._field_present, which also excludes bool).
    if isinstance(cu, dict) and isinstance(cu.get(inner), int) and not isinstance(cu.get(inner), bool):
        return cu[inner]
    return None


def extract_total_nano_aiu(body: bytes | str, content_type: str = "") -> int:
    """Per-request charge in nano-AIU, or 0 if no copilot_usage is present.

    JSON body -> top-level copilot_usage.total_nano_aiu.
    SSE body  -> the LAST `data:` event carrying copilot_usage (the final
    message_delta); robust to truncation and the trailing [DONE] sentinel.
    """
    if not body:
        return 0
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body

    is_sse = (
        "text/event-stream" in content_type.lower()
        or text.lstrip().startswith("event:")
        or "\ndata:" in text
        or text.startswith("data:")
    )

    if is_sse:
        last = 0
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                val = _usage_from_obj(json.loads(payload))
            except ValueError:
                continue
            if val is not None:
                last = val
        return last

    try:
        val = _usage_from_obj(json.loads(text))
    except ValueError:
        return 0
    return val or 0
