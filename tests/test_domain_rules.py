from ctc.domain.config import config
from ctc.domain.types import Role, Bucket, RequestStatus
from ctc.domain.rules import derive_status


def test_config_values():
    assert config.credit_to_euro_rate == 0.0088
    assert config.request_expiry_hours == 24
    assert config.cycle_reset_day == 1


def test_enum_values_match_stored_text():
    assert Role.GIVER.value == "giver"
    assert Bucket.POOL.value == "pool"
    assert RequestStatus.PARTIALLY_FUNDED.value == "partially_funded"
    assert RequestStatus.CANCELLED.value == "cancelled"


def test_derive_status():
    now = 1_000
    assert derive_status(0, 60, now + 1, now) == RequestStatus.OPEN
    assert derive_status(30, 60, now + 1, now) == RequestStatus.PARTIALLY_FUNDED
    assert derive_status(60, 60, now + 1, now) == RequestStatus.FULFILLED
    assert derive_status(10, 60, now - 1, now) == RequestStatus.EXPIRED
    # fulfilled beats expired
    assert derive_status(60, 60, now - 1, now) == RequestStatus.FULFILLED


def test_derive_status_cancelled_wins():
    now = 1_000
    assert derive_status(0, 60, now + 1, now, cancelled_at=now) == RequestStatus.CANCELLED
    # cancelled beats expired and partial
    assert derive_status(30, 60, now - 1, now, cancelled_at=now - 5) == RequestStatus.CANCELLED
