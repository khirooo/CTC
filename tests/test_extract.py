import json as _json
import os

from ctc import contract
from ctc.metering.extract import extract_total_nano_aiu

# Real shape from fixtures ex13 (gpt-4o-mini, free) — JSON body, sibling of "usage".
JSON_FREE = (
    '{"choices":[{"message":{"content":"hi","role":"assistant"}}],'
    '"usage":{"total_tokens":182},"model":"gpt-4o-mini-2024-07-18",'
    '"copilot_usage":{"token_details":[],"total_nano_aiu":0}}'
)
# Real shape from fixtures ex14 (claude-sonnet, SSE) — usage in final message_delta.
SSE_PRICED = (
    "event: message_start\n"
    'data: {"type":"message_start","message":{"usage":{"input_tokens":3}}}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
    "event: message_delta\n"
    'data: {"copilot_usage":{"token_details":[],"total_nano_aiu":8262952500},'
    '"type":"message_delta","usage":{"output_tokens":326}}\n\n'
    "event: message_stop\n"
    'data: {"type":"message_stop"}\n\n'
    "data: [DONE]\n\n"
)
# Real shape from fixtures ex16 (400, bad model) — no copilot_usage at all.
ERR_400 = '{"error":{"message":"model not available","code":"model_not_available_for_integrator"}}'


def test_extract_uses_contract_field_names():
    outer, inner = contract.METERING_FIELD
    body = '{"%s":{"%s":1234}}' % (outer, inner)
    assert extract_total_nano_aiu(body, "application/json") == 1234


def test_json_free_model_returns_zero():
    assert extract_total_nano_aiu(JSON_FREE, "application/json") == 0


def test_sse_returns_last_message_delta_value():
    assert extract_total_nano_aiu(SSE_PRICED, "text/event-stream") == 8262952500


def test_error_body_returns_zero():
    assert extract_total_nano_aiu(ERR_400, "application/json") == 0


def test_empty_body_returns_zero():
    assert extract_total_nano_aiu(b"", "") == 0


def test_accepts_bytes_and_detects_sse_without_content_type():
    assert extract_total_nano_aiu(SSE_PRICED.encode(), "") == 8262952500


def test_truncated_sse_before_usage_returns_zero():
    truncated = "event: message_start\ndata: {\"type\":\"message_start\"}\n\n"
    assert extract_total_nano_aiu(truncated, "text/event-stream") == 0


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "metering", "exchanges.ndjson")


def _load_fixture_records():
    # The fixture contains embedded raw newlines in SSE bodies, so decode the
    # whole file as concatenated JSON objects rather than line-by-line.
    with open(FIXTURE, encoding="utf-8") as fh:
        raw = fh.read()
    dec = _json.JSONDecoder(strict=False)
    i, n, recs = 0, len(raw), []
    while i < n:
        while i < n and raw[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        obj, i = dec.raw_decode(raw, i)
        recs.append(obj)
    return recs


def test_against_real_fixtures():
    recs = _load_fixture_records()
    # Lookup is by positional index into the fixture; this is
    # fixture-order-dependent (records must keep their current ordering).
    by_idx = {i: r for i, r in enumerate(recs)}
    # ex13 chat/completions free model, ex14 + ex19 sse priced, ex16 400.
    assert extract_total_nano_aiu(by_idx[13]["body"], by_idx[13]["response_content_type"]) == 0
    assert extract_total_nano_aiu(by_idx[14]["body"], by_idx[14]["response_content_type"]) == 8262952500
    assert extract_total_nano_aiu(by_idx[19]["body"], by_idx[19]["response_content_type"]) == 1210027500
    assert extract_total_nano_aiu(by_idx[16]["body"], by_idx[16]["response_content_type"]) == 0
