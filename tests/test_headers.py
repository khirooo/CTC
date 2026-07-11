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


def test_accept_encoding_includes_gzip_deflate():
    assert "gzip" in proxy._ACCEPT_ENCODING
    assert "deflate" in proxy._ACCEPT_ENCODING


def test_accept_encoding_pinned_over_client_value():
    # A client advertising a codec we can't decode (e.g. br when brotli is
    # absent) must be overridden with our decodable set.
    out = proxy.build_upstream_headers(
        {"authorization": "token x", "accept-encoding": "br, gzip, weird"},
        "api.example.ghe.com", "token x", 0, "PAT")
    assert out["accept-encoding"] == proxy._ACCEPT_ENCODING
    assert "weird" not in out["accept-encoding"]
