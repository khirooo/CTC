import pytest
from ctc.domain.deployment import DeploymentConfig


def test_app_origin_scheme_consistency_helper():
    from api_server import assert_transport_consistent
    # https transport + http origin → error
    with pytest.raises(ValueError):
        assert_transport_consistent(DeploymentConfig(web_transport="https"),
                                    "http://app")
    # consistent → ok
    assert_transport_consistent(DeploymentConfig(web_transport="http"),
                                "http://app") is None


# --- GHE domain reaching the control plane -------------------------------------
#
# ctc/contract.py derives the Copilot API host from GHE_DOMAIN at import time. The
# control plane calls that host for the PAT-health permission probe, so a missing
# GHE_DOMAIN there leaves it probing the placeholder domain: every probe fails to
# resolve, is treated as "no opinion", and an under-scoped PAT keeps a "valid"
# verdict forever. Nothing else in the control plane reads GHE_DOMAIN, so without
# this check the omission is completely silent.

def test_placeholder_ghe_domain_against_a_real_api_base_is_fatal():
    from api_server import assert_ghe_domain_consistent
    with pytest.raises(ValueError) as e:
        assert_ghe_domain_consistent("https://api.acme-corp.example",
                                     ghe_domain="example.ghe.com")
    assert "GHE_DOMAIN" in str(e.value)


def test_consistent_domain_and_api_base_is_ok():
    from api_server import assert_ghe_domain_consistent
    assert assert_ghe_domain_consistent("https://api.acme-corp.example",
                                        ghe_domain="acme-corp.example") is None


def test_placeholder_everywhere_is_ok_for_local_dev():
    # A dev/test deployment left entirely on defaults is coherent, not broken.
    from api_server import assert_ghe_domain_consistent
    assert assert_ghe_domain_consistent("https://api.example.ghe.com",
                                        ghe_domain="example.ghe.com") is None


def test_divergent_but_non_placeholder_domain_is_allowed():
    # A deployment whose API host genuinely differs from the web domain is
    # unusual but legitimate — warn-worthy, never fatal.
    from api_server import assert_ghe_domain_consistent
    assert assert_ghe_domain_consistent("https://ghe-api.acme-corp.example",
                                        ghe_domain="acme-corp.example") is None
