from ctc.domain.config import config, NANO_PER_AIU, _free_allowance_nano
from ctc.domain.types import Role, Bucket, RequestStatus
from ctc.domain.rules import derive_status, next_bucket


def test_config_values():
    assert config.free_allowance == 300 * NANO_PER_AIU  # 300 AIU in nano-AIU
    assert config.credit_to_euro_rate == 0.0088
    assert config.request_expiry_hours == 24
    assert config.cycle_reset_day == 1


def test_free_allowance_env_override(monkeypatch):
    monkeypatch.setenv("CTC_FREE_ALLOWANCE_AIU", "500")
    assert _free_allowance_nano() == 500 * NANO_PER_AIU
    monkeypatch.delenv("CTC_FREE_ALLOWANCE_AIU", raising=False)
    assert _free_allowance_nano() == 300 * NANO_PER_AIU


def test_enum_values_match_stored_text():
    assert Role.GIVER.value == "giver"
    assert Bucket.POOL.value == "pool"
    assert RequestStatus.PARTIALLY_FUNDED.value == "partially_funded"


def test_derive_status():
    now = 1_000
    assert derive_status(0, 60, now + 1, now) == RequestStatus.OPEN
    assert derive_status(30, 60, now + 1, now) == RequestStatus.PARTIALLY_FUNDED
    assert derive_status(60, 60, now + 1, now) == RequestStatus.FULFILLED
    assert derive_status(10, 60, now - 1, now) == RequestStatus.EXPIRED
    # fulfilled beats expired
    assert derive_status(60, 60, now - 1, now) == RequestStatus.FULFILLED


def test_next_bucket_consumer_prefers_pool_then_grant():
    assert next_bucket(Role.CONSUMER, allowance_remaining=100, pool_available=50) == Bucket.POOL
    assert next_bucket(Role.CONSUMER, allowance_remaining=0, pool_available=50, grant_remaining=20) == Bucket.GRANT
    assert next_bucket(Role.CONSUMER, allowance_remaining=100, pool_available=0, grant_remaining=20) == Bucket.GRANT
    assert next_bucket(Role.CONSUMER, allowance_remaining=0, pool_available=0, grant_remaining=0) is None


def test_next_bucket_giver_prefers_own_then_grant():
    assert next_bucket(Role.GIVER, personal_remaining=100) == Bucket.OWN
    assert next_bucket(Role.GIVER, personal_remaining=0, grant_remaining=20) == Bucket.GRANT
    assert next_bucket(Role.GIVER, personal_remaining=0, grant_remaining=0) is None
