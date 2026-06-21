import proxy


def test_is_billable_matches_only_completion_posts():
    assert proxy.is_billable("copilot-api.example.ghe.com", "POST", "/chat/completions")
    assert proxy.is_billable("copilot-api.example.ghe.com", "POST", "/v1/messages")
    # query string tolerated
    assert proxy.is_billable("copilot-api.example.ghe.com", "POST", "/v1/messages?x=1")
    # wrong method / host / path
    assert not proxy.is_billable("copilot-api.example.ghe.com", "GET", "/v1/messages")
    assert not proxy.is_billable("api.example.ghe.com", "POST", "/chat/completions")
    assert not proxy.is_billable("copilot-api.example.ghe.com", "POST", "/models")


def test_strip_bearer():
    assert proxy.strip_bearer("Bearer ghp_x") == "ghp_x"
    assert proxy.strip_bearer("token ghp_y") == "ghp_y"
    assert proxy.strip_bearer("ghp_z") == "ghp_z"
    assert proxy.strip_bearer("") == ""
