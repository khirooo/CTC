import json

import proxy


def test_is_billable_matches_only_completion_posts():
    assert proxy.is_billable("copilot-api.example.ghe.com", "POST", "/chat/completions")
    assert proxy.is_billable("copilot-api.example.ghe.com", "POST", "/v1/messages")
    # query string tolerated
    assert proxy.is_billable("copilot-api.example.ghe.com", "POST", "/v1/messages?x=1")
    # wrong method / host / path
    assert not proxy.is_billable("copilot-api.example.ghe.com", "GET", "/v1/messages")
    assert not proxy.is_billable("api.example.ghe.com", "POST", "/chat/completions")
    assert not proxy.is_billable("copilot-api.example.ghe.com", "POST", "/models")


def test_is_session_bootstrap_matches_models_session_post():
    assert proxy.is_session_bootstrap("copilot-api.example.ghe.com", "POST", "/models/session")
    # query string tolerated
    assert proxy.is_session_bootstrap("copilot-api.example.ghe.com", "POST", "/models/session?x=1")
    # wrong method / host / path
    assert not proxy.is_session_bootstrap("copilot-api.example.ghe.com", "GET", "/models/session")
    assert not proxy.is_session_bootstrap("api.example.ghe.com", "POST", "/models/session")
    assert not proxy.is_session_bootstrap("copilot-api.example.ghe.com", "POST", "/responses")
    # never overlaps with is_billable -- the whole point is they're mutually exclusive
    assert not proxy.is_billable("copilot-api.example.ghe.com", "POST", "/models/session")
    assert not proxy.is_session_bootstrap("copilot-api.example.ghe.com", "POST", "/v1/messages")


def test_is_invalid_auto_mode_selector_401():
    assert proxy.is_invalid_auto_mode_selector_401(401, b"Invalid auto-mode selector")
    assert not proxy.is_invalid_auto_mode_selector_401(401, b"something else")
    assert not proxy.is_invalid_auto_mode_selector_401(200, b"Invalid auto-mode selector")
    assert not proxy.is_invalid_auto_mode_selector_401(401, b"")
    assert not proxy.is_invalid_auto_mode_selector_401(403, b"Invalid auto-mode selector")


def test_patch_json_model_field():
    body = b'{"model": "gpt-5.3-codex", "other": 1}'
    patched = proxy._patch_json_model_field(body, "claude-sonnet-4.6")
    payload = json.loads(patched)
    assert payload["model"] == "claude-sonnet-4.6"
    assert payload["other"] == 1

    already = b'{"model": "claude-sonnet-4.6", "other": 1}'
    assert proxy._patch_json_model_field(already, "claude-sonnet-4.6") == already

    malformed = b"not json"
    assert proxy._patch_json_model_field(malformed, "claude-sonnet-4.6") == malformed

    no_model = b'{"other": 1}'
    assert proxy._patch_json_model_field(no_model, "claude-sonnet-4.6") == no_model


def test_strip_bearer():
    assert proxy.strip_bearer("Bearer ghp_x") == "ghp_x"
    assert proxy.strip_bearer("token ghp_y") == "ghp_y"
    assert proxy.strip_bearer("ghp_z") == "ghp_z"
    assert proxy.strip_bearer("") == ""


def _parse_block(raw: bytes):
    import json
    head, body = raw.split(b"\r\n\r\n", 1)
    status_line = head.split(b"\r\n", 1)[0].decode()
    return status_line, json.loads(body)


def test_ctc_block_response_uses_anthropic_envelope_for_messages():
    raw = proxy._ctc_block_response("/v1/messages", 402, "out of credit")
    status, payload = _parse_block(raw)
    assert status == "HTTP/1.1 402 Payment Required"
    assert payload == {"type": "error", "error": {"type": "ctc_error", "message": "out of credit"}}


def test_ctc_block_response_uses_openai_envelope_for_completions():
    # query string must not change the envelope choice
    raw = proxy._ctc_block_response("/chat/completions?x=1", 401, "bad token")
    status, payload = _parse_block(raw)
    assert status == "HTTP/1.1 401 Unauthorized"
    assert payload["error"]["message"] == "bad token"
    assert payload["error"]["type"] == "ctc_error"


def test_ctc_block_response_content_length_matches_body():
    raw = proxy._ctc_block_response("/v1/messages", 503, "no cycle")
    head, body = raw.split(b"\r\n\r\n", 1)
    declared = int(next(l.split(b":", 1)[1] for l in head.split(b"\r\n")
                        if l.lower().startswith(b"content-length")))
    assert declared == len(body)
