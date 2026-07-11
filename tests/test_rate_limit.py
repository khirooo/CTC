import pytest
from aiohttp import web

from ctc.api.rate_limit import RateLimiter


def test_allows_up_to_limit_then_blocks():
    clock = [1000.0]
    rl = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        rl.check("pat", "u1", 5)          # 5 allowed
    with pytest.raises(web.HTTPTooManyRequests):
        rl.check("pat", "u1", 5)          # 6th blocked


def test_refills_over_time():
    clock = [1000.0]
    rl = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        rl.check("pat", "u1", 5)
    with pytest.raises(web.HTTPTooManyRequests):
        rl.check("pat", "u1", 5)
    clock[0] += 60                        # a full window later → bucket refilled
    rl.check("pat", "u1", 5)              # ok again


def test_partial_refill():
    clock = [1000.0]
    rl = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        rl.check("pat", "u1", 5)          # drained
    clock[0] += 12                        # 12s @ 5/60 tok/s = 1 token
    rl.check("pat", "u1", 5)              # exactly one available
    with pytest.raises(web.HTTPTooManyRequests):
        rl.check("pat", "u1", 5)


def test_keys_and_scopes_are_independent():
    clock = [1000.0]
    rl = RateLimiter(now=lambda: clock[0])
    for _ in range(5):
        rl.check("pat", "u1", 5)
    rl.check("pat", "u2", 5)              # different key unaffected
    rl.check("login", "u1", 5)           # different scope unaffected
