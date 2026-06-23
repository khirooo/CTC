import pytest
from ctc.domain.deployment import DeploymentConfig


def test_defaults_match_shipped_target_shape():
    cfg = DeploymentConfig.from_env({})
    assert cfg.auth_mode == "email"
    assert cfg.web_transport == "http"
    assert cfg.email_backend == "console"


def test_reads_overrides():
    cfg = DeploymentConfig.from_env({
        "CTC_AUTH_MODE": "ghe_oauth",
        "CTC_WEB_TRANSPORT": "https",
        "CTC_EMAIL_BACKEND": "smtp",
    })
    assert cfg.auth_mode == "ghe_oauth"
    assert cfg.web_transport == "https"
    assert cfg.email_backend == "smtp"


@pytest.mark.parametrize("key,bad", [
    ("CTC_AUTH_MODE", "ldap"),
    ("CTC_WEB_TRANSPORT", "ftp"),
    ("CTC_EMAIL_BACKEND", "smtp2"),
])
def test_invalid_value_raises(key, bad):
    with pytest.raises(ValueError) as e:
        DeploymentConfig.from_env({key: bad})
    assert key in str(e.value)
