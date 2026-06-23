import pytest
from ctc.domain.deployment import DeploymentConfig


def test_app_origin_scheme_consistency_helper():
    from api_server import assert_transport_consistent
    # https transport + http origin → error
    with pytest.raises(ValueError):
        assert_transport_consistent(DeploymentConfig(web_transport="https",
                                                     auth_mode="email", email_backend="console"),
                                    "http://app")
    # consistent → ok
    assert_transport_consistent(DeploymentConfig(web_transport="http",
                                                 auth_mode="email", email_backend="console"),
                                "http://app") is None
