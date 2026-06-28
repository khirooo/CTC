import json
import proxy
from ctc import contract


def test_is_token_exchange_matches_only_get_v2token_on_ghe():
    api = f"api.{contract.GHE_DOMAIN}"
    assert proxy.is_token_exchange(api, "GET", "/copilot_internal/v2/token")
    assert proxy.is_token_exchange(api, "GET", "/copilot_internal/v2/token?x=1")
    # wrong method / path / non-swap host
    assert not proxy.is_token_exchange(api, "POST", "/copilot_internal/v2/token")
    assert not proxy.is_token_exchange(api, "GET", "/copilot_internal/user")
    assert not proxy.is_token_exchange("api.github.com", "GET", "/copilot_internal/v2/token")


def test_mock_token_exchange_response_is_200_json_with_token():
    raw = proxy._mock_token_exchange_response()
    head, body = raw.split(b"\r\n\r\n", 1)
    assert head.split(b"\r\n", 1)[0] == b"HTTP/1.1 200 OK"
    assert b"Content-Type: application/json" in head
    payload = json.loads(body)
    assert payload["token"]
    assert payload["endpoints"]["api"].startswith("https://copilot-api.")
    # Content-Length matches the body exactly
    clen = int([h for h in head.decode().split("\r\n") if h.lower().startswith("content-length:")][0].split(":")[1])
    assert clen == len(body)


def test_copilot_api_identity_headers_overwrite_client_values():
    # the extension sends copilot-integration-id: vscode-chat; the proxy must
    # rewrite it to the CLI's value so the swapped PAT is accepted.
    hdrs = {"copilot-integration-id": "vscode-chat", "editor-version": "vscode/1.99",
            "user-agent": "GitHubCopilotChat/x", "accept": "text/event-stream"}
    fwd = proxy.build_upstream_headers(hdrs, contract.BILLABLE_HOST, "Bearer fake", 0, "ghp_realpat")
    fwd = proxy.apply_copilot_api_identity(fwd, contract.BILLABLE_HOST)
    assert fwd["copilot-integration-id"] == "copilot-developer-cli"
    assert fwd["editor-version"] == "copilot/1.0.63"
    assert fwd["accept"] == "text/event-stream"  # unrelated headers preserved


def test_copilot_api_identity_noop_on_other_hosts():
    # mirror the real call chain: build_upstream_headers first, then apply_copilot_api_identity
    # this proves the identity rewrite is a true no-op end-to-end on the GHE API host
    hdrs = {"copilot-integration-id": "vscode-chat"}
    api_host = f"api.{contract.GHE_DOMAIN}"
    fwd = proxy.build_upstream_headers(hdrs, api_host, "Bearer fake", 0, "ghp_realpat")
    fwd = proxy.apply_copilot_api_identity(fwd, api_host)
    assert fwd["copilot-integration-id"] == "vscode-chat"  # NOT rewritten to copilot-developer-cli
