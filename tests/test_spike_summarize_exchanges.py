from tools.spike_summarize_exchanges import summarize


def _rec(host, path, status=200, method="POST", body=""):
    return {
        "method": method, "host": host, "path": path, "status": status,
        "request_headers": {"authorization": "***REDACTED***"},
        "response_headers": {}, "response_content_type": "application/json",
        "body_kind": "text", "body": body,
    }


def test_summarize_groups_hosts_and_paths():
    recs = [
        _rec("copilot-api.example.ghe.com", "/chat/completions", body='{"copilot_usage":{"total_nano_aiu":42}}'),
        _rec("api.example.ghe.com", "/copilot_internal/v2/token", method="GET", body='{"token":"***REDACTED***"}'),
        _rec("api.example.ghe.com", "/copilot_internal/user", method="GET"),
    ]
    out = summarize(recs)

    assert out["hosts"]["api.example.ghe.com"]["count"] == 2
    assert "/copilot_internal/user" in out["hosts"]["api.example.ghe.com"]["paths"]

    assert len(out["token_exchange"]) == 1
    assert out["token_exchange"][0]["path"] == "/copilot_internal/v2/token"

    assert len(out["billable"]) == 1
    assert out["billable"][0]["host"] == "copilot-api.example.ghe.com"

    assert len(out["metering_hits"]) == 1
    assert out["metering_hits"][0]["path"] == "/chat/completions"

    assert out["statuses"]["copilot-api.example.ghe.com"] == [200]


def test_summarize_never_leaks_raw_headers():
    out = summarize([_rec("h", "/p")])
    blob = repr(out)
    assert "authorization" not in blob.lower()
