import importlib

from ctc import contract


def test_billable_constants():
    assert contract.BILLABLE_HOST == "copilot-api.example.ghe.com"
    assert contract.BILLABLE_PATHS == {"/chat/completions", "/v1/messages", "/responses"}
    assert contract.BILLABLE_METHOD == "POST"
    assert contract.AUTH_SCHEME == "Bearer"


def test_metering_field_is_copilot_usage_total_nano_aiu():
    assert contract.METERING_FIELD == ("copilot_usage", "total_nano_aiu")
    assert contract.METERING_LOCATION["/chat/completions"] == "json-top-level"
    assert contract.METERING_LOCATION["/v1/messages"] == "sse-final-message_delta"
    assert contract.METERING_LOCATION["/responses"] == "sse-final-message_delta"


def test_swap_hosts_subset_of_mitm():
    assert contract.SWAP_HOSTS <= contract.EXPECTED_MITM_HOSTS


def test_copilot_identity_headers_default_to_proven_values():
    """LOW2: defaults must match the current proven client-identity literals."""
    assert contract.COPILOT_API_IDENTITY_HEADERS == {
        "copilot-integration-id": "copilot-developer-cli",
        "editor-version": "copilot/1.0.63",
        "user-agent": "GitHubCopilotChat/copilot/1.0.63",
    }


def test_copilot_identity_headers_env_overridable(monkeypatch):
    """LOW2: each client-identity value is env-overridable so a deprecated
    Copilot client version can be field-patched without a code change."""
    monkeypatch.setenv("CTC_COPILOT_INTEGRATION_ID", "copilot-chat")
    monkeypatch.setenv("CTC_COPILOT_EDITOR_VERSION", "copilot/9.9.9")
    monkeypatch.setenv("CTC_COPILOT_USER_AGENT", "GitHubCopilotChat/copilot/9.9.9")
    reloaded = importlib.reload(contract)
    try:
        assert reloaded.COPILOT_API_IDENTITY_HEADERS == {
            "copilot-integration-id": "copilot-chat",
            "editor-version": "copilot/9.9.9",
            "user-agent": "GitHubCopilotChat/copilot/9.9.9",
        }
    finally:
        monkeypatch.undo()
        importlib.reload(contract)  # restore defaults for other tests


def test_is_github_ish():
    assert contract.is_github_ish("copilot-api.example.ghe.com")
    assert contract.is_github_ish("api.github.com")
    assert contract.is_github_ish("api.githubcopilot.com")
    assert not contract.is_github_ish("registry.npmjs.org")
    assert not contract.is_github_ish("example.com")
    # dot-boundary: a lookalike prefix must NOT match the trusted suffix
    assert not contract.is_github_ish("evilgithubcopilot.com")
    assert not contract.is_github_ish("notexample.ghe.com")
    # exact suffix host itself still matches
    assert contract.is_github_ish("githubcopilot.com")
    assert contract.is_github_ish("example.ghe.com")
