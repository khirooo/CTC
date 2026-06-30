import asyncio
from ctc.metering.live_quota import LiveQuotaCache

def _run(coro): return asyncio.new_event_loop().run_until_complete(coro)

def make(calls, pats=None, fail=False):
    if pats is None:
        pats = {"g1": "pat1"}
    async def fetch_user(pat):
        calls.append(pat)
        if fail: raise RuntimeError("boom")
        return {"quota_snapshots": {"premium_interactions":
                {"entitlement": 4000, "remaining": 1500}}, "quota_reset_date": "2026-07-01"}
    t = [100.0]
    return LiveQuotaCache(lambda gid: pats.get(gid), fetch_user, ttl=60,
                          clock=lambda: t[0]), t

def test_get_returns_live_value():
    calls=[]; c,_ = make(calls)
    assert _run(c.get("g1")) == {"entitlement":4000,"remaining":1500,"reset_date":"2026-07-01"}
    assert calls == ["pat1"]

def test_caches_within_ttl():
    calls=[]; c,_ = make(calls)
    _run(c.get("g1")); _run(c.get("g1"))
    assert calls == ["pat1"]  # one fetch

def test_refetches_after_ttl():
    calls=[]; c,t = make(calls)
    _run(c.get("g1")); t[0]+=61; _run(c.get("g1"))
    assert calls == ["pat1","pat1"]

def test_none_on_fetch_failure_and_retries():
    calls=[]; c,_ = make(calls, fail=True)
    assert _run(c.get("g1")) is None
    assert _run(c.get("g1")) is None  # failed results are NOT cached -> retried
    assert calls == ["pat1","pat1"]

def test_none_when_no_pat():
    calls=[]; c,_ = make(calls, pats={})
    assert _run(c.get("g1")) is None
    assert calls == []

def test_set_exhausted_serves_zero_without_fetch():
    calls=[]; c,_ = make(calls)
    c.set_exhausted("g1")
    assert _run(c.remaining("g1")) == 0
    assert calls == []
