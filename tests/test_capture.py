import base64
import json
import os
from ctc.metering.capture import (
    redact_text, redact_headers, record_exchange, close_captures, _CAPTURE_HANDLES)


def test_redact_text_masks_github_tokens():
    s = "auth github_pat_ABCDEFGHIJ0123456789KLMNOP and ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    out = redact_text(s)
    assert "github_pat_" not in out
    assert "ghp_" not in out
    assert out.count("***REDACTED***") == 2


def test_redact_text_masks_json_token_field():
    s = '{"token":"tid=abc;exp=123;sig=zzz","expires_at":99}'
    out = redact_text(s)
    assert "tid=abc" not in out
    assert '"token":"***REDACTED***"' in out
    assert '"expires_at":99' in out


def test_redact_headers_fully_masks_sensitive_headers():
    out = redact_headers({
        "Authorization": "Bearer github_pat_X",
        "X-Access-Token": "ghp_secret",
        "Cookie": "session=abc",
        "Set-Cookie": "session=def",
        "authorization": "Bearer github_pat_Y",
        "Content-Type": "application/json",
    })
    assert out["Authorization"] == "***REDACTED***"
    assert out["X-Access-Token"] == "***REDACTED***"
    assert out["Cookie"] == "***REDACTED***"
    assert out["Set-Cookie"] == "***REDACTED***"
    assert out["authorization"] == "***REDACTED***"
    assert out["Content-Type"] == "application/json"


def test_redact_headers_masks_proxy_authorization():
    # the VS Code shim carries the CTC token in Proxy-Authorization; captures
    # must never persist it in the clear.
    import base64
    cred = base64.b64encode(b"ctc:github_pat_secret").decode()
    out = redact_headers({"Proxy-Authorization": f"Basic {cred}"})
    assert out["Proxy-Authorization"] == "***REDACTED***"
    assert "github_pat_secret" not in str(out)
    assert cred not in str(out)


def test_redact_headers_redacts_token_in_non_sensitive_value():
    out = redact_headers({"X-Custom": "ghp_" + "a" * 25})
    assert "ghp_" not in out["X-Custom"]
    assert "***REDACTED***" in out["X-Custom"]


def test_record_exchange_writes_redacted_ndjson(tmp_path):
    rec = record_exchange(
        str(tmp_path),
        method="POST",
        path="/copilot_internal/v2/token",
        upstream_host="api.example.ghe.com",
        status=200,
        request_headers={"Authorization": "Bearer github_pat_SECRET00000000000000000000"},
        response_headers={"Content-Type": "application/json"},
        response_body=b'{"token":"tid=secret;exp=1","chat_enabled":true}',
        response_content_type="application/json",
    )
    line = (tmp_path / "exchanges.ndjson").read_text().strip()
    on_disk = json.loads(line)
    assert on_disk == rec
    assert on_disk["request_headers"]["Authorization"] == "***REDACTED***"
    assert "tid=secret" not in line
    assert on_disk["body_kind"] == "text"
    assert on_disk["status"] == 200


def test_record_exchange_appends_multiple_lines(tmp_path):
    for _ in range(3):
        record_exchange(str(tmp_path), method="GET", path="/x", upstream_host="h",
                        status=200, request_headers={}, response_headers={}, response_body=b"{}")
    lines = (tmp_path / "exchanges.ndjson").read_text().splitlines()
    assert len(lines) == 3


def test_record_exchange_reuses_persistent_handle(tmp_path):
    close_captures()
    record_exchange(str(tmp_path), method="GET", path="/x", upstream_host="h",
                    status=200, request_headers={}, response_headers={}, response_body=b"{}")
    key = os.path.join(str(tmp_path), "exchanges.ndjson")
    first = _CAPTURE_HANDLES.get(key)
    assert first is not None and not first.closed
    record_exchange(str(tmp_path), method="GET", path="/y", upstream_host="h",
                    status=200, request_headers={}, response_headers={}, response_body=b"{}")
    # Same file path -> same handle reused, not reopened.
    assert _CAPTURE_HANDLES.get(key) is first
    close_captures()
    assert _CAPTURE_HANDLES == {}
    # Both appends made it to disk despite the shared handle.
    assert len((tmp_path / "exchanges.ndjson").read_text().splitlines()) == 2


def test_record_exchange_base64_for_binary_body(tmp_path):
    rec = record_exchange(str(tmp_path), method="GET", path="/x", upstream_host="h",
                          status=200, request_headers={}, response_headers={},
                          response_body=b"\xff\xfe\x00binary")
    assert rec["body_kind"] == "base64"


def test_redact_text_masks_access_token_key():
    s = '{"access_token":"tid=abc;exp=1;sig=zzz"}'
    out = redact_text(s)
    assert "tid=abc" not in out
    assert '"access_token":"***REDACTED***"' in out


def test_redact_text_masks_bare_copilot_token():
    out = redact_text("data: tid=abc;exp=1;sig=zzz")
    assert "tid=abc" not in out
    assert "***REDACTED***" in out


def test_record_exchange_redacts_token_in_non_utf8_body(tmp_path):
    body = b"\xff\xfe" + b"ghp_" + b"a" * 25
    rec = record_exchange(str(tmp_path), method="GET", path="/x", upstream_host="h",
                          status=200, request_headers={}, response_headers={},
                          response_body=body)
    assert rec["body_kind"] == "base64"
    decoded = base64.b64decode(rec["body"])
    assert b"ghp_" not in decoded
    assert b"***REDACTED***" in decoded
    # The raw token must never reach disk.
    line = (tmp_path / "exchanges.ndjson").read_text()
    assert "ghp_" not in line
