import proxy


def test_should_swap_ghe_hosts():
    assert proxy.should_swap("api.example.ghe.com") is True
    assert proxy.should_swap("copilot-api.example.ghe.com") is True


def test_should_not_swap_github():
    assert proxy.should_swap("api.github.com") is False


def test_swap_uses_bearer_pat_for_ghe():
    out = proxy.build_upstream_headers(
        {"authorization": "token github_pat_FAKE", "accept": "*/*"},
        "api.example.ghe.com", "token github_pat_FAKE", 0, "github_pat_REAL")
    assert out["authorization"] == "Bearer github_pat_REAL"
    assert out["host"] == "api.example.ghe.com"
    assert "content-length" not in out  # body_len 0 → omitted


def test_passthrough_token_for_github():
    out = proxy.build_upstream_headers(
        {"authorization": "Bearer ghu_x"}, "api.github.com", "Bearer ghu_x", 0, "github_pat_REAL")
    assert out["authorization"] == "Bearer ghu_x"


def test_hop_by_hop_stripped_and_length_set():
    out = proxy.build_upstream_headers(
        {"connection": "keep-alive", "transfer-encoding": "chunked",
         "authorization": "token x", "content-length": "5"},
        "api.example.ghe.com", "token x", 5, "PAT")
    for k in ("connection", "transfer-encoding", "proxy-connection"):
        assert k not in out
    assert out["content-length"] == "5"
