import base64
import inspect

import proxy


def _basic(cred: str) -> str:
    return "Basic " + base64.b64encode(cred.encode()).decode()


def test_parse_proxy_authorization_token_in_password():
    assert proxy.parse_proxy_authorization(
        {"proxy-authorization": _basic("ctc:github_pat_abc")}) == "github_pat_abc"


def test_parse_proxy_authorization_token_in_username():
    assert proxy.parse_proxy_authorization(
        {"proxy-authorization": _basic("github_pat_abc:")}) == "github_pat_abc"


def test_parse_proxy_authorization_missing_returns_none():
    assert proxy.parse_proxy_authorization({}) is None


def test_parse_proxy_authorization_non_basic_returns_none():
    assert proxy.parse_proxy_authorization({"proxy-authorization": "Bearer x"}) is None


def test_parse_proxy_authorization_malformed_base64_returns_none():
    assert proxy.parse_proxy_authorization({"proxy-authorization": "Basic !!!notb64!!!"}) is None


def test_proxy_auth_from_head_reads_connect():
    host = f"api.{proxy.contract.GHE_DOMAIN}"
    raw = (f"CONNECT {host}:443 HTTP/1.1\r\n"
           f"Host: {host}:443\r\n"
           f"Proxy-Authorization: {_basic('ctc:github_pat_xyz')}\r\n\r\n").encode()
    assert proxy.proxy_auth_from_head(raw) == "github_pat_xyz"


def test_proxy_auth_from_head_absent_returns_none():
    raw = b"CONNECT h:443 HTTP/1.1\r\nHost: h\r\n\r\n"
    assert proxy.proxy_auth_from_head(raw) is None


def test_select_identity_token_proxy_auth_wins_over_bearer():
    assert proxy.select_identity_token(
        "github_pat_proxy", "Bearer mocked_copilot_token") == "github_pat_proxy"


def test_select_identity_token_falls_back_to_bearer():
    assert proxy.select_identity_token(None, "Bearer github_pat_cli") == "github_pat_cli"


def test_select_identity_token_strips_scheme_on_fallback():
    assert proxy.select_identity_token(None, "token ghs_abc") == "ghs_abc"


def test_proxy_authorization_stripped_from_upstream():
    hdrs = {"proxy-authorization": _basic("ctc:tok"), "accept": "x"}
    fwd = proxy.build_upstream_headers(
        hdrs, f"api.{proxy.contract.GHE_DOMAIN}", "Bearer fake", 0, "ghp_pat")
    assert "proxy-authorization" not in fwd
    assert fwd["accept"] == "x"


def test_masked_headers_covers_both_auth_headers():
    assert "authorization" in proxy._MASKED_HEADERS
    assert "proxy-authorization" in proxy._MASKED_HEADERS


def test_serve_accepts_identity_token_kwarg():
    sig = inspect.signature(proxy._serve)
    assert "identity_token" in sig.parameters
    assert sig.parameters["identity_token"].default is None
