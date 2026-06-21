import proxy
from ctc import contract


def test_no_mock_user_constants():
    assert not hasattr(proxy, "MOCK_USER")
    assert not hasattr(proxy, "MOCK_COPILOT_USER")


def test_ghe_hosts_subset_of_mitm_hosts():
    # Every GHE host that gets the swap must actually be MITM'd.
    assert proxy.SWAP_HOSTS <= proxy.MITM_HOSTS


def test_mitm_hosts_match_contract_exactly():
    # The refactor must not change the live host set.
    assert proxy.MITM_HOSTS == {
        "api.example.ghe.com", "example.ghe.com", "copilot-api.example.ghe.com",
        "api.github.com", "api.localhost", "localhost",
    }
    assert proxy.MITM_HOSTS == contract.EXPECTED_MITM_HOSTS


def test_ghe_hosts_match_contract_exactly():
    assert proxy.SWAP_HOSTS == {
        "api.example.ghe.com", "example.ghe.com", "copilot-api.example.ghe.com",
    }
    assert proxy.SWAP_HOSTS == contract.SWAP_HOSTS


def test_billable_paths_match_contract():
    assert proxy._BILLABLE_PATHS == {"/chat/completions", "/v1/messages"}
