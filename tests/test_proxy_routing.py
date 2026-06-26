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
