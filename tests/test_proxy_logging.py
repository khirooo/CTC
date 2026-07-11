"""B4 (P1-8 + P2 verbose): proxy logs redact secrets and gate bodies behind DEBUG."""
import logging

import pytest

import proxy as proxy_mod


class _FakeResp:
    def __init__(self, status, headers, body=b""):
        self.status = status
        self.reason = "OK"
        self.headers = headers
        self._body = body

    async def read(self):
        return self._body


class _NullWriter:
    def write(self, data):
        pass

    async def drain(self):
        pass


def test_log_block_is_debug_only(caplog):
    with caplog.at_level(logging.INFO, logger="proxy"):
        proxy_mod._log_block("X", "hello")
    assert "hello" not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="proxy"):
        proxy_mod._log_block("X", "hello")
    assert "hello" in caplog.text


async def test_response_body_token_redacted_in_debug_log(caplog):
    secret = "github_pat_" + "A" * 30
    body = ('{"session_token":"%s"}' % secret).encode()
    resp = _FakeResp(200, {"Content-Type": "application/json",
                           "Content-Length": str(len(body))}, body=body)
    with caplog.at_level(logging.DEBUG, logger="proxy"):
        await proxy_mod._relay_response(_NullWriter(), resp, "h", "/x")
    assert secret not in caplog.text
    assert "***REDACTED***" in caplog.text


async def test_response_body_not_logged_at_info(caplog):
    secret = "github_pat_" + "B" * 30
    body = ('{"session_token":"%s"}' % secret).encode()
    resp = _FakeResp(200, {"Content-Type": "application/json",
                           "Content-Length": str(len(body))}, body=body)
    with caplog.at_level(logging.INFO, logger="proxy"):
        await proxy_mod._relay_response(_NullWriter(), resp, "h", "/x")
    # No body text emitted at INFO, redacted or otherwise.
    assert secret not in caplog.text
    assert "RESPONSE BODY" not in caplog.text


def test_copilot_session_token_is_a_sensitive_header():
    from ctc.metering.capture import redact_headers
    out = redact_headers({"copilot-session-token": "tid=abc;exp=1;sig=z"})
    assert out["copilot-session-token"] == "***REDACTED***"
