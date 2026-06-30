import proxy
from ctc.contract import BILLABLE_HOST


def test_responses_is_billable():
    assert proxy.is_billable(BILLABLE_HOST, "POST", "/responses") is True
    assert proxy.is_billable(BILLABLE_HOST, "POST", "/responses?stream=1") is True


def test_responses_not_billable_on_other_host():
    assert proxy.is_billable("api.github.com", "POST", "/responses") is False
