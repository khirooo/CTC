from ctc import contract


def test_token_exchange_path():
    assert contract.TOKEN_EXCHANGE_PATH == "/copilot_internal/v2/token"


def test_mock_token_template_has_required_keys():
    t = contract.MOCK_TOKEN_TEMPLATE
    # the extension reads these from the /v2/token response
    for key in ("token", "expires_at", "refresh_in", "endpoints", "chat_enabled"):
        assert key in t, key
    assert t["endpoints"]["api"] == f"https://copilot-api.{contract.GHE_DOMAIN}"


def test_mock_token_ttl_and_refresh_are_positive_ints():
    assert isinstance(contract.MOCK_TOKEN_TTL_SECONDS, int) and contract.MOCK_TOKEN_TTL_SECONDS > 0
    assert isinstance(contract.MOCK_TOKEN_REFRESH_SECONDS, int) and contract.MOCK_TOKEN_REFRESH_SECONDS > 0


def test_copilot_api_identity_headers_are_cli_allowlisted():
    h = contract.COPILOT_API_IDENTITY_HEADERS
    # the discriminator that makes copilot-api accept the swapped PAT (R1)
    assert h["copilot-integration-id"] == "copilot-developer-cli"
    assert "editor-version" in h and "user-agent" in h
    # header names are lowercase so they overwrite the client's headers in build_upstream_headers
    assert all(k == k.lower() for k in h)


def test_responses_is_billable_and_metered():
    assert "/responses" in contract.BILLABLE_PATHS
    assert "/responses" in contract.METERING_LOCATION
