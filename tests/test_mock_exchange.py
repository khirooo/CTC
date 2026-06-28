from ctc import contract
from ctc.routing.mock_exchange import build_token_response


def test_build_token_response_sets_future_expiry():
    out = build_token_response(1_000_000)
    assert out["expires_at"] == 1_000_000 + contract.MOCK_TOKEN_TTL_SECONDS
    assert out["refresh_in"] == contract.MOCK_TOKEN_REFRESH_SECONDS


def test_build_token_response_token_is_nonempty_and_carries_exp():
    out = build_token_response(1_000_000)
    assert out["token"]
    assert f"exp={1_000_000 + contract.MOCK_TOKEN_TTL_SECONDS}" in out["token"]


def test_build_token_response_keeps_template_keys_and_endpoints():
    out = build_token_response(1_000_000)
    assert out["endpoints"]["api"] == f"https://copilot-api.{contract.GHE_DOMAIN}"
    assert out["chat_enabled"] is True


def test_build_token_response_does_not_mutate_template():
    import copy
    before = copy.deepcopy(contract.MOCK_TOKEN_TEMPLATE)
    build_token_response(1_000_000)
    assert contract.MOCK_TOKEN_TEMPLATE == before
