import pytest
from ctc.domain.deployment import DeploymentConfig


def test_default_web_transport():
    cfg = DeploymentConfig.from_env({})
    assert cfg.web_transport == "http"


def test_reads_override():
    cfg = DeploymentConfig.from_env({"CTC_WEB_TRANSPORT": "https"})
    assert cfg.web_transport == "https"


def test_invalid_value_raises():
    with pytest.raises(ValueError) as e:
        DeploymentConfig.from_env({"CTC_WEB_TRANSPORT": "ftp"})
    assert "CTC_WEB_TRANSPORT" in str(e.value)
