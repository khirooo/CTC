from ctc import contract


def test_billable_constants():
    assert contract.BILLABLE_HOST == "copilot-api.example.ghe.com"
    assert contract.BILLABLE_PATHS == {"/chat/completions", "/v1/messages"}
    assert contract.BILLABLE_METHOD == "POST"
    assert contract.AUTH_SCHEME == "Bearer"


def test_metering_field_is_copilot_usage_total_nano_aiu():
    assert contract.METERING_FIELD == ("copilot_usage", "total_nano_aiu")
    assert contract.METERING_LOCATION["/chat/completions"] == "json-top-level"
    assert contract.METERING_LOCATION["/v1/messages"] == "sse-final-message_delta"


def test_swap_hosts_subset_of_mitm():
    assert contract.SWAP_HOSTS <= contract.EXPECTED_MITM_HOSTS


def test_is_github_ish():
    assert contract.is_github_ish("copilot-api.example.ghe.com")
    assert contract.is_github_ish("api.github.com")
    assert contract.is_github_ish("api.githubcopilot.com")
    assert not contract.is_github_ish("registry.npmjs.org")
    assert not contract.is_github_ish("example.com")
