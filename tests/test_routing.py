import proxy

GHE = "api.example.ghe.com"


def test_ghe_host_is_mitm_no_remap():
    assert proxy.decide_route("api.example.ghe.com", 443, GHE) == (True, "api.example.ghe.com", 443)


def test_npm_is_blind():
    do_mitm, host, _ = proxy.decide_route("registry.npmjs.org", 443, GHE)
    assert do_mitm is False and host == "registry.npmjs.org"


def test_githubcopilot_saas_is_blind():
    assert proxy.decide_route("api.githubcopilot.com", 443, GHE)[0] is False


def test_localhost_alias_remaps_to_real_ghe():
    assert proxy.decide_route("api.localhost", 8080, GHE) == (True, GHE, 443)


def test_api_github_is_mitm_but_not_remapped():
    do_mitm, host, _ = proxy.decide_route("api.github.com", 443, GHE)
    assert do_mitm is True and host == "api.github.com"
